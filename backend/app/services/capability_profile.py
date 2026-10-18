"""成分功效证据指数 v1：来源可追溯、同成分同方向取最大权重，浓度独立展示。

这是已收录资料的参考指数，不是成品实测功效、有效率或剂量加权指纹。
既有 fingerprint / 排行榜的计算口径保持独立。
"""
from __future__ import annotations

from decimal import Decimal
from collections import Counter
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


def select_index_assertions(assertions):
    """Shared qualification/max-contribution rule for details and whole-catalog views.

    Input order is assertion ID ascending; a tie retains the earlier assertion.
    No concentration or missing-value imputation enters this index.
    """
    best, excluded, unrated = {}, [], Counter()
    for assertion in assertions:
        canonical = assertion.efficacy_canonical or canonicalize(assertion.efficacy)
        reason = _reason(assertion, canonical)
        if reason:
            if canonical in DIRECTIONS and reason in ("论文未明确评级", "证据强度未明确或不在有效范围"):
                unrated[(assertion.ingredient_id, canonical)] += 1
            excluded.append((assertion, canonical, reason))
            continue
        key = (assertion.ingredient_id, canonical)
        previous = best.get(key)
        if previous is None or assertion.evidence_strength > previous.evidence_strength:
            if previous is not None:
                excluded.append((previous, canonical, "同成分同方向只计最高合格权重"))
            best[key] = assertion
        else:
            excluded.append((assertion, canonical, "同成分同方向只计最高合格权重"))
    return best, excluded, unrated


def index_sum(weights):
    return float(round(sum((Decimal(str(weight)) for weight in weights), Decimal(0)), 4))


def capability_profile(session: Session, product_id: int) -> dict:
    # Two batched queries; no ingredient/evidence lookups inside the aggregation loop.
    links = session.query(ProductIngredient).options(joinedload(ProductIngredient.ingredient)).filter_by(
        product_id=product_id).order_by(ProductIngredient.id).all()
    by_id = {link.ingredient_id: link for link in links}
    assertions = session.query(EfficacyAssertion).options(joinedload(EfficacyAssertion.evidence)).filter(
        EfficacyAssertion.ingredient_id.in_(by_id)).order_by(EfficacyAssertion.id).all() if by_id else []
    selected, rejected, unrated_by_ingredient = select_index_assertions(assertions)
    unrated = {family: sum(unrated_by_ingredient[(iid, family)] for iid in by_id) for family in DIRECTIONS}

    def item_for(assertion, canonical):
        link = by_id[assertion.ingredient_id]
        ing, ev = link.ingredient, assertion.evidence
        concentration, dose = _concentration(link, assertion)
        return {
            "ingredient_id": ing.id, "cn_name": ing.cn_name, "inci_name": ing.inci_name,
            "assertion_id": assertion.id, "efficacy": assertion.efficacy, "canonical": canonical,
            "weight": assertion.evidence_strength if _finite(assertion.evidence_strength) else None, "evidence_level": assertion.evidence_level or UNKNOWN,
            "reference_only": ev.type == EvidenceType.BOOK, "note": assertion.note,
            "concentration": concentration, "dose": dose,
            "evidence": {"id": ev.id, "type": ev.type.value, "title": ev.title, "source": ev.source,
                         "url": ev.url, "year": ev.year, "excerpt": ev.excerpt},
        }
    best = {key: item_for(assertion, key[1]) for key, assertion in selected.items()}
    excluded = [{**item_for(assertion, canonical), "reason": reason} for assertion, canonical, reason in rejected]
    dimensions = []
    for canonical in DIRECTIONS:
        contributions = sorted((item for (iid, family), item in best.items() if family == canonical),
                               key=lambda item: (-item["weight"], item["ingredient_id"]))
        dimensions.append({
            "canonical": canonical,
            "status": "scored" if contributions else ("unrated" if unrated[canonical] else "no_evidence"),
            "score": index_sum(c["weight"] for c in contributions) if contributions else None,
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
