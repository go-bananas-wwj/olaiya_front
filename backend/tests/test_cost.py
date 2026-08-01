"""每起效成本（总纲 I3）：规格解析与成本公式。手算基准：59/30×2/10=0.393。"""

import pytest

from app.services.cost import cost_per_effective_dose, parse_spec_ml


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("30ml", 30.0),
        ("50g", 50.0),
        ("230ml", 230.0),
        ("48ml", 48.0),
        ("30 ml", 30.0),      # 数字与单位间允许空白
        ("30ML", 30.0),       # 大小写不敏感
        ("1.5g", 1.5),
        ("50克", 50.0),
        ("230毫升", 230.0),
        # 无法解析为单一容量/质量的一律 None
        ("30ml*2", None),     # 多支装不支持
        ("", None),
        ("一盒", None),
        ("1.5oz", None),
        ("ml", None),
        ("30ml 50g", None),
    ],
)
def test_parse_spec_ml(spec, expected):
    assert parse_spec_ml(spec) == expected


def test_parse_spec_ml_none_input():
    assert parse_spec_ml(None) is None


def test_cost_formula_hand_calc():
    """TO 烟酰胺口径：59 元 / 30ml × 起效 2% / 浓度 10% ≈ 0.393 元/天。"""
    cost = cost_per_effective_dose(price=59.0, spec_ml=30.0, conc_mid=10.0, eff_low=2.0)
    assert cost == pytest.approx(59.0 / 30.0 * 2.0 / 10.0, abs=1e-9)
    assert cost == pytest.approx(0.393, abs=1e-3)


def test_cost_scales_with_effective_line():
    """同产品起效线翻倍 → 成本翻倍（线性折算）。"""
    base = cost_per_effective_dose(price=1720.0, spec_ml=30.0, conc_mid=15.0, eff_low=8.0)
    double = cost_per_effective_dose(price=1720.0, spec_ml=30.0, conc_mid=15.0, eff_low=16.0)
    assert base == pytest.approx(1720.0 / 30.0 * 8.0 / 15.0, abs=1e-9)
    assert double == pytest.approx(2 * base, rel=1e-9)


def test_cost_conc_mid_non_positive_returns_none():
    """推断浓度中点 ≤0 无法折算，返回 None 而不是抛错或除零。"""
    assert cost_per_effective_dose(price=59.0, spec_ml=30.0, conc_mid=0.0, eff_low=2.0) is None
    assert cost_per_effective_dose(price=59.0, spec_ml=30.0, conc_mid=-1.0, eff_low=2.0) is None
