"""列表接口大数据量性能修复（P0）：聚合子查询 + LIMIT/OFFSET 下推 + total。

契约：
- /api/products、/api/ingredients 不带 limit/offset 时保持旧的纯 list 返回（向后兼容）；
  带 limit>0 或 offset>0 时返回 {"total": 过滤后总数, "items": [...]}，item 字段不变。
- /api/ingredients/{id} 响应增加 product_total；products 默认前 50 条，
  可用 product_limit / product_offset 翻页（product_limit=0 表示不限）。
- /api/brands 返回去重排序后的品牌名 list。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.db import engine
from app.main import app, get_db
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


def _count_selects(fn):
    """执行 fn 并统计发出的 SELECT 语句数（含子查询展开前的语句级别）。"""
    n = [0]

    def _listener(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            n[0] += 1

    event.listen(engine, "before_cursor_execute", _listener)
    try:
        return fn(), n[0]
    finally:
        event.remove(engine, "before_cursor_execute", _listener)


# ---------- /api/products 聚合与分页 ----------


def test_products_paginated_shape_and_total(client):
    full = client.get("/api/products").json()
    r = client.get("/api/products", params={"limit": 1})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"total", "items"}
    assert body["total"] == len(full)
    assert len(body["items"]) == 1
    # item 字段与旧结构一致
    assert set(body["items"][0]) == {"id", "name", "brand", "nmpa_id",
                                     "claim_count", "ingredient_count"}
    assert body["items"][0]["id"] == full[0]["id"]


def test_products_offset(client):
    full = client.get("/api/products").json()
    body = client.get("/api/products", params={"limit": 1, "offset": 1}).json()
    assert body["total"] == len(full)
    assert [p["id"] for p in body["items"]] == [full[1]["id"]]
    # offset 越过末尾：空页但 total 不变
    tail = client.get("/api/products", params={"limit": 1, "offset": len(full)}).json()
    assert tail["total"] == len(full) and tail["items"] == []


def test_products_no_pagination_keeps_list(client):
    """不带 limit/offset：保持旧的纯 list 返回（前端旧代码兼容）。"""
    r = client.get("/api/products")
    assert isinstance(r.json(), list)


def test_products_pagination_counts_correct(client, session):
    """聚合子查询出的 claim_count / ingredient_count 与逐条 COUNT 一致。"""
    p = client.get("/api/products").json()[0]
    session.add(ProductClaim(product_id=p["id"], claim="保湿"))
    session.commit()
    body = client.get("/api/products", params={"limit": 50}).json()
    for item in body["items"]:
        assert item["claim_count"] == (
            session.query(ProductClaim).filter_by(product_id=item["id"]).count())
        assert item["ingredient_count"] == (
            session.query(ProductIngredient).filter_by(product_id=item["id"]).count())


def test_products_pagination_filters(client, session):
    """has_claims / brand / q 过滤在 SQL 层生效，total 为过滤后总数。"""
    p = client.get("/api/products").json()[0]
    session.add(ProductClaim(product_id=p["id"], claim="保湿"))
    session.commit()
    with_claims = client.get("/api/products",
                             params={"has_claims": "true", "limit": 10}).json()
    assert with_claims["total"] == 1
    assert [x["id"] for x in with_claims["items"]] == [p["id"]]
    without = client.get("/api/products",
                         params={"has_claims": "false", "limit": 10}).json()
    assert without["total"] == 1
    by_brand = client.get("/api/products", params={
        "brand": "修丽可 SkinCeuticals", "limit": 10}).json()
    assert by_brand["total"] == 1
    assert by_brand["items"][0]["brand"] == "修丽可 SkinCeuticals"


def test_products_query_count_constant(client, session):
    """limit 下推后查询数为常数：加产品前后 SELECT 次数不变且为个位数。"""
    _, n1 = _count_selects(lambda: client.get("/api/products", params={"limit": 1}))
    for i in range(10):
        extra = Product(name=f"压测产品{i}", brand="压测")
        session.add(extra)
        session.flush()
        session.add(ProductClaim(product_id=extra.id, claim="保湿"))
    session.commit()
    _, n2 = _count_selects(lambda: client.get("/api/products", params={"limit": 1}))
    assert n1 == n2, f"查询数随数据量增长：{n1} -> {n2}"
    assert n2 <= 3, f"单页产品列表不应超过 3 条 SELECT（聚合+计数），实际 {n2}"


# ---------- /api/brands ----------


def test_brands_endpoint(client, session):
    session.add(Product(name="重复品牌产品", brand="The Ordinary"))
    session.commit()
    r = client.get("/api/brands")
    assert r.status_code == 200
    brands = r.json()
    assert isinstance(brands, list)
    assert brands == sorted(set(brands))  # 去重且排序
    assert "修丽可 SkinCeuticals" in brands and "The Ordinary" in brands


# ---------- /api/ingredients 聚合与分页 ----------


def test_ingredients_paginated_shape_and_total(client):
    full = client.get("/api/ingredients").json()
    body = client.get("/api/ingredients", params={"limit": 2, "offset": 1}).json()
    assert set(body) == {"total", "items"}
    assert body["total"] == len(full)
    assert [i["id"] for i in body["items"]] == [i["id"] for i in full[1:3]]
    assert set(body["items"][0]) == {"id", "inci_name", "cn_name", "cas_no",
                                     "assertion_count"}


def test_ingredients_no_pagination_keeps_list(client):
    assert isinstance(client.get("/api/ingredients").json(), list)


def test_ingredients_pagination_counts_and_filter(client, session):
    body = client.get("/api/ingredients", params={"limit": 100}).json()
    for item in body["items"]:
        assert item["assertion_count"] == (
            session.query(EfficacyAssertion)
            .filter_by(ingredient_id=item["id"]).count())
    with_ev = client.get("/api/ingredients",
                         params={"has_evidence": "true", "limit": 100}).json()
    assert with_ev["total"] == 5  # 种子里 5 个登记成分有断言
    assert all(i["assertion_count"] > 0 for i in with_ev["items"])
    no_ev = client.get("/api/ingredients",
                       params={"has_evidence": "false", "limit": 100}).json()
    assert no_ev["total"] == body["total"] - 5


def test_products_negative_limit_offset_422(client):
    """limit/offset 为负：参数校验 422（ge=0），不下推到 SQL。"""
    assert client.get("/api/products", params={"limit": -1}).status_code == 422
    assert client.get("/api/products", params={"offset": -5}).status_code == 422
    # 0 仍合法（limit=0 表示不限）
    assert client.get("/api/products", params={"limit": 0, "offset": 0}).status_code == 200


def test_ingredients_query_count_constant(client, session):
    _, n1 = _count_selects(lambda: client.get("/api/ingredients", params={"limit": 1}))
    for i in range(10):
        session.add(Ingredient(inci_name=f"BENCH ING {i}", cn_name=f"压测成分{i}"))
    session.commit()
    _, n2 = _count_selects(lambda: client.get("/api/ingredients", params={"limit": 1}))
    assert n1 == n2, f"查询数随数据量增长：{n1} -> {n2}"
    assert n2 <= 3, f"单页成分列表不应超过 3 条 SELECT，实际 {n2}"


def test_ingredients_negative_limit_offset_422(client):
    assert client.get("/api/ingredients", params={"limit": -1}).status_code == 422
    assert client.get("/api/ingredients", params={"offset": -5}).status_code == 422
    assert client.get("/api/ingredients", params={"limit": 0, "offset": 0}).status_code == 200


# ---------- /api/ingredients/{id} 产品分页 ----------


def _make_products_with_ingredient(session, ing_id, n):
    ids = []
    for i in range(n):
        p = Product(name=f"含成分产品{i}", brand=f"品牌{i % 3}")
        session.add(p)
        session.flush()
        session.add(ProductIngredient(product_id=p.id, ingredient_id=ing_id, position=1))
        ids.append(p.id)
    session.commit()
    return ids


def test_ingredient_detail_product_total_and_default_cap(client, session):
    ing = session.query(Ingredient).filter_by(inci_name="NIACINAMIDE").one()
    ids = _make_products_with_ingredient(session, ing.id, 60)
    body = client.get(f"/api/ingredients/{ing.id}").json()
    assert body["product_total"] == len(ids) + 1  # 种子 The Ordinary + 60 个新品
    assert len(body["products"]) == 50  # 默认只给前 50 条
    assert all(set(p) == {"id", "name", "brand"} for p in body["products"])


def test_ingredient_detail_product_pagination(client, session):
    ing = session.query(Ingredient).filter_by(inci_name="NIACINAMIDE").one()
    ids = sorted(_make_products_with_ingredient(session, ing.id, 5))
    body = client.get(f"/api/ingredients/{ing.id}",
                      params={"product_limit": 3, "product_offset": 1}).json()
    assert body["product_total"] == 6
    assert len(body["products"]) == 3
    got = [p["id"] for p in body["products"]]
    assert got == sorted(got)  # 按产品 id 排序
    # product_limit=0 表示不限（旧行为可复原）
    full = client.get(f"/api/ingredients/{ing.id}",
                      params={"product_limit": 0}).json()
    assert len(full["products"]) == 6


def test_ingredient_detail_products_dedup(client, session):
    """同一产品重复关联同一成分时，产品列表与 total 都去重。"""
    ing = session.query(Ingredient).filter_by(inci_name="NIACINAMIDE").one()
    p = Product(name="重复关联产品", brand="TEST")
    session.add(p)
    session.flush()
    session.add(ProductIngredient(product_id=p.id, ingredient_id=ing.id, position=1))
    session.add(ProductIngredient(product_id=p.id, ingredient_id=ing.id, position=2))
    session.commit()
    body = client.get(f"/api/ingredients/{ing.id}").json()
    got = [x["id"] for x in body["products"]]
    assert got.count(p.id) == 1
    assert body["product_total"] == len(set(got)) == len(got)
