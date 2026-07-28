"""浓度区间推断引擎（约束采样）测试。

覆盖简报测试要点：
- 约束恒成立：全样本满足降序 / 微量线 ≤0.1 / Σ≈100 / upper_cap / 水相先验
- 可复现性：同输入同 seed 输出逐位一致
- 修丽可 CE 形态（12 成分：水首位 + 微量段 2 个）区间合理性
- 约束矛盾显式报错
- confidence ∈ [0,1] 且随区间宽度单调减
"""

import numpy as np
import pytest

from app.services.concentration import (
    ConcentrationEstimate,
    IngredientInput,
    _sample_concentrations,
    estimate_concentrations,
)

TOL = 1e-9


def _random_ingredients(rng: np.random.Generator) -> list[IngredientInput]:
    """生成一批随机但必然可行的成分表（主段 cap 宽松，微量段 cap ≥0.05）。"""
    m = int(rng.integers(2, 8))
    t = int(rng.integers(0, 4))
    items: list[IngredientInput] = []
    for i in range(m):
        cap = None if rng.random() < 0.5 else float(rng.uniform(60.0, 100.0))
        items.append(IngredientInput(inci_name=f"MAIN-{i}", upper_cap=cap))
    for j in range(t):
        cap = None if rng.random() < 0.5 else float(rng.uniform(0.05, 0.1))
        items.append(IngredientInput(inci_name=f"TRACE-{j}", is_trace=True, upper_cap=cap))
    return items


def _assert_sample_invariants(samples: np.ndarray, items: list[IngredientInput], leave_on: bool):
    main_cols = [k for k, x in enumerate(items) if not x.is_trace]
    trace_cols = [k for k, x in enumerate(items) if x.is_trace]
    for row in samples:
        # Σ≈100
        assert abs(row.sum() - 100.0) < 1e-6
        # 主段降序
        main_vals = row[main_cols]
        assert np.all(np.diff(main_vals) <= TOL)
        # 微量线：微量段 ≤0.1，主段末位 ≥0.1
        if trace_cols:
            assert np.all(row[trace_cols] <= 0.1 + TOL)
            assert np.all(row[trace_cols] >= 0.0)
        assert main_vals[-1] >= 0.1 - TOL
        # 主段全体 ≥ 微量段全体（降序跨段成立）
        if trace_cols:
            assert main_vals[-1] >= row[trace_cols].max() - TOL
        # upper_cap
        for k, x in enumerate(items):
            if x.upper_cap is not None:
                assert row[k] <= x.upper_cap + TOL
        # 水相先验
        lo, hi = (50.0, 95.0) if leave_on else (40.0, 90.0)
        for k, x in enumerate(items):
            if x.water and not x.is_trace:
                assert lo - TOL <= row[k] <= hi + TOL


# ---------------------------------------------------------------- 约束恒成立


@pytest.mark.parametrize("seed", range(10))
def test_constraints_hold_random_batches(seed):
    rng = np.random.default_rng(10_000 + seed)
    items = _random_ingredients(rng)
    leave_on = bool(rng.random() < 0.5)
    samples = _sample_concentrations(items, leave_on=leave_on, n_samples=300, seed=seed)
    assert samples.shape == (300, len(items))
    _assert_sample_invariants(samples, items, leave_on)


@pytest.mark.parametrize("leave_on,expected_range", [(True, (50.0, 95.0)), (False, (40.0, 90.0))])
def test_water_prior_hold_all_samples(leave_on, expected_range):
    items = [
        IngredientInput(inci_name="AQUA", water=True),
        IngredientInput(inci_name="B"),
        IngredientInput(inci_name="C"),
        IngredientInput(inci_name="D"),
        IngredientInput(inci_name="E-TRACE", is_trace=True),
    ]
    samples = _sample_concentrations(items, leave_on=leave_on, n_samples=500, seed=7)
    _assert_sample_invariants(samples, items, leave_on)
    lo, hi = expected_range
    assert np.all(samples[:, 0] >= lo - TOL)
    assert np.all(samples[:, 0] <= hi + TOL)


def test_trace_segment_always_below_line():
    items = [IngredientInput(inci_name=f"M{i}") for i in range(4)] + [
        IngredientInput(inci_name=f"T{j}", is_trace=True) for j in range(3)
    ]
    samples = _sample_concentrations(items, leave_on=True, n_samples=500, seed=3)
    assert np.all(samples[:, 4:] <= 0.1 + TOL)
    assert np.all(samples[:, 3] >= 0.1 - TOL)


# ---------------------------------------------------------------- 可复现性


def test_reproducible_bitwise():
    items = _random_ingredients(np.random.default_rng(0))
    items[0] = IngredientInput(inci_name="AQUA", water=True, upper_cap=90.0)
    a = estimate_concentrations(items, leave_on=True, n_samples=500, seed=123)
    b = estimate_concentrations(items, leave_on=True, n_samples=500, seed=123)
    for ea, eb in zip(a, b):
        assert (ea.low, ea.high, ea.confidence) == (eb.low, eb.high, eb.confidence)
    sa = _sample_concentrations(items, leave_on=True, n_samples=500, seed=123)
    sb = _sample_concentrations(items, leave_on=True, n_samples=500, seed=123)
    assert np.array_equal(sa, sb)


