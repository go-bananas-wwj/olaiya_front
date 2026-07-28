"""剂量达标判定单测（计划 02 Task 4 + 总纲 v4.1 §三 I2）。

verdict_for 四分支：unknown / effective / insufficient / uncertain，
语义为「浓度估计区间 [low, high] 相对文献起效线 eff_low 的关系」；
另加 ppm 微量分支 trace_level：微量段成分（is_trace）且文献起效线
本身低于 0.1% 微量分界线时，「存在即可能起效，依赖原料披露」。
"""

import pytest

from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.models.product import Product, ProductIngredient
from app.services.dosecheck import dose_verdicts, verdict_for


@pytest.mark.parametrize(
    "low,high,eff_low,eff_high,expected",
    [
        # unknown：缺文献起效浓度（eff_low 为 None），无论区间如何都不可判定
        (1.0, 5.0, None, None, "unknown"),
        (10.0, 20.0, None, 5.0, "unknown"),
        # effective：区间整体过起效线（low >= eff_low，含恰等边界）
        (2.0, 8.0, 2.0, 5.0, "effective"),
        (3.0, 9.0, 2.0, None, "effective"),   # eff_high 缺失不影响判定
        (0.5, 1.0, 0.1, 0.5, "effective"),
        # insufficient：区间整体低于起效线（high < eff_low，严格小于）
        (0.1, 0.5, 2.0, 5.0, "insufficient"),
        (0.05, 0.09, 0.1, None, "insufficient"),
        # uncertain：区间横跨起效线（low < eff_low <= high，含 high 恰等边界）
        (1.0, 3.0, 2.0, 5.0, "uncertain"),
        (0.5, 2.0, 2.0, 5.0, "uncertain"),    # high == eff_low 不算不足
        (1.0, 10.0, 2.0, None, "uncertain"),
    ],
)
def test_verdict_for_branches(low, high, eff_low, eff_high, expected):
    assert verdict_for(low, high, eff_low, eff_high) == expected


@pytest.mark.parametrize(
    "low,high,eff_low,eff_high,expected",
    [
        # trace_level：微量段成分且起效线本身处于微量区间（<0.1%），存在即可能起效
        (0.001, 0.01, 0.0003, None, "trace_level"),    # 阿基瑞林 3ppm 活性物口径
        (0.01, 0.09, 0.05, 0.08, "trace_level"),       # 四分支本为 uncertain，trace 优先
        (0.05, 0.09, 0.01, None, "trace_level"),       # 四分支本为 effective，trace 仍优先
        (0.001, 0.005, 0.099, None, "trace_level"),    # eff_low 贴近 0.1 仍属微量口径
        # unknown 优先：缺文献起效浓度时即使 is_trace 也不判 trace_level
        (0.001, 0.01, None, None, "unknown"),
        # is_trace=True 但 eff_low >= 0.1：起效线不在微量区间，仍走四分支
        (0.001, 0.01, 0.1, None, "insufficient"),      # eff_low 恰等 0.1 不算 ppm 口径
        (0.01, 0.05, 0.5, 1.0, "insufficient"),
        (0.05, 0.5, 0.2, None, "uncertain"),
    ],
)
def test_verdict_for_trace_branch(low, high, eff_low, eff_high, expected):
    assert verdict_for(low, high, eff_low, eff_high, is_trace=True) == expected


def test_verdict_for_ppm_eff_low_without_trace_flag():
    """非微量段成分即使 eff_low < 0.1，也只走既有四分支（主段区间整体过线即达标）。"""
    assert verdict_for(0.5, 1.0, 0.05, None) == "effective"
    assert verdict_for(0.001, 0.01, 0.05, None) == "insufficient"
    assert verdict_for(0.01, 0.5, 0.05, None) == "uncertain"


def _product_with_trace_link(session, *, is_trace, eff_low):
    p = Product(name="测试霜", brand="测试牌", category="面霜", price_current=99.0)
    ing = Ingredient(inci_name="ACETYL HEXAPEPTIDE-8", cn_name="乙酰基六肽-8")
    ev = Evidence(type=EvidenceType.PAPER, title="测试文献", source="测试期刊", year=2002)
    session.add_all([p, ing, ev])
    session.flush()
    session.add(EfficacyAssertion(ingredient_id=ing.id, efficacy="抗皱",
                                  evidence_id=ev.id, effective_conc_low=eff_low))
    session.add(ProductIngredient(product_id=p.id, ingredient_id=ing.id, position=5,
                                  is_trace=is_trace, conc_low=0.001, conc_high=0.01))
    session.commit()
    return p


def test_dose_verdicts_passes_is_trace_to_verdict(session):
    """dose_verdicts 必须把 ProductIngredient.is_trace 传入判定：微量段 + ppm 起效线 → trace_level。"""
    p = _product_with_trace_link(session, is_trace=True, eff_low=0.0003)
    estimates = dose_verdicts(session, p.id)
    assert estimates[0]["dose"][0]["verdict"] == "trace_level"


def test_dose_verdicts_main_segment_ppm_eff_low_keeps_four_branch(session):
    """同一 ppm 起效线，主段成分不触发 trace_level（区间过线按四分支判达标）。"""
    p = _product_with_trace_link(session, is_trace=False, eff_low=0.0003)
    estimates = dose_verdicts(session, p.id)
    assert estimates[0]["dose"][0]["verdict"] == "effective"
