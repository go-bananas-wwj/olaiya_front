"""相似候选的价格与成分差异展示数据；不改变检索分数或原有成本折算。"""

import math
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.ingredient import Ingredient
from ..models.product import PricePoint, Product, ProductIngredient

_SPEC = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ml|g|毫升|克)\s*$", re.I)


def price_fields(product: Product, point: PricePoint | None = None) -> dict:
    """单一规格才算单位价；质量和体积不互换，记录日期不冒充采样日期。"""
    unit_price = unit = None
    match = _SPEC.fullmatch(product.spec or "")
    price = product.price_current
    if match and price is not None and math.isfinite(price) and price >= 0:
        quantity = float(match[1])
        if math.isfinite(quantity) and quantity > 0:
            unit = "ml" if match[2].lower() in ("ml", "毫升") else "g"
            unit_price = round(price / quantity, 6)
    return {
        "price_current": price, "spec": product.spec,
        "source_url": product.source_url, "buy_url": product.buy_url,
        "price_source": point.source if point else None,
        "price_recorded_at": point.date.isoformat() if point else None,
        "unit_price": unit_price, "unit_price_unit": unit,
    }


def matching_price_points(session: Session, ids: list[int]) -> dict[int, PricePoint]:
    if not ids:
        return {}
    points = session.execute(
        select(PricePoint).join(Product, Product.id == PricePoint.product_id)
        .where(Product.id.in_(ids), PricePoint.price == Product.price_current)
        .order_by(PricePoint.date.desc(), PricePoint.id.desc())
    ).scalars()
    latest = {}
    for point in points:
        latest.setdefault(point.product_id, point)
    return latest


def enrich_candidates(session: Session, target_id: int, items: list[dict]) -> list[dict]:
    """批量补充候选，固定三条 SQL；共享集合按真实成分 id 比对，无顺序/浓度推测。"""
    if not items:
        return []
    ids = list({item["id"] for item in items})
    products = {p.id: p for p in session.execute(
        select(Product).where(Product.id.in_(ids))).scalars()}
    points = matching_price_points(session, ids)
    formulas: dict[int, set[int]] = {}
    names = {}
    for pid, iid, cn, inci in session.execute(
        select(ProductIngredient.product_id, Ingredient.id, Ingredient.cn_name, Ingredient.inci_name)
        .join(Ingredient, Ingredient.id == ProductIngredient.ingredient_id)
        .where(ProductIngredient.product_id.in_([target_id, *ids]))
    ):
        formulas.setdefault(pid, set()).add(iid)
        names[iid] = {"ingredient_id": iid, "cn_name": cn, "inci_name": inci}
    target = formulas.get(target_id, set())

    def ingredients(group):
        return [names[iid] for iid in sorted(group)]

    enriched = []
    for item in items:
        pid = item["id"]
        if pid not in products:  # 索引中已删除的产品跳过
            continue
        candidate = formulas.get(pid, set())
        enriched.append({
            **item, "name": products[pid].name, "brand": products[pid].brand,
            **price_fields(products[pid], points.get(pid)),
            "shared": len(target & candidate), "union": len(target | candidate),
            "shared_ingredients": ingredients(target & candidate),
            "only_target_ingredients": ingredients(target - candidate),
            "only_candidate_ingredients": ingredients(candidate - target),
        })
    return enriched
