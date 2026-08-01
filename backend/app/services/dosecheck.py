"""剂量达标判定（计划 02 Task 4）：浓度估计区间 vs 文献起效浓度。

low/high/confidence 均为推断引擎输出的**模型估计值**（约束采样 p5/p95），
非实测浓度；dose 判定仅表达「估计区间与文献起效线的相对关系」，
不构成功效承诺。产品无推断结果（conc_low 为 NULL）时不输出判定。

每起效成本（总纲 I3，cost_per_effective_dose/cost_note）：折算浓度基准优先
取品牌官方披露锚点 disclosed_conc（官方数据），无披露时取推断区间中点
（模型估计值）；起效线取该成分全部断言中 effective_conc_low 的最小值
（达到最低文献起效线的折算成本）。产品有价格/规格、成分有起效线时才计算，
其余为 None；输出为估计值，展示必须带「估计」语义。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models.ingredient import EfficacyAssertion
from ..models.product import Product, ProductIngredient
from .cost import cost_per_effective_dose, parse_spec_ml

COST_NOTE = "按 1ml 日用量折算，估计值"


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
    disclosed_conc, dose: [{efficacy, eff_low, eff_high, verdict}],
    cost_per_effective_dose, cost_note}；一个成分有多条功效断言时逐条输出判定。
    cost_per_effective_dose 为每起效成本（元/天，按 1ml 用量折算，估计值），
    产品无价格/规格或成分无起效浓度断言时为 None。
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
    product = session.get(Product, product_id)
    price = product.price_current if product is not None else None
    spec_ml = parse_spec_ml(product.spec) if product is not None else None
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
        # 每起效成本：起效线取全部断言最低 effective_conc_low；
        # 折算浓度基准 = 官方披露锚点，无披露取推断区间中点（估计值）
        eff_lows = [a.effective_conc_low for a in assertions
                    if a.effective_conc_low is not None]
        cost = None
        if price is not None and spec_ml is not None and eff_lows:
            conc_mid = (link.disclosed_conc if link.disclosed_conc is not None
                        else (link.conc_low + link.conc_high) / 2)
            cost = cost_per_effective_dose(
                price=price, spec_ml=spec_ml, conc_mid=conc_mid, eff_low=min(eff_lows))
        estimates.append({
            "ingredient_id": ing.id,
            "inci_name": ing.inci_name,
            "cn_name": ing.cn_name,
            "low": link.conc_low,          # 模型估计区间下限（p5，%）
            "high": link.conc_high,        # 模型估计区间上限（p95，%）
            "confidence": link.conc_confidence,
            "disclosed_conc": link.disclosed_conc,
            "dose": dose,
            "cost_per_effective_dose": cost,  # 元/天（1ml 用量折算，估计值）
            "cost_note": COST_NOTE if cost is not None else None,
        })
    return estimates
