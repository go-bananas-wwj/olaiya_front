"""功效指纹（总纲 I3）：产品在功效空间中的稀疏向量表示。

每个功效维度的得分 = Σ_成分 (剂量因子 × 证据强度)；同一成分同一功效的
多条断言只取贡献最大的一条（max，不重复累加，避免同源/弱证据刷分）。
维度按规范功效族（efficacy_canonical，规则见 app.services.efficacy_canon）
聚合，避免自由文本功效（「美白」/「美白（抑制黑素小体转运）」）碎裂成多维；
断言未填 canonical 时按同一套规则实时映射兜底。
剂量因子表达「产品内估计剂量相对文献起效线的充足度」：推断区间充足 →
趋近 1（封顶 1.5）；剂量未知 → 保守默认 0.5（诚实默认，不虚报也不抹杀）；
微量段 ppm 级起效成分 → 1.0（存在即可能起效，与 dosecheck 的 trace_level
同口径）。指纹分值为相对排序信号，非功效承诺；推断浓度本身是模型估计值。

指纹 purity：法规类断言（evidence_level=regulation）、防腐功效族断言与原料商宣称
断言（evidence.type=supplier）不参与计分 —— 「准用防腐剂」等是合规事实而非皮肤
功效，其 0.9 的层级默认分会把防腐维刷成所有产品的公共高分维，压扁相似度区分度；
原料商宣称未经同行评议（降级通道），不计入证据支撑的功效信号。被排除条目仍入
detail 并标注 excluded/exclude_reason（诚实原则），coverage 以 excluded_count 计数。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models.evidence import EvidenceType
from ..models.ingredient import EfficacyAssertion
from ..models.product import ProductIngredient
from .efficacy_canon import canonicalize
from .evidence_level import REGULATION

UNKNOWN_DOSE_FACTOR = 0.5  # 无推断浓度时的保守剂量因子（诚实默认）

MAX_DOSE_FACTOR = 1.5  # 区间充足度上限：超过起效线最多按 1.5 倍计，防单成分刷分


def dose_factor(*, conc_low: float | None, conc_high: float | None,
                eff_low: float | None, is_trace: bool) -> tuple[float, str]:
    """剂量因子与口径说明。优先级自上而下：

    - eff_low 为 None（或 <= 0，非法值视同无基准）→ (1.0, "无起效浓度基准")：
      无文献起效线可锚定，证据强度全额计入
    - is_trace 且 eff_low < 0.1 → (1.0, "微量线 ppm 口径")：微量段成分而文献
      起效线本身在微量区间（肽类等 ppm 级即起效），存在即可能起效；
      与 dosecheck 的 trace_level 同口径，优先于推断区间分支
    - 有推断区间 → (min(区间中点/eff_low, 1.5), "推断区间")：中点充足度，
      cap 到 [0, 1.5]
    - 无推断区间（position NULL，未做浓度推断）→ (UNKNOWN_DOSE_FACTOR, "未知剂量")
    """
    if eff_low is None or eff_low <= 0:
        return 1.0, "无起效浓度基准"
    if is_trace and eff_low < 0.1:
        return 1.0, "微量线 ppm 口径"
    if conc_low is None or conc_high is None:
        return UNKNOWN_DOSE_FACTOR, "未知剂量"
    midpoint = (conc_low + conc_high) / 2
    ratio = midpoint / eff_low
    return min(max(ratio, 0.0), MAX_DOSE_FACTOR), "推断区间"


def _exclude_reason(a: EfficacyAssertion, canonical: str) -> str | None:
    """指纹计分排除规则，命中返回原因（不计分但仍入 detail），未命中返回 None。

    - 法规类断言（evidence_level == regulation）：合规事实不是皮肤功效；
    - 防腐功效族断言（efficacy 规范名为「防腐」，关键词规则命中即属该族）：
      防腐是配方稳定性要求，不是对皮肤的功效宣称；
    - 原料商宣称断言（evidence.type == supplier）：未经同行评议的供应商宣称
      （降级通道），不计入证据支撑的功效信号。
    """
    if a.evidence_level == REGULATION:
        return "法规类断言，非皮肤功效"
    if canonical == "防腐":
        return "防腐功效族断言，非皮肤功效"
    if a.evidence.type == EvidenceType.SUPPLIER:
        return "原料商宣称（未经同行评议），不计入功效指纹"
    return None


def compute_fingerprint(session: Session, product_id: int) -> dict:
    """计算产品的功效指纹。

    返回 {
      fingerprint: {规范功效族: round(score, 4)},   # 仅非零维度，按得分降序
      coverage: {"ingredients_total": int, "ingredients_with_assertion": int,
                 "inferred_dose": int, "unknown_dose": int,  # 成分级剂量覆盖，
                 # inferred_dose + unknown_dose == ingredients_total
                 "excluded_count": int},  # 被 purity 规则排除的断言条数
      detail: [{ingredient_id, inci_name, efficacy, efficacy_canonical,
                dose_factor, dose_basis, evidence_strength, contribution,
                excluded, exclude_reason?}]  # 逐断言贡献明细（含被 max 丢弃的
                # 与被排除的；efficacy 为原文，excluded 仅被排除条目带 reason）
    }
    evidence_strength 为 NULL（未评级）的断言 contribution 按 0 计，不进指纹维度，
    但仍在 detail 中如实列出；被排除条目的 contribution 照常计算展示，但不进维度。
    """
    links = (
        session.query(ProductIngredient)
        .filter_by(product_id=product_id)
        .order_by(ProductIngredient.id)
        .all()
    )
    scores: dict[str, float] = {}
    detail: list[dict] = []
    with_assertion = 0
    inferred = 0
    excluded_count = 0
    for link in links:
        if link.conc_low is not None:
            inferred += 1
        ing = link.ingredient
        assertions = (
            session.query(EfficacyAssertion)
            .filter_by(ingredient_id=ing.id)
            .order_by(EfficacyAssertion.id)
            .all()
        )
        if assertions:
            with_assertion += 1
        best: dict[str, float] = {}  # 同成分同功效族取 max contribution
        for a in assertions:
            factor, basis = dose_factor(
                conc_low=link.conc_low, conc_high=link.conc_high,
                eff_low=a.effective_conc_low, is_trace=link.is_trace,
            )
            contribution = round(factor * (a.evidence_strength or 0.0), 4)
            canonical = a.efficacy_canonical or canonicalize(a.efficacy)
            reason = _exclude_reason(a, canonical)
            entry = {
                "ingredient_id": ing.id,
                "inci_name": ing.inci_name,
                "efficacy": a.efficacy,
                "efficacy_canonical": canonical,
                "dose_factor": round(factor, 4),
                "dose_basis": basis,
                "evidence_strength": a.evidence_strength,
                "contribution": contribution,
                "excluded": reason is not None,
            }
            if reason is not None:
                entry["exclude_reason"] = reason
                excluded_count += 1
            detail.append(entry)
            if reason is None and contribution > best.get(canonical, 0.0):
                best[canonical] = contribution
        for canonical, contrib in best.items():
            scores[canonical] = scores.get(canonical, 0.0) + contrib
    fingerprint = {
        canonical: round(score, 4)
        for canonical, score in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        if score > 0
    }
    return {
        "fingerprint": fingerprint,
        "coverage": {
            "ingredients_total": len(links),
            "ingredients_with_assertion": with_assertion,
            "inferred_dose": inferred,
            "unknown_dose": len(links) - inferred,
            "excluded_count": excluded_count,
        },
        "detail": detail,
    }
