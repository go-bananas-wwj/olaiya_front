"""浓度推断执行器与锚点校准测试（计划 02 Task 3）。

- assemble_inputs：cap 取各先验 min（None 不参与）、驻留/淋洗判定、
  水相标记规则（按名判定且仅位次 1 的水适用水相先验）
- anchor_hit：披露值 ±20% 相对容差的命中判定边界
- run_inference：玩具产品（水/烟酰胺/苯氧乙醇 cap=1.0 + 微量段 1 个）
  字段回写非空、cap 生效（苯氧乙醇 conc_high ≤1.0）、幂等
- 校准先验（CALIBRATED_*）下引擎不变量仍成立
"""

import numpy as np
import pytest

from app.models.ingredient import Ingredient
from app.models.product import Product, ProductIngredient
from app.services.concentration import IngredientInput, _sample_concentrations
from data.tools.run_inference import (
    CALIBRATED_DIRICHLET_ALPHA,
    CALIBRATED_DIRICHLET_DECAY,
    CALIBRATED_MAIN_FLOOR,
    CALIBRATED_WATER_PRIOR_LEAVE_ON,
    anchor_hit,
    assemble_inputs,
    is_leave_on,
    run_inference,
)


def _make_product(session, *, category="精华", with_anchor=False):
    """玩具产品：水 / 烟酰胺 / 苯氧乙醇(legal_cap=1.0) / 微量段透明质酸钠。"""
    water = Ingredient(inci_name="WATER", cn_name="水")
    niacinamide = Ingredient(inci_name="NIACINAMIDE", cn_name="烟酰胺")
    phenoxy = Ingredient(inci_name="PHENOXYETHANOL", cn_name="苯氧乙醇", legal_cap=1.0)
    ha = Ingredient(inci_name="SODIUM HYALURONATE", cn_name="透明质酸钠")
    product = Product(name="玩具精华", brand="TEST", category=category)
    session.add_all([water, niacinamide, phenoxy, ha, product])
    session.flush()
    rows = [
        ProductIngredient(product_id=product.id, ingredient_id=water.id, position=1),
        ProductIngredient(
            product_id=product.id,
            ingredient_id=niacinamide.id,
            position=2,
            disclosed_conc=5.0 if with_anchor else None,
        ),
        ProductIngredient(product_id=product.id, ingredient_id=phenoxy.id, position=3),
        ProductIngredient(product_id=product.id, ingredient_id=ha.id, position=4, is_trace=True),
    ]
    session.add_all(rows)
    session.commit()
    return product, rows


# ---------------------------------------------------------------- anchor_hit


@pytest.mark.parametrize(
    "low,high,disclosed,expected",
    [
        (10.0, 20.0, 15.0, True),
        (10.0, 20.0, 10.0 * 0.8, True),   # 恰在 low×0.8 边界（含）
        (10.0, 20.0, 20.0 * 1.2, True),   # 恰在 high×1.2 边界（含）
        (10.0, 20.0, 7.9, False),         # 低于 low×0.8
        (10.0, 20.0, 24.1, False),        # 高于 high×1.2
    ],
)
def test_anchor_hit_tolerance(low, high, disclosed, expected):
    assert anchor_hit(low, high, disclosed) is expected


# ---------------------------------------------------------------- assemble_inputs


def test_assemble_inputs_cap_min_excludes_none(session):
    """cap = min(legal_cap, iecic 按 leave_on, cir_high, sccs)，None 不参与。"""
    ing = Ingredient(
        inci_name="X",
        cn_name="X",
        legal_cap=2.0,
        iecic_max_leave_on=0.8,
        iecic_max_rinse_off=3.0,
        cir_conc_high=None,
        sccs_limit=1.5,
    )
    water = Ingredient(inci_name="WATER", cn_name="水")
    product = Product(name="p", brand="b", category="精华")
    session.add_all([ing, water, product])
    session.flush()
    session.add_all(
        [
            ProductIngredient(product_id=product.id, ingredient_id=water.id, position=1),
            ProductIngredient(product_id=product.id, ingredient_id=ing.id, position=2),
        ]
    )
    session.commit()
    by_id = {i.id: i for i in session.query(Ingredient).all()}

    items, leave_on = assemble_inputs(product, by_id)
    assert leave_on is True
    assert items[1].upper_cap == pytest.approx(0.8)  # min(2.0, 0.8, 1.5)

    product.category = "洗发水"
    session.commit()
    items, leave_on = assemble_inputs(product, by_id)
    assert leave_on is False
    assert items[1].upper_cap == pytest.approx(1.5)  # min(2.0, 3.0, 1.5)，淋洗用 rinse_off


