"""剂量达标判定（计划 02 Task 4）：浓度估计区间 vs 文献起效浓度。

low/high/confidence 均为推断引擎输出的**模型估计值**（约束采样 p5/p95），
非实测浓度；dose 判定仅表达「估计区间与文献起效线的相对关系」，
不构成功效承诺。产品无推断结果（conc_low 为 NULL）时不输出判定。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models.ingredient import EfficacyAssertion
from ..models.product import ProductIngredient


def verdict_for(low: float, high: float, eff_low: float | None, eff_high: float | None,
                *, is_trace: bool = False) -> str:
    """判定估计区间 [low, high] 相对文献起效线 eff_low 的达标状态。

    - eff_low 为 None → "unknown"（无法判定：缺文献浓度）
    - is_trace 且 eff_low < 0.1 → "trace_level"（总纲 v4.1 §三 I2：
      成分处于 ≤0.1% 微量段，而文献起效线本身也在微量区间——肽类等
      ppm 级即起效——则「存在即可能起效」，达标与否依赖原料披露，
      不按推断区间判不足）
    - low >= eff_low → "effective"（达标：区间整体过起效线）
    - high < eff_low → "insufficient"（不足：区间整体低于起效线）
    - 其他 → "uncertain"（存疑：区间横跨起效线）

    eff_high 保留文献区间语义入参，当前判定只锚定起效下限。
    """
    if eff_low is None:
        return "unknown"
    if is_trace and eff_low < 0.1:
        return "trace_level"
    if low >= eff_low:
        return "effective"
    if high < eff_low:
        return "insufficient"
    return "uncertain"


def dose_verdicts(session: Session, product_id: int) -> list[dict] | None:
    """组装产品的浓度估计 + 逐断言剂量判定；无推断结果（无 conc_low 非空行）返回 None。

    每个估计项：{ingredient_id, inci_name, cn_name, low, high, confidence,
    disclosed_conc, dose: [{efficacy, eff_low, eff_high, verdict}]}；
    一个成分有多条功效断言时逐条输出判定。
    """
    links = (
        session.query(ProductIngredient)
        .filter(
            ProductIngredient.product_id == product_id,
            ProductIngredient.conc_low.isnot(None),
        )
        .order_by(ProductIngredient.position)
        .all()
    )
    if not links:
        return None
    estimates: list[dict] = []
    for link in links:
        ing = link.ingredient
        assertions = (
            session.query(EfficacyAssertion)
            .filter_by(ingredient_id=ing.id)
            .order_by(EfficacyAssertion.id)
            .all()
        )
        dose = [
            {
                "efficacy": a.efficacy,
                "eff_low": a.effective_conc_low,
                "eff_high": a.effective_conc_high,
                "verdict": verdict_for(
                    link.conc_low, link.conc_high,
                    a.effective_conc_low, a.effective_conc_high,
                    is_trace=link.is_trace,
                ),
            }
            for a in assertions
        ]
        estimates.append({
            "ingredient_id": ing.id,
            "inci_name": ing.inci_name,
            "cn_name": ing.cn_name,
            "low": link.conc_low,          # 模型估计区间下限（p5，%）
            "high": link.conc_high,        # 模型估计区间上限（p95，%）
            "confidence": link.conc_confidence,
            "disclosed_conc": link.disclosed_conc,
            "dose": dose,
        })
    return estimates
