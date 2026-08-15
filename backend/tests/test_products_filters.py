"""产品列表新参数：efficacy 功效胶囊筛选 / sort 排序 / q 并入备案号匹配（v2.2 方案 P0）。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_db
from app.models.product import Product, ProductClaim


@pytest.fixture()
def client(session):
    p1 = Product(name="甲 美白精华", brand="甲牌", nmpa_id="浙G妆网备字2026000001")
    p2 = Product(name="乙 保湿面霜", brand="乙牌", nmpa_id="沪G妆网备字2026000002")
    p3 = Product(name="丙 无宣称乳", brand="丙牌", nmpa_id=None)
    session.add_all([p1, p2, p3])
    session.flush()
    session.add_all([
        ProductClaim(product_id=p1.id, claim="美白提亮"),
        ProductClaim(product_id=p1.id, claim="保湿"),
        ProductClaim(product_id=p2.id, claim="保湿"),
    ])
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def test_efficacy_filter_hit(client):
    r = client.get("/api/products", params={"efficacy": "美白"}).json()
    assert [p["name"] for p in r] == ["甲 美白精华"]


def test_efficacy_filter_keyword_or(client):
    # 「美白」枚举映射多词 OR：claim「美白提亮」命中；「保湿」枚举不命中它
    r = client.get("/api/products", params={"efficacy": "保湿"}).json()
    names = sorted(p["name"] for p in r)
    assert names == ["乙 保湿面霜", "甲 美白精华"]


def test_efficacy_unknown_422(client):
    assert client.get("/api/products", params={"efficacy": "丰胸"}).status_code == 422


def test_sort_claim_count_desc(client):
    r = client.get("/api/products", params={"sort": "claim_count_desc"}).json()
    assert [p["name"] for p in r][:2] == ["甲 美白精华", "乙 保湿面霜"]


def test_sort_unknown_422(client):
    assert client.get("/api/products", params={"sort": "price"}).status_code == 422


def test_q_matches_nmpa_id(client):
    r = client.get("/api/products", params={"q": "2026000002"}).json()
    assert [p["name"] for p in r] == ["乙 保湿面霜"]


def test_no_params_backward_compatible(client):
    r = client.get("/api/products").json()
    assert isinstance(r, list) and len(r) == 3
