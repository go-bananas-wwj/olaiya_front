"""相似产品价格、来源与成分差异：保留检索分数，不混用质量和体积。"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_db
from app.models.ingredient import Ingredient
from app.models.product import PricePoint, Product, ProductIngredient
from app.services.similar_levels import reset_similar_levels_cache
from app.services.comparison_metadata import enrich_candidates


@pytest.fixture()
def comparison(session, monkeypatch):
    ingredients = [Ingredient(inci_name=f"COMPARE-{i}", cn_name=f"测试成分{i}") for i in range(3)]
    products = [
        Product(name="目标", brand="测试", price_current=120, spec="30ml"),
        Product(name="相似", brand="测试", price_current=50, spec="50克",
                source_url="https://example.org/formula", buy_url="https://example.org/buy"),
        Product(name="缺价", brand="测试"),
    ]
    session.add_all(ingredients + products)
    session.flush()
    for product, indexes in zip(products, [(0, 1), (0, 2), (0,)]):
        for index in indexes:
            session.add(ProductIngredient(product_id=product.id, ingredient_id=ingredients[index].id))
    session.add_all([
        PricePoint(product_id=products[1].id, date=date(2026, 8, 1), price=50,
                   source="https://example.org/price", is_manual=True),
        # 最近的历史价格与当前值不符，不能冒充当前价格来源。
        PricePoint(product_id=products[1].id, date=date(2026, 8, 2), price=90,
                   source="https://example.org/other-price", is_manual=True),
    ])
    session.commit()
    monkeypatch.setattr("app.main.search_products", lambda pid, k: [
        {"product_id": products[1].id, "score": 0.9},
        {"product_id": products[2].id, "score": 0.8},
    ][:k])
    reset_similar_levels_cache()
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            yield client, products, ingredients
    finally:
        app.dependency_overrides.clear()
        reset_similar_levels_cache()


def test_embedding_results_include_price_and_formula_difference(comparison):
    client, products, ingredients = comparison
    result = client.get(f"/api/products/{products[0].id}/similar").json()["similar"]
    first, missing = result
    assert [r["score"] for r in result] == [0.9, 0.8]
    assert first["price_current"] == 50
    assert first["spec"] == "50克"
    assert first["unit_price"] == 1
    assert first["unit_price_unit"] == "g"
    assert first["price_source"] == "https://example.org/price"
    assert first["price_recorded_at"] == "2026-08-01"
    assert first["source_url"] == "https://example.org/formula"
    assert first["buy_url"] == "https://example.org/buy"
    assert (first["shared"], first["union"]) == (1, 3)
    assert [i["ingredient_id"] for i in first["shared_ingredients"]] == [ingredients[0].id]
    assert [i["ingredient_id"] for i in first["only_target_ingredients"]] == [ingredients[1].id]
    assert [i["ingredient_id"] for i in first["only_candidate_ingredients"]] == [ingredients[2].id]
    assert missing["price_current"] is None
    assert missing["unit_price"] is None
    assert missing["price_source"] is None


def test_set_similarity_uses_same_metadata(comparison):
    client, products, _ = comparison
    result = client.get(f"/api/products/{products[0].id}/similar-levels").json()
    candidate = next(i for i in result["l1"] if i["id"] == products[1].id)
    assert candidate["score"] == pytest.approx(1 / 3, abs=1e-4)
    assert candidate["unit_price_unit"] == "g"
    assert candidate["price_source"] == "https://example.org/price"


def test_candidate_metadata_is_batched_and_deleted_index_rows_are_skipped(comparison, session):
    from sqlalchemy import event

    _, products, _ = comparison
    statements = []
    def count_statement(*args):
        statements.append(1)
    event.listen(session.bind, "before_cursor_execute", count_statement)
    try:
        result = enrich_candidates(session, products[0].id, [
            {"id": p.id, "score": .5} for p in products[1:]
        ] + [{"id": 999999, "score": .9}])
    finally:
        event.remove(session.bind, "before_cursor_execute", count_statement)
    assert len(statements) <= 3
    assert [r["id"] for r in result] == [p.id for p in products[1:]]


@pytest.mark.parametrize("spec, price, expected, unit", [
    ("30ml", 120, 4, "ml"), (" 50 毫升 ", 100, 2, "ml"),
    ("50g", 100, 2, "g"), ("50克", 0, 0, "g"),
    ("30ml×2", 100, None, None), ("0ml", 100, None, None),
    (None, 100, None, None), ("30ml", None, None, None),
    ("30ml", -1, None, None),
])
def test_product_unit_price_never_assumes_density(comparison, session, spec, price, expected, unit):
    client, products, _ = comparison
    target = products[0]
    target.spec, target.price_current = spec, price
    session.commit()
    result = client.get(f"/api/products/{target.id}").json()
    assert result["unit_price"] == expected
    assert result["unit_price_unit"] == unit
    # 产品来源页、购买页都不能替代未记录的价格来源。
    assert result["price_source"] is None
