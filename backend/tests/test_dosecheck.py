"""剂量达标判定单测（计划 02 Task 4）。

verdict_for 四分支：unknown / effective / insufficient / uncertain，
语义为「浓度估计区间 [low, high] 相对文献起效线 eff_low 的关系」。
"""

import pytest

from app.services.dosecheck import verdict_for


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
