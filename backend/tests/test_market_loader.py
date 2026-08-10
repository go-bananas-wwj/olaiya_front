"""口碑/好价快照加载器：high 才入库、low/坏日期跳过、幂等、最新好价落 PricePoint。"""

import datetime
import json

import pytest

from app.models.product import MarketSnapshot, PricePoint, Product
from data.loaders.market_loader import load_market


def _write_raw(tmp_path, product_id, pages):
    raw = tmp_path / f"{product_id}.json"
    raw.write_text(json.dumps(
        {"product_id": product_id, "query": "测试", "pages": pages},
        ensure_ascii=False), encoding="utf-8")
    return raw


PAGE_HIGH = {
    "url": "https://www.smzdm.com/p/111/", "title": "测试精华 30ml 99元",
    "price": 99.0, "price_original": 129.0, "channel": "京东",
    "value_ratio": 83.0, "votes_up": 10, "votes_down": 2,
    "date": "2026-07-05", "year_inferred": False, "expired": True,
    "comment_count": None, "match_confidence": "high",
    "match_reason": "标题即该产品", "snippet": "过期99元 | 83%的值友认为值 10:2",
}
PAGE_OLD = {**PAGE_HIGH, "url": "https://www.smzdm.com/p/100/",
            "price": 109.0, "date": "2026-03-01", "value_ratio": None,
            "votes_up": None, "votes_down": None, "expired": True}
PAGE_LOW = {**PAGE_HIGH, "url": "https://www.smzdm.com/p/222/",
            "match_confidence": "low", "match_reason": "15ml 体验装非正装"}


@pytest.fixture()
def product(session):
    p = Product(name="测试精华", brand="测试品牌")
    session.add(p)
    session.commit()
    return p


def test_high_pages_become_snapshots_and_latest_point(session, tmp_path, product):
    _write_raw(tmp_path, product.id, [PAGE_HIGH, PAGE_OLD, PAGE_LOW])
    stats = load_market(session, raw_dir=tmp_path)
    session.commit()
    snaps = (session.query(MarketSnapshot)
             .filter_by(product_id=product.id)
             .order_by(MarketSnapshot.date).all())
    assert len(snaps) == 2  # low 置信页不入库
    assert snaps[0].date == datetime.date(2026, 3, 1)
    assert snaps[1].value_ratio == 83.0
    assert snaps[1].source == "smzdm/京东"
    assert "https://www.smzdm.com/p/111/" in snaps[1].estimate_note
    assert "值投票 10:2" in snaps[1].estimate_note
    assert "过期" in snaps[1].estimate_note
    # 最新好价（07-05，99 元）落 PricePoint，非人工采样
    points = session.query(PricePoint).filter_by(product_id=product.id).all()
    assert len(points) == 1
    assert points[0].price == 99.0
    assert points[0].date == datetime.date(2026, 7, 5)
    assert points[0].is_manual is False
    assert points[0].source.startswith("smzdm/京东")
    assert stats["snapshots_added"] == 2 and stats["points_added"] == 1
    assert len(stats["skipped_low"]) == 1
    assert stats["skipped_low"][0]["reason"] == "15ml 体验装非正装"


def test_idempotent_second_run(session, tmp_path, product):
    _write_raw(tmp_path, product.id, [PAGE_HIGH])
    load_market(session, raw_dir=tmp_path)
    session.commit()
    stats = load_market(session, raw_dir=tmp_path)
    session.commit()
    assert session.query(MarketSnapshot).count() == 1
    assert session.query(PricePoint).count() == 1
    assert stats["snapshots_added"] == 0 and stats["snapshots_updated"] == 1
    assert stats["points_added"] == 0 and stats["points_updated"] == 1


def test_unknown_product_and_bad_date_skipped(session, tmp_path, product):
    _write_raw(tmp_path, 999999, [PAGE_HIGH])  # 库中无此产品
    bad_date = {**PAGE_HIGH, "url": "https://www.smzdm.com/p/333/", "date": "07-05"}
    _write_raw(tmp_path, product.id, [bad_date])
    stats = load_market(session, raw_dir=tmp_path)
    session.commit()
    assert stats["unmatched_products"] == [999999]
    assert session.query(MarketSnapshot).count() == 0  # 非法日期不入库
    assert session.query(PricePoint).count() == 0


def test_year_inferred_marked_in_note(session, tmp_path, product):
    inferred = {**PAGE_HIGH, "url": "https://www.smzdm.com/p/444/",
                "date": "2026-05-01", "year_inferred": True}
    _write_raw(tmp_path, product.id, [inferred])
    load_market(session, raw_dir=tmp_path)
    session.commit()
    snap = session.query(MarketSnapshot).one()
    assert "年份按采集日推断（估计）" in snap.estimate_note
