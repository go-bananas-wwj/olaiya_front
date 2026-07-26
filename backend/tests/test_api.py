import pytest
from fastapi.testclient import TestClient

from app.main import app, get_db
from data.loaders.seed_loader import load_seed


@pytest.fixture()
def client(session):
    load_seed(session)
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def test_list_ingredients(client):
    r = client.get("/api/ingredients")
    assert r.status_code == 200
    names = {i["inci_name"] for i in r.json()}
    assert "NIACINAMIDE" in names


def test_search_by_cn_name(client):
    r = client.get("/api/ingredients", params={"q": "烟酰"})
    assert r.status_code == 200
    assert [i["cn_name"] for i in r.json()] == ["烟酰胺"]


def test_ingredient_detail_has_evidence_chain(client):
    items = client.get("/api/ingredients", params={"q": "烟酰胺"}).json()
    r = client.get(f"/api/ingredients/{items[0]['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["assertions"], "种子里的烟酰胺必须有功效断言"
    a = body["assertions"][0]
    assert a["evidence"]["type"] == "paper"
    assert a["evidence"]["url"].startswith("https://pubmed.ncbi.nlm.nih.gov/")
    assert a["effective_conc_low"] == 2.0


def test_ingredient_not_found(client):
    r = client.get("/api/ingredients/999999")
    assert r.status_code == 404
    assert r.json()["detail"] == "成分不存在"


def test_list_products(client):
    r = client.get("/api/products")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2  # 种子里的修丽可 CE 与 The Ordinary
    ce = [p for p in body if "CE" in p["name"]][0]
    assert ce["brand"] == "修丽可 SkinCeuticals"
    assert ce["ingredient_count"] == 12
    assert ce["claim_count"] == 0


def test_product_detail(client):
    products = client.get("/api/products").json()
    ce = [p for p in products if "CE" in p["name"]][0]
    r = client.get(f"/api/products/{ce['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == ce["name"]
    assert len(body["ingredients"]) == 12
    # 种子产品的成分带位次（官方 INCI 顺序）
    first = body["ingredients"][0]
    assert first["inci_name"] == "WATER" and first["position"] == 1
    assert body["claims"] == []


def test_product_not_found(client):
    r = client.get("/api/products/999999")
    assert r.status_code == 404
    assert r.json()["detail"] == "产品不存在"


def test_frontend_page_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "成分真言" in r.text
