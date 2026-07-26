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
        yield TestClient(app)
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
