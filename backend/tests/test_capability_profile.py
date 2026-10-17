from sqlalchemy import event
from fastapi.testclient import TestClient

from app.main import app, get_db
from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import Ingredient, EfficacyAssertion
from app.models.product import Product, ProductIngredient


def seed(session):
    product = Product(name="证据对照样本", brand="测试品牌")
    ingredients = [Ingredient(inci_name=f"TEST-{i}", cn_name=f"测试成分{i}") for i in range(3)]
    session.add_all([product, *ingredients]); session.flush()
    for i, ingredient in enumerate(ingredients):
        session.add(ProductIngredient(product_id=product.id, ingredient_id=ingredient.id,
                                      position=i + 1, conc_low=0.1, conc_high=0.2))
    session.commit()
    return product, ingredients


def assertion(session, ingredient, weight=0.8, level="human_ct", kind=EvidenceType.PAPER,
              efficacy="保湿", source=None, **extra):
    if source is None:
        source = Evidence(type=kind, title="测试资料", source="测试来源", url="https://example.org/evidence")
        session.add(source); session.flush()
    item = EfficacyAssertion(ingredient_id=ingredient.id, efficacy=efficacy,
                            evidence_id=source.id, evidence_strength=weight, evidence_level=level, **extra)
    session.add(item); session.commit()
    return item


def profile(session, product):
    from app.services.capability_profile import capability_profile
    return capability_profile(session, product.id)


def dimension(data, family="保湿"):
    return next(d for d in data["dimensions"] if d["canonical"] == family)


def test_max_per_ingredient_family_is_recomputable_and_sources_are_deduplicated(session):
    product, ingredients = seed(session)
    best = assertion(session, ingredients[0], weight=0.8, effective_conc_low=1)
    assertion(session, ingredients[0], weight=0.5, level="in_vitro", note="体外研究")
    assertion(session, ingredients[0], weight=0.8)  # identical weight does not increase score
    assertion(session, ingredients[1], weight=0.8, source=best.evidence)
    d = dimension(profile(session, product))
    assert d["score"] == 1.6
    assert d["status"] == "scored"
    assert d["ingredient_count"] == 2
    assert d["source_count"] == 1
    assert sum(c["weight"] for c in d["contributions"]) == d["score"]
    assert d["contributions"][0]["assertion_id"] == best.id
    assert d["contributions"][0]["evidence"]["id"] == best.evidence_id
    assert d["contributions"][0]["dose"]["verdict"] == "insufficient"


def test_non_efficacy_channels_and_oral_studies_do_not_score(session):
    product, ingredients = seed(session)
    for kind in [EvidenceType.DATABASE, EvidenceType.REGULATION, EvidenceType.PATENT,
                 EvidenceType.SUPPLIER, EvidenceType.WHITE_PAPER]:
        assertion(session, ingredients[0], kind=kind, weight=1)
    assertion(session, ingredients[0], level="oral", note="口服研究，不可外推外用")
    assertion(session, ingredients[0], level="human_rct", note="口服随机试验")
    assertion(session, ingredients[0], efficacy="安全评估：保湿剂的使用浓度", weight=1)
    result = profile(session, product)
    assert dimension(result)["score"] is None
    assert len(result["excluded"]) == 8
    assert all(e["reason"] and e["evidence"]["id"] for e in result["excluded"])


def test_missing_unrated_and_real_zero_are_different(session):
    product, ingredients = seed(session)
    assertion(session, ingredients[0], level="unknown", weight=0.2)
    assertion(session, ingredients[1], level="human_ct", weight=None)
    d = dimension(profile(session, product))
    assert d["score"] is None and d["unrated_count"] == 2
    assert d["status"] == "unrated"
    assertion(session, ingredients[2], weight=0)
    d = dimension(profile(session, product))
    assert d["score"] == 0 and d["status"] == "scored"
    empty = dimension(profile(session, product), "美白")
    assert empty["score"] is None and empty["status"] == "no_evidence"


def test_book_is_low_strength_reference_and_weak_notes_are_preserved(session):
    product, ingredients = seed(session)
    assertion(session, ingredients[0], kind=EvidenceType.BOOK, level="unknown", weight=0.3)
    assertion(session, ingredients[1], level="in_vitro", weight=0.5,
              note="体外复方研究，不能归因于单一成分")
    d = dimension(profile(session, product))
    assert d["score"] == 0.8
    assert d["contributions"][0]["note"] == "体外复方研究，不能归因于单一成分"
    book = next(c for c in d["contributions"] if c["evidence"]["type"] == "book")
    assert book["weight"] == 0.3
    assert book["reference_only"] is True


def test_concentration_changes_do_not_change_index_and_unknown_positions_are_not_inferred(session):
    product, ingredients = seed(session)
    assertion(session, ingredients[0], effective_conc_low=1)
    before = dimension(profile(session, product))
    link = session.query(ProductIngredient).filter_by(ingredient_id=ingredients[0].id).one()
    link.position = None
    session.commit()
    after = dimension(profile(session, product))
    assert before["score"] == after["score"] == 0.8
    assert after["contributions"][0]["concentration"]["status"] == "unknown"
    assert after["contributions"][0]["dose"]["verdict"] == "unknown"
    link.disclosed_conc = 2
    session.commit()
    disclosed = dimension(profile(session, product))["contributions"][0]
    assert disclosed["concentration"]["status"] == "disclosed"
    assert disclosed["dose"]["verdict"] == "effective"


def test_eight_directions_and_api_404(session):
    product, _ = seed(session)
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            r = client.get(f"/api/products/{product.id}/capability-profile")
            assert r.status_code == 200
            data = r.json()
            assert data["method_version"] == "evidence-index-v1"
            assert [d["canonical"] for d in data["dimensions"]] == ["保湿", "抗皱", "修护", "舒缓", "抗氧化", "美白", "控油祛痘", "焕肤"]
            assert client.get("/api/products/999999/capability-profile").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_query_count_is_independent_of_ingredient_count(session):
    product, ingredients = seed(session)
    for ingredient in ingredients:
        assertion(session, ingredient)
    selects = []
    engine = session.get_bind()
    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)
    event.listen(engine, "before_cursor_execute", record)
    try:
        assert dimension(profile(session, product))["ingredient_count"] == 3
        assert len(selects) <= 2
    finally:
        event.remove(engine, "before_cursor_execute", record)


def test_invalid_weights_and_overrated_books_are_excluded_and_json_safe(session):
    import json
    product, ingredients = seed(session)
    assertion(session, ingredients[0], weight=float('inf'), effective_conc_low=float('inf'))
    assertion(session, ingredients[1], kind=EvidenceType.BOOK, level='unknown', weight=0.8)
    data = profile(session, product)
    assert dimension(data)['score'] is None
    assert len(data['excluded']) == 2
    json.dumps(data, allow_nan=False)
