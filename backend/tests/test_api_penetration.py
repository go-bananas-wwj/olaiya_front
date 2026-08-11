"""成分渗透率 API 测试（借鉴 INCI Beauty「出现在 X% 产品中」统计）。

渗透率 = 含该成分的产品数 / 库中有成分表的产品总数；平均位次只统计 position 非空关联。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_db
from app.models.ingredient import Ingredient
from app.models.product import Product, ProductIngredient


@pytest.fixture()
def client(session):
    niac = Ingredient(inci_name="NIACINAMIDE", cn_name="烟酰胺")
    lonely = Ingredient(inci_name="LONELY", cn_name="冷门成分")
    base = Ingredient(inci_name="BASE", cn_name="基底成分")
    session.add_all([niac, lonely, base])
    session.flush()
    for i in range(4):
        session.add(Product(name=f"产品{i}", brand="测试品牌"))
    session.flush()
    products = session.query(Product).order_by(Product.id).all()
    # 烟酰胺进 3 个产品（其中一个 NULL 位次），冷门成分不进任何产品
    session.add(ProductIngredient(product_id=products[0].id, ingredient_id=niac.id, position=2))
    session.add(ProductIngredient(product_id=products[1].id, ingredient_id=niac.id, position=None))
    session.add(ProductIngredient(product_id=products[2].id, ingredient_id=niac.id, position=5))
    # 第 4 个产品也有成分表（不含烟酰胺），保证分母=4
    session.add(ProductIngredient(product_id=products[3].id, ingredient_id=base.id, position=1))
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def _ingredient_ids(client):
    return {i["inci_name"]: i["id"] for i in client.get("/api/ingredients").json()}


def test_penetration_basic(client):
    ids = _ingredient_ids(client)
    r = client.get(f"/api/ingredients/{ids['NIACINAMIDE']}/penetration")
    assert r.status_code == 200
    body = r.json()
    assert body["cn_name"] == "烟酰胺"
    assert body["product_count"] == 3
    assert body["total_products"] == 4
    assert body["penetration"] == pytest.approx(0.75, abs=1e-3)
    assert body["avg_position"] == pytest.approx((2 + 5) / 2, abs=1e-3)  # NULL 位次不计入


def test_penetration_zero(client):
    ids = _ingredient_ids(client)
    body = client.get(f"/api/ingredients/{ids['LONELY']}/penetration").json()
    assert body["product_count"] == 0
    assert body["penetration"] == 0
    assert body["avg_position"] is None


def test_penetration_404(client):
    assert client.get("/api/ingredients/99999/penetration").status_code == 404
