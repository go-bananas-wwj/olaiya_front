"""市场快照 API：GET /api/products/{id}/market 最新快照 + 历史点 + 404/空态。"""

import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_db
from app.models.product import MarketSnapshot, Product


@pytest.fixture()
def client(session):
    p = Product(name="测试精华", brand="测试品牌")
    session.add(p)
    session.flush()
    session.add_all([
        MarketSnapshot(product_id=p.id, date=datetime.date(2026, 3, 1),
                       source="smzdm/京东", price=109.0, value_ratio=None,
                       comment_count=None, estimate_note="页面 https://www.smzdm.com/p/100/"),
        MarketSnapshot(product_id=p.id, date=datetime.date(2026, 7, 5),
                       source="smzdm/京东", price=99.0, value_ratio=83.0,
                       comment_count=None, estimate_note="页面 https://www.smzdm.com/p/111/"),
    ])
    empty = Product(name="无快照产品", brand="测试品牌")
    session.add(empty)
    session.commit()
    session.expire_all()
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as c:
            yield c, p.id, empty.id
    finally:
        app.dependency_overrides.clear()


def test_market_latest_and_history(client):
    c, pid, _ = client
    r = c.get(f"/api/products/{pid}/market")
    assert r.status_code == 200
    body = r.json()
    assert body["latest"]["date"] == "2026-07-05"
    assert body["latest"]["price"] == 99.0
    assert body["latest"]["value_ratio"] == 83.0
    assert body["latest"]["source"] == "smzdm/京东"
    assert len(body["history"]) == 1
    assert body["history"][0]["date"] == "2026-03-01"
    assert "值率" in body["note"]


def test_market_empty_state(client):
    c, _, empty_id = client
    body = c.get(f"/api/products/{empty_id}/market").json()
    assert body["latest"] is None
    assert body["history"] == []


def test_market_404(client):
    c, _, _ = client
    r = c.get("/api/products/999999/market")
    assert r.status_code == 404
