import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func

from app.main import app, get_db
from app.models.evidence import Evidence
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.models.product import Product, ProductClaim, ProductIngredient
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


# —— Part 4：统计 / 过滤 / 成分-产品关联 / 证据标记 ——


def test_stats(client, session):
    r = client.get("/api/stats")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "products": session.query(Product).count(),
        "brands": session.query(func.count(func.distinct(Product.brand))).scalar(),
        "ingredients": session.query(Ingredient).count(),
        "ingredients_with_evidence": session.query(
            func.count(func.distinct(EfficacyAssertion.ingredient_id))).scalar(),
        "product_ingredients": session.query(ProductIngredient).count(),
        "claims": session.query(ProductClaim).count(),
        "assertions": session.query(EfficacyAssertion).count(),
        "evidence": session.query(Evidence).count(),
    }
    assert body["ingredients_with_evidence"] == 5  # 种子里 5 个登记成分均有断言
    assert body["claims"] == 0


def test_products_filter_brand(client):
    r = client.get("/api/products", params={"brand": "修丽可 SkinCeuticals"})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["brand"] == "修丽可 SkinCeuticals"
    assert client.get("/api/products", params={"brand": "不存在的品牌"}).json() == []


def test_products_filter_has_claims(client, session):
    # 种子不含宣称：全部落在 false 侧
    assert len(client.get("/api/products", params={"has_claims": "false"}).json()) == 2
    assert client.get("/api/products", params={"has_claims": "true"}).json() == []
    p = client.get("/api/products").json()[0]
    session.add(ProductClaim(product_id=p["id"], claim="保湿"))
    session.commit()
    with_claims = client.get("/api/products", params={"has_claims": "true"}).json()
    assert [x["id"] for x in with_claims] == [p["id"]]
    without = client.get("/api/products", params={"has_claims": "false"}).json()
    assert p["id"] not in {x["id"] for x in without}


def test_products_filter_limit(client):
    all_products = client.get("/api/products").json()
    r = client.get("/api/products", params={"limit": 1})
    assert [p["id"] for p in r.json()] == [all_products[0]["id"]]
    # 0 与不传等价：不限
    assert client.get("/api/products", params={"limit": 0}).json() == all_products


def test_ingredients_has_evidence_and_assertion_count(client, session):
    body = client.get("/api/ingredients").json()
    assert all("assertion_count" in i for i in body)
    for i in body:
        expected = session.query(EfficacyAssertion).filter_by(ingredient_id=i["id"]).count()
        assert i["assertion_count"] == expected
    with_ev = client.get("/api/ingredients", params={"has_evidence": "true"}).json()
    assert with_ev and all(i["assertion_count"] > 0 for i in with_ev)
    # 种子里产品成分表带入的 stub 成分无断言，必被过滤掉
    assert len(with_ev) == 5 and len(with_ev) < len(body)


def test_ingredient_detail_products(client):
    items = client.get("/api/ingredients", params={"q": "烟酰胺"}).json()
    body = client.get(f"/api/ingredients/{items[0]['id']}").json()
    assert body["products"], "烟酰胺必须出现在 The Ordinary 精华中"
    assert all(set(p) == {"id", "name", "brand"} for p in body["products"])
    ids = [p["id"] for p in body["products"]]
    assert ids == sorted(ids)
    # 交叉验证：这些产品详情页的成分表确实含烟酰胺
    for p in body["products"]:
        detail = client.get(f"/api/products/{p['id']}").json()
        assert any(i["inci_name"] == "NIACINAMIDE" for i in detail["ingredients"])
    # 原有断言结构不受影响
    assert body["assertions"][0]["evidence"]["type"] == "paper"


def test_product_detail_ingredient_evidence_flags(client, session):
    products = client.get("/api/products").json()
    ce = [p for p in products if "CE" in p["name"]][0]
    body = client.get(f"/api/products/{ce['id']}").json()
    first = body["ingredients"][0]
    assert first["inci_name"] == "WATER"
    assert isinstance(first["ingredient_id"], int)
    assert first["has_evidence"] is False  # stub 成分无断言
    flagged = [i for i in body["ingredients"] if i["has_evidence"]]
    assert {i["inci_name"] for i in flagged} == {"ASCORBIC ACID", "PHENOXYETHANOL"}
    for i in body["ingredients"]:
        expected = (session.query(EfficacyAssertion)
                    .filter_by(ingredient_id=i["ingredient_id"]).count()) > 0
        assert i["has_evidence"] == expected