def test_assemble_inputs_water_flag_only_at_first_position(session):
    """水按名判定，但仅位次 1 的水适用水相先验（SK-II 形态：水在中间的不得标记）。"""
    water = Ingredient(inci_name="WATER", cn_name="水")
    a = Ingredient(inci_name="A", cn_name="A")
    b = Ingredient(inci_name="B", cn_name="B")
    product = Product(name="p", brand="b", category="精华")
    session.add_all([water, a, b, product])
    session.flush()
    session.add_all(
        [
            ProductIngredient(product_id=product.id, ingredient_id=a.id, position=1),
            ProductIngredient(product_id=product.id, ingredient_id=water.id, position=2),
            ProductIngredient(product_id=product.id, ingredient_id=b.id, position=3),
        ]
    )
    session.commit()
    by_id = {i.id: i for i in session.query(Ingredient).all()}
    items, _ = assemble_inputs(product, by_id)
    assert [x.water for x in items] == [False, False, False]

    # cn_name == "水" 且位次 1 → 标记
    water2 = Ingredient(inci_name="AQUA", cn_name="水")
    product2 = Product(name="p2", brand="b", category="精华")
    session.add_all([water2, product2])
    session.flush()
    session.add(ProductIngredient(product_id=product2.id, ingredient_id=water2.id, position=1))
    session.add(ProductIngredient(product_id=product2.id, ingredient_id=a.id, position=2))
    session.commit()
    by_id = {i.id: i for i in session.query(Ingredient).all()}
    items, _ = assemble_inputs(product2, by_id)
    assert [x.water for x in items] == [True, False]


@pytest.mark.parametrize(
    "category,expected",
    [
        ("精华", True),
        ("面霜", True),
        (None, True),
        ("洗发水", False),
        ("洁面乳", False),
        ("沐浴油", False),
        ("卸妆水", False),
        ("发膜", False),
    ],
)
def test_is_leave_on(category, expected):
    assert is_leave_on(category) is expected


# ---------------------------------------------------------------- run_inference


def test_run_inference_writes_back_and_cap_enforced(session):
    _, rows = _make_product(session, with_anchor=True)
    stats = run_inference(session)
    assert stats["products_inferred"] == 1
    assert stats["anchors_total"] == 1
    for r in rows:
        assert r.conc_low is not None
        assert r.conc_high is not None
        assert r.conc_confidence is not None
        assert 0.0 <= r.conc_low <= r.conc_high <= 100.0
        assert 0.0 <= r.conc_confidence <= 1.0
    # cap 生效：苯氧乙醇 high ≤ 1.0
    assert rows[2].conc_high <= 1.0 + 1e-9
    # 微量段 high ≤ 0.1
    assert rows[3].conc_high <= 0.1 + 1e-9


def test_run_inference_idempotent(session):
    _, rows = _make_product(session)
    run_inference(session)
    first = [(r.conc_low, r.conc_high, r.conc_confidence) for r in rows]
    run_inference(session)
    second = [(r.conc_low, r.conc_high, r.conc_confidence) for r in rows]
    assert first == second


def test_run_inference_skips_products_without_positions(session):
    """position 全空的产品不参与推断。"""
    ing = Ingredient(inci_name="X", cn_name="X")
    product = Product(name="无序产品", brand="b", category="精华")
    session.add_all([ing, product])
    session.flush()
    session.add(ProductIngredient(product_id=product.id, ingredient_id=ing.id, position=None))
    session.commit()
    stats = run_inference(session)
    assert stats["products_inferred"] == 0
    assert stats["anchors_total"] == 0
    assert stats["coverage"] is None


# ---------------------------------------------------------------- 校准先验不变量


def test_calibrated_priors_keep_invariants():
    """校准先验下：Σ=100、主段降序、非水主段 ≥ floor、微量 ≤0.1、cap 成立。"""
    items = [IngredientInput(inci_name="AQUA", water=True)]
    items += [
        IngredientInput(inci_name=f"M{i}", upper_cap=20.0 if i % 3 == 0 else None)
        for i in range(15)
    ]
    items += [IngredientInput(inci_name=f"T{j}", is_trace=True) for j in range(3)]
    samples = _sample_concentrations(
        items,
        leave_on=True,
        n_samples=500,
        seed=5,
        dirichlet_alpha=CALIBRATED_DIRICHLET_ALPHA,
        main_floor=CALIBRATED_MAIN_FLOOR,
        water_prior=CALIBRATED_WATER_PRIOR_LEAVE_ON,
        dirichlet_decay=CALIBRATED_DIRICHLET_DECAY,
    )
    main_cols = [k for k, x in enumerate(items) if not x.is_trace]
    trace_cols = [k for k, x in enumerate(items) if x.is_trace]
    for row in samples:
        assert abs(row.sum() - 100.0) < 1e-6
        main_vals = row[main_cols]
        assert np.all(np.diff(main_vals) <= 1e-9)
        assert np.all(main_vals[1:] >= CALIBRATED_MAIN_FLOOR - 1e-9)
        assert np.all(row[trace_cols] <= 0.1 + 1e-9)
        for k, x in enumerate(items):
            if x.upper_cap is not None:
                assert row[k] <= x.upper_cap + 1e-9
