"""成分功效证据指数 v1：来源可追溯、同成分同方向取最大权重，浓度独立展示。

这是已收录资料的参考指数，不是成品实测功效、有效率或剂量加权指纹。
既有 fingerprint / 排行榜的计算口径保持独立。
"""
from __future__ import annotations

from decimal import Decimal
import math

from sqlalchemy.orm import Session, joinedload

from ..models.evidence import EvidenceType
from ..models.ingredient import EfficacyAssertion
from ..models.product import ProductIngredient
from .dosecheck import verdict_for
from .efficacy_canon import canonicalize
from .evidence_level import EVIDENCE_LEVELS, ORAL, UNKNOWN, classify_evidence_level
from .fingerprint import _exclude_reason

METHOD_VERSION = "evidence-index-v1"
DIRECTIONS = ("保湿", "抗皱", "修护", "舒缓", "抗氧化", "美白", "控油祛痘", "焕肤")
INDEX_NOTE = "指数汇总已收录的成分证据，受资料覆盖影响，不是成品实测效果。"


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def _concentration(link: ProductIngredient, assertion: EfficacyAssertion) -> tuple[dict, dict]:
    disclosed = link.disclosed_conc
    estimated = (link.position is not None and link.position > 0 and
                 _finite(link.conc_low) and _finite(link.conc_high) and
                 0 <= link.conc_low <= link.conc_high <= 100)
    if _finite(disclosed) and 0 <= disclosed <= 100:
        concentration = {"status": "disclosed", "low": disclosed, "high": disclosed,
                         "label": "有来源披露的浓度", "estimated": False}
    elif estimated:
        concentration = {"status": "estimated", "low": link.conc_low, "high": link.conc_high,
                         "label": "有可用的浓度估计（非实测）", "estimated": True}
    else:
        concentration = {"status": "unknown", "low": None, "high": None,
                         "label": "产品浓度无法判断", "estimated": False}
    research_known = _finite(assertion.effective_conc_low) and assertion.effective_conc_low > 0
    product_known = concentration["status"] != "unknown"
    dose = {
        "research_low": assertion.effective_conc_low if _finite(assertion.effective_conc_low) else None,
        "research_high": assertion.effective_conc_high if _finite(assertion.effective_conc_high) else None,
        "research_available": research_known,
        "assessable": research_known and product_known,
        "verdict": "unknown",
        "note": "研究浓度缺失" if not research_known else ("产品浓度无法判断" if not product_known else "仅对照本条研究条件，非成品功效验证"),
    }
    if dose["assessable"]:
        dose["verdict"] = verdict_for(concentration["low"], concentration["high"],
                                     assertion.effective_conc_low, assertion.effective_conc_high,
                                     is_trace=link.is_trace)
    return concentration, dose


def _reason(assertion: EfficacyAssertion, canonical: str) -> str | None:
    reason = _exclude_reason(assertion, canonical)
    if reason:
        return reason
    if assertion.efficacy.startswith(("安全评估", "功能分类", "法定限用", "法规", "配方典型用量", "配方实践")):
        return "功能分类、安全或配方参考资料，非功效实证"
    if assertion.evidence.type not in (EvidenceType.PAPER, EvidenceType.BOOK):
        return "该资料通道不计入主指数"
    if assertion.evidence_level == ORAL or classify_evidence_level(assertion.note, assertion.evidence) == ORAL:
        return "口服研究，不能用于外用产品指数"
    if canonical not in DIRECTIONS:
        return "不属于本次八个功效方向"
    if assertion.evidence.type == EvidenceType.PAPER and (
        assertion.evidence_level not in EVIDENCE_LEVELS or assertion.evidence_level == UNKNOWN
    ):
        return "论文未明确评级"
    weight = assertion.evidence_strength
    if not _finite(weight) or not 0 <= weight <= 1:
        return "证据强度未明确或不在有效范围"
    if assertion.evidence.type == EvidenceType.BOOK and weight > 0.3:
        return "工具书强度超过既有低强度上限"
    return None