def test_output_schema_and_order():
    items = _random_ingredients(np.random.default_rng(5))
    est = estimate_concentrations(items, leave_on=False, n_samples=300, seed=9)
    assert len(est) == len(items)
    for e, x in zip(est, items):
        assert isinstance(e, ConcentrationEstimate)
        assert e.inci_name == x.inci_name  # 输出顺序与输入一致
        assert 0.0 <= e.low <= e.high <= 100.0


# ---------------------------------------------------------------- 修丽可 CE 形态


def _skinceuticals_ce() -> list[IngredientInput]:
    """修丽可 CE 精华形态：12 成分，水首位，微量段 2 个。"""
    return [
        IngredientInput(inci_name="AQUA/WATER", water=True),
        IngredientInput(inci_name="ETHOXYDIGLYCOL"),
        IngredientInput(inci_name="ASCORBIC ACID", upper_cap=20.0),
        IngredientInput(inci_name="GLYCERIN"),
        IngredientInput(inci_name="PROPYLENE GLYCOL"),
        IngredientInput(inci_name="LAURETH-23"),
        IngredientInput(inci_name="PHENOXYETHANOL", upper_cap=1.0),
        IngredientInput(inci_name="TOCOPHEROL"),
        IngredientInput(inci_name="TRIETHANOLAMINE"),
        IngredientInput(inci_name="FERULIC ACID"),
        IngredientInput(inci_name="PANTHENOL", is_trace=True),
        IngredientInput(inci_name="SODIUM HYALURONATE", is_trace=True),
    ]


def test_skinceuticals_ce_water_interval_dominates():
    est = estimate_concentrations(_skinceuticals_ce(), leave_on=True, n_samples=2000, seed=42)
    water = est[0]
    assert water.inci_name == "AQUA/WATER"
    # 水的 low 全表最大
    assert water.low == max(e.low for e in est)
    # 水的区间中位数全表最大
    water_mid = (water.low + water.high) / 2
    assert water_mid == max((e.low + e.high) / 2 for e in est)
    # 微量段 high 不超 0.1
    assert est[-1].high <= 0.1 + TOL
    assert est[-2].high <= 0.1 + TOL
    # cap 生效：苯氧乙醇 ≤1.0
    phenoxy = est[6]
    assert phenoxy.high <= 1.0 + TOL


# ---------------------------------------------------------------- 约束矛盾


def test_contradiction_water_cap_vs_prior_raises():
    items = [
        IngredientInput(inci_name="AQUA", water=True, upper_cap=30.0),  # cap 30 < 先验 50
        IngredientInput(inci_name="B"),
    ]
    with pytest.raises(ValueError, match="矛盾|conflict|infeasible"):
        estimate_concentrations(items, leave_on=True)


def test_contradiction_unreachable_caps_raise():
    # 两主段：首位 cap 0.5，次位 cap 99.5 → Σ=100 不可达
    items = [
        IngredientInput(inci_name="A", upper_cap=0.5),
        IngredientInput(inci_name="B", upper_cap=99.5),
    ]
    with pytest.raises(ValueError):
        estimate_concentrations(items, leave_on=True, n_samples=100, seed=1)


def test_contradiction_main_cap_below_trace_line():
    items = [
        IngredientInput(inci_name="A"),
        IngredientInput(inci_name="B", upper_cap=0.05),  # 主段末位必须 ≥0.1
    ]
    with pytest.raises(ValueError):
        estimate_concentrations(items, leave_on=True, n_samples=100, seed=1)


# ---------------------------------------------------------------- confidence


def test_confidence_bounds_and_monotonic_in_width():
    items = _random_ingredients(np.random.default_rng(11))
    est = estimate_concentrations(items, leave_on=True, n_samples=500, seed=77)
    for e in est:
        assert 0.0 <= e.confidence <= 1.0
    # 同先验标志下，区间越宽 confidence 越低（严格按公式单调）
    for flag in (False, True):
        group = [
            e
            for e, x in zip(est, items)
            if (x.upper_cap is not None or x.water) == flag
        ]
        widths = [e.high - e.low for e in group]
        confs = [e.confidence for e in group]
        order = np.argsort(widths)
        sorted_confs = np.array(confs)[order]
        assert np.all(np.diff(sorted_confs) <= TOL)


def test_confidence_formula():
    items = [
        IngredientInput(inci_name="AQUA", water=True),
        IngredientInput(inci_name="B", upper_cap=50.0),
        IngredientInput(inci_name="C"),
    ]
    est = estimate_concentrations(items, leave_on=True, n_samples=500, seed=5)
    for e, x in zip(est, items):
        has_prior = x.upper_cap is not None or x.water
        expected = 0.5 + 0.3 * has_prior + 0.2 * (1 - (e.high - e.low) / 100.0)
        assert e.confidence == pytest.approx(min(1.0, max(0.0, expected)), abs=1e-12)
