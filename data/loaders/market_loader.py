"""口碑/好价快照加载器：smzdm 采集 JSON → market_snapshots 时间序列 + 最新好价 PricePoint。

输入为 data/raw/smzdm/{product_id}.json（git 忽略，采集器产出，结构见下），
只入库 match_confidence="high" 的页面；low（规格/色号对不上、套装配角等存疑件）
一律不猜，计入 skipped_low 报告。product_id 在库中不存在时跳过（外键安全），
计入 unmatched_products。

每个 high 页面落一行 MarketSnapshot（source="smzdm/{渠道}"，estimate_note 含页面
URL/标题/日期推断说明/值投票票数）；每产品取日期最新的 high 且有价格的页面落一条
PricePoint（source 注明 smzdm 与渠道、is_manual=False）。幂等：同产品同日期同来源
同 URL 的快照/价格点重复执行更新而非重复插入。

页面 JSON 结构（采集器/研究产出）：
{"product_id": 84, "query": "...",
 "pages": [{"url": "https://www.smzdm.com/p/.../", "title": "...",
            "price": 107.1, "price_original": null, "channel": "京东",
            "value_ratio": 83, "votes_up": 10, "votes_down": 2,
            "date": "2026-07-05", "year_inferred": false, "expired": true,
            "comment_count": null, "match_confidence": "high",
            "match_reason": "...", "snippet": "..."}]}

CLI：仓库根目录执行  PYTHONPATH=backend .venv/bin/python -m data.loaders.market_loader
"""

import datetime
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models.product import MarketSnapshot, PricePoint, Product

RAW_DIR = Path(__file__).resolve().parents[1] / "raw" / "smzdm"


def _snapshot_note(page: dict) -> str:
    """快照备注：页面 URL + 标题 + 估计语义（日期推断/过期）+ 值投票票数。"""
    parts = [f"页面 {page['url']}", f"标题「{page.get('title', '')[:80]}」"]
    if page.get("year_inferred"):
        parts.append("日期仅月日，年份按采集日推断（估计）")
    if page.get("expired"):
        parts.append("好价已过期（促销价有时效）")
    up, down = page.get("votes_up"), page.get("votes_down")
    if up is not None and down is not None:
        parts.append(f"值投票 {up}:{down}")
    if page.get("match_reason"):
        parts.append(f"匹配：{page['match_reason'][:80]}")
    return "；".join(parts)


def _point_source(page: dict) -> str:
    """PricePoint.source：注明 smzdm 与渠道 + 页面 URL（200 字符截断）。"""
    return f"smzdm/{page.get('channel') or '未知渠道'} {page['url']}"[:200]


def _find_snapshot(session: Session, product_id: int, date: datetime.date,
                   source: str, url: str) -> MarketSnapshot | None:
    """幂等查找：同产品同日期同来源且 estimate_note 含同 URL 的快照。"""
    return (
        session.query(MarketSnapshot)
        .filter_by(product_id=product_id, date=date, source=source)
        .filter(MarketSnapshot.estimate_note.contains(url))
        .one_or_none()
    )


def load_market(session: Session, raw_dir: Path = RAW_DIR) -> dict:
    """smzdm 采集 JSON 入库，返回统计。幂等：同日同源同 URL 更新不重复。"""
    stats = {
        "files": 0, "products_matched": 0, "unmatched_products": [],
        "snapshots_added": 0, "snapshots_updated": 0,
        "points_added": 0, "points_updated": 0, "skipped_low": [],
    }
    files = sorted(Path(raw_dir).glob("*.json")) if Path(raw_dir).is_dir() else []
    stats["files"] = len(files)
    for f in files:
        rec = json.loads(f.read_text(encoding="utf-8"))
        product_id = rec.get("product_id")
        product = session.get(Product, product_id) if product_id else None
        if product is None:
            stats["unmatched_products"].append(product_id)
            continue
        stats["products_matched"] += 1
        latest_priced: tuple[datetime.date, dict] | None = None
        for page in rec.get("pages", []):
            if page.get("match_confidence") != "high":  # 存疑件不猜，记入报告
                stats["skipped_low"].append(
                    {"product_id": product_id, "url": page.get("url"),
                     "reason": page.get("match_reason")})
                continue
            try:
                date = datetime.date.fromisoformat(page["date"])
            except (KeyError, TypeError, ValueError):
                stats["skipped_low"].append(
                    {"product_id": product_id, "url": page.get("url"),
                     "reason": "日期缺失或非法"})
                continue
            source = f"smzdm/{page.get('channel') or '未知渠道'}"
            snap = _find_snapshot(session, product.id, date, source, page["url"])
            if snap is None:
                session.add(MarketSnapshot(
                    product_id=product.id, date=date, source=source,
                    price=page.get("price"), value_ratio=page.get("value_ratio"),
                    comment_count=page.get("comment_count"),
                    estimate_note=_snapshot_note(page)))
                stats["snapshots_added"] += 1
            else:
                snap.price = page.get("price")
                snap.value_ratio = page.get("value_ratio")
                snap.comment_count = page.get("comment_count")
                snap.estimate_note = _snapshot_note(page)
                stats["snapshots_updated"] += 1
            if page.get("price") is not None and (
                    latest_priced is None or date > latest_priced[0]):
                latest_priced = (date, page)
        if latest_priced is not None:  # 最新好价 → PricePoint（不进 price_current）
            date, page = latest_priced
            source = _point_source(page)
            point = (
                session.query(PricePoint)
                .filter_by(product_id=product.id, date=date, source=source)
                .one_or_none())
            if point is None:
                session.add(PricePoint(product_id=product.id, date=date,
                                       price=page["price"], source=source,
                                       is_manual=False))
                stats["points_added"] += 1
            else:
                point.price = page["price"]
                point.is_manual = False
                stats["points_updated"] += 1
    return stats


def main() -> None:
    init_db()
    with SessionLocal() as s:
        stats = load_market(s)
        s.commit()
        print(f"files={stats['files']} products={stats['products_matched']} "
              f"snapshots +{stats['snapshots_added']} ~{stats['snapshots_updated']} "
              f"points +{stats['points_added']} ~{stats['points_updated']}")
        for pid in stats["unmatched_products"]:
            print(f"  库中无此 product_id：{pid}")
        for sk in stats["skipped_low"]:
            print(f"  存疑跳过：{sk['product_id']} {sk['url']}（{sk['reason']}）")


if __name__ == "__main__":
    main()