def capability_profile(session: Session, product_id: int) -> dict:
    # Two batched queries; no ingredient/evidence lookups inside the aggregation loop.
    links = session.query(ProductIngredient).options(joinedload(ProductIngredient.ingredient)).filter_by(
        product_id=product_id).order_by(ProductIngredient.id).all()
    by_id = {link.ingredient_id: link for link in links}
    assertions = session.query(EfficacyAssertion).options(joinedload(EfficacyAssertion.evidence)).filter(
        EfficacyAssertion.ingredient_id.in_(by_id)).order_by(EfficacyAssertion.id).all() if by_id else []
    best: dict[tuple[int, str], dict] = {}
    excluded = []
    unrated = {family: 0 for family in DIRECTIONS}
    for assertion in assertions:
        link = by_id[assertion.ingredient_id]
        ing, ev = link.ingredient, assertion.evidence
        canonical = assertion.efficacy_canonical or canonicalize(assertion.efficacy)
        concentration, dose = _concentration(link, assertion)
        item = {
            "ingredient_id": ing.id, "cn_name": ing.cn_name, "inci_name": ing.inci_name,
            "assertion_id": assertion.id, "efficacy": assertion.efficacy, "canonical": canonical,
            "weight": assertion.evidence_strength if _finite(assertion.evidence_strength) else None, "evidence_level": assertion.evidence_level or UNKNOWN,
            "reference_only": ev.type == EvidenceType.BOOK, "note": assertion.note,
            "concentration": concentration, "dose": dose,
            "evidence": {"id": ev.id, "type": ev.type.value, "title": ev.title, "source": ev.source,
                         "url": ev.url, "year": ev.year, "excerpt": ev.excerpt},
        }
        reason = _reason(assertion, canonical)
        if reason:
            if canonical in unrated and reason in ("论文未明确评级", "证据强度未明确或不在有效范围"):
                unrated[canonical] += 1
            excluded.append({**item, "reason": reason})
            continue
        key = (ing.id, canonical)
        previous = best.get(key)
        if previous is None or item["weight"] > previous["weight"]:
            if previous is not None:
                excluded.append({**previous, "reason": "同成分同方向只计最高合格权重"})
            best[key] = item
        else:
            excluded.append({**item, "reason": "同成分同方向只计最高合格权重"})
    dimensions = []
    for canonical in DIRECTIONS:
        contributions = sorted((item for (iid, family), item in best.items() if family == canonical),
                               key=lambda item: (-item["weight"], item["ingredient_id"]))
        dimensions.append({
            "canonical": canonical,
            "status": "scored" if contributions else ("unrated" if unrated[canonical] else "no_evidence"),
            "score": float(round(sum((Decimal(str(c["weight"])) for c in contributions), Decimal(0)), 4)) if contributions else None,
            "ingredient_count": len(contributions),
            "source_count": len({c["evidence"]["id"] for c in contributions}),
            "unrated_count": unrated[canonical],
            "dose_coverage": {"assessable": sum(c["dose"]["assessable"] for c in contributions), "total": len(contributions)},
            "contributions": contributions,
        })
    return {
        "product_id": product_id, "method_version": METHOD_VERSION, "note": INDEX_NOTE,
        # Full excerpts remain available via ingredient detail; avoid repeating long excerpts
        # hundreds of times in the excluded-record list sent on the first screen.
        "dimensions": dimensions, "excluded": [{**item, "evidence": {k: v for k, v in item["evidence"].items() if k != "excerpt"}} for item in excluded],
        "coverage": {"ingredients_total": len(by_id), "ingredients_scored": len({iid for iid, _ in best}),
                     "sources_scored": len({item["evidence"]["id"] for item in best.values()}), "excluded_assertions": len(excluded)},
    }
