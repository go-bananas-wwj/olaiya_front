"""证据充分度面板（借鉴 EWG「数据充分度」独立维度）：一个产品的功效断言按证据层级分布。

把「不知道」做成一等公民：unknown 计数如实展示不隐藏；全部 9 个层级键都返回
（含 0 计数），按证据强度默认分降序排列，前端可直接渲染分布条与分级徽章。
evidence_level 为 NULL 的断言按 unknown 计（与铁律「拿不准落 unknown」同口径）。
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models.ingredient import EfficacyAssertion
from ..models.product import ProductIngredient
from .evidence_level import DEFAULT_EVIDENCE_STRENGTH, EVIDENCE_LEVELS, UNKNOWN

LEVEL_LABELS = {
    "human_rct": "人体随机对照试验",
    "human_ct": "人体试验",
    "human_open": "开放人体试验",
    "in_vitro": "体外实验",
    "animal": "动物实验",
    "oral": "口服研究",
    "review": "综述",
    "regulation": "法规/官方文件",
    "unknown": "证据不足",
}

# 展示顺序：证据强度默认分降序（最强的排最前，unknown 垫底）
_LEVEL_ORDER = sorted(EVIDENCE_LEVELS, key=lambda lv: -DEFAULT_EVIDENCE_STRENGTH[lv])


def evidence_profile(session: Session, product_id: int) -> dict:
    """返回 {assertions_total, ingredients_total, ingredients_with_assertions, by_level}。

    by_level: [{level, label, count, ratio}]，ratio = count / assertions_total
    （round 4，无断言时为 0）。
    """
    links = session.query(ProductIngredient).filter_by(product_id=product_id).all()
    ing_ids = [lnk.ingredient_id for lnk in links]
    counts = {lv: 0 for lv in EVIDENCE_LEVELS}
    with_assertions: set[int] = set()
    if ing_ids:
        rows = (
            session.query(EfficacyAssertion.ingredient_id,
                          EfficacyAssertion.evidence_level, func.count())
            .filter(EfficacyAssertion.ingredient_id.in_(ing_ids))
            .group_by(EfficacyAssertion.ingredient_id, EfficacyAssertion.evidence_level)
            .all()
        )
        for iid, level, cnt in rows:
            counts[level if level in counts else UNKNOWN] += cnt  # NULL/枚举外值同铁律口径落 unknown
            with_assertions.add(iid)
    total = sum(counts.values())
    by_level = [
        {"level": lv, "label": LEVEL_LABELS[lv], "count": counts[lv],
         "ratio": round(counts[lv] / total, 4) if total else 0}
        for lv in _LEVEL_ORDER
    ]
    return {
        "assertions_total": total,
        "ingredients_total": len(ing_ids),
        "ingredients_with_assertions": len(with_assertions),
        "by_level": by_level,
    }
