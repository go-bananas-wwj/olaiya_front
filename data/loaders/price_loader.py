"""价格规格加载器（每起效成本数据底座）：手工采样的官方零售价 + 主规格入库。

产品定位双通道：item 有 product_id 走精确通道（校验 brand，防去重合并/重命名
造成的 match 串漂移错挂；product_id 在库中不存在时——如异库/测试库种子——回退
match 模糊通道）；否则 match 串对产品名做子串模糊匹配，同名多条时按
「有序产品（有位次关联）优先 + brand 匹配」消歧（如理肤泉 B5：有序「B5多效修复霜
（Cicaplast Baume B5）」胜出，无序「理肤泉新B5多效修复霜」不误写）。无法唯一
消歧时不猜写，计入 unmatched。写入 product.price_current / product.spec，并落
一条 PricePoint（date=今天、source=source_url、is_manual=True）；同日同源重复
执行更新价格而非重复插点（幂等）。item 可选 buy_url（官方购买页，如品牌官网
产品页），有则回填 product.buy_url；products.buy_url 列对既有库的补列迁移由
app.db.ensure_additive_columns（init_db 调用链）完成。

CLI：仓库根目录执行  PYTHONPATH=backend .venv/bin/python -m data.loaders.price_loader
"""

import datetime
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models.product import PricePoint, Product, ProductIngredient

PRICE_PATH = Path(__file__).resolve().parents[1] / "seed" / "price_specs.json"


def _like_escape(s: str) -> str:
    """LIKE 字面量转义：match 串含 %（如「烟酰胺10%+锌1%」）时按字面匹配。"""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _has_position(session: Session, product_id: int) -> bool:
    """是否有序产品：存在 position 非空的成分关联（官方降序成分表）。"""
    return (
        session.query(ProductIngredient.id)
        .filter(
            ProductIngredient.product_id == product_id,
            ProductIngredient.position.isnot(None),
        )
        .first()
    ) is not None


def _brand_matches(product_brand: str | None, item_brand: str | None) -> bool:
    """品牌宽松匹配：相等或互为子串（如库内「理肤泉」对采样「理肤泉 La Roche-Posay」）。"""
    if not product_brand or not item_brand:
        return False
    pb, ib = product_brand.strip(), item_brand.strip()
    return pb == ib or pb in ib or ib in pb


def _find_product(session: Session, match: str, brand: str) -> Product | None:
    """match 子串匹配产品名；多条候选先取有序产品，再按 brand 消歧；唯一才返回。"""
    candidates = (
        session.query(Product)
        .filter(Product.name.like(f"%{_like_escape(match)}%", escape="\\"))
        .all()
    )
    if not candidates:
        return None
    if len(candidates) > 1:
        ordered = [p for p in candidates if _has_position(session, p.id)]
        if ordered:  # 有序产品优先；无有序候选则保留全集走 brand 消歧
            candidates = ordered
    if len(candidates) > 1:
        by_brand = [p for p in candidates if _brand_matches(p.brand, brand)]
        if by_brand:
            candidates = by_brand
    return candidates[0] if len(candidates) == 1 else None


def _resolve_product(session: Session, item: dict) -> Product | None:
    """item 定位产品：有 product_id 走精确通道（去重合并/重命名后不受 match 串漂移
    影响，id 出自规则匹配报告，入库时校验 brand 防错挂）；product_id 在库中不存在时
    （如异库/测试库种子）回退 match 子串模糊匹配；否则直接走模糊匹配。"""
    pid = item.get("product_id")
    if pid is not None:
        product = session.get(Product, pid)
        if product is not None:
            brand = item.get("brand")
            if brand and not _brand_matches(product.brand, brand):  # id 与品牌对不上 = 数据错误，不猜写
                return None
            return product
    return _find_product(session, item["match"], item.get("brand"))


def load_prices(session: Session, path: Path = PRICE_PATH) -> dict:
    """价格/规格入库，返回统计。幂等：同日同源 PricePoint 更新不重复。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    today = datetime.date.today()
    stats = {
        "items": len(data["items"]),
        "matched": 0,
        "unmatched": [],
        "price_points_added": 0,
        "price_points_updated": 0,
    }
    for item in data["items"]:
        product = _resolve_product(session, item)
        if product is None:
            stats["unmatched"].append(item["match"])
            continue
        product.price_current = item["price"]
        product.spec = item["spec"]
        if item.get("buy_url"):  # 官方购买页（可选字段，提供才写，幂等同值）
            product.buy_url = item["buy_url"]
        point = (
            session.query(PricePoint)
            .filter_by(product_id=product.id, date=today, source=item["source_url"])
            .one_or_none()
        )
        if point is None:
            session.add(PricePoint(
                product_id=product.id,
                date=today,
                price=item["price"],
                source=item["source_url"],
                is_manual=True,
            ))
            stats["price_points_added"] += 1
        else:
            point.price = item["price"]
            point.is_manual = True
            stats["price_points_updated"] += 1
        stats["matched"] += 1
    return stats


def main() -> None:
    init_db()
    with SessionLocal() as s:
        stats = load_prices(s)
        s.commit()
        print(f"items={stats['items']} matched={stats['matched']} "
              f"points_added={stats['price_points_added']} "
              f"points_updated={stats['price_points_updated']}")
        for m in stats["unmatched"]:
            print(f"  未匹配：{m}")


if __name__ == "__main__":
    main()
