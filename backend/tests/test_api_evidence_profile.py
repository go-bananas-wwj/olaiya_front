"""证据充分度面板 API 测试：按证据层级统计一个产品的断言分布（借鉴 EWG 数据充分度维度）。

unknown 计数必须如实展示（把「不知道」做成一等公民），断言为 0 时全部落 0 不报错。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_db
from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.models.product import Product, ProductIngredient
from app.services.evidence_level import EVIDENCE_LEVELS


@pytest.fixture()
def client(session):
    p = Product(name="测试精华", brand="测试品牌")
    session.add(p)
    i1 = Ingredient(inci_name="NIACINAMIDE", cn_name="烟酰胺")
    i2 = Ingredient(inci_name="GLYCERIN", cn_name="甘油")
    i3 = Ingredient(inci_name="WATER", cn_name="水")
    session.add_all([i1, i2, i3])
    session.flush()
    for pos, ing in enumerate([i1, i2, i3], start=1):
        session.add(ProductIngredient(product_id=p.id, ingredient_id=ing.id, position=pos))
    ev = Evidence(type=EvidenceType.PAPER, title="t", source="s")
    session.add(ev)
    session.flush()
    # i1 两条断言（human_rct + in_vitro），i2 两条（regulation + NULL 落 unknown），i3 无断言
    session.add_all([
        EfficacyAssertion(ingredient_id=i1.id, efficacy="美白", evidence_id=ev.id,
                          evidence_level="human_rct", evidence_strength=1.0),
        EfficacyAssertion(ingredient_id=i1.id, efficacy="修护", evidence_id=ev.id,
                          evidence_level="in_vitro", evidence_strength=0.5),
        EfficacyAssertion(ingredient_id=i2.id, efficacy="法定限用：甘油", evidence_id=ev.id,
                          evidence_level="regulation", evidence_strength=0.9),
        EfficacyAssertion(ingredient_id=i2.id, efficacy="保湿", evidence_id=ev.id),  # NULL → unknown
    ])
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def _product_id(client) -> int:
    return client.get("/api/products").json()[0]["id"]


def test_evidence_profile_distribution(client):
    r = client.get(f"/api/products/{_product_id(client)}/evidence-profile")
    assert r.status_code == 200
    body = r.json()
    assert body["assertions_total"] == 4
    assert body["ingredients_total"] == 3
    assert body["ingredients_with_assertions"] == 2
    by_level = {row["level"]: row for row in body["by_level"]}
    # 全部层级键都在（含 0 计数），unknown 不隐藏
    assert set(by_level) == set(EVIDENCE_LEVELS)
    assert by_level["human_rct"]["count"] == 1
    assert by_level["in_vitro"]["count"] == 1
    assert by_level["regulation"]["count"] == 1
    assert by_level["unknown"]["count"] == 1  # NULL evidence_level 如实落 unknown
    assert by_level["human_rct"]["ratio"] == pytest.approx(1 / 4, abs=1e-3)
    # 每个层级带中文标签（前端徽章直接用）
    assert by_level["human_rct"]["label"]


def test_evidence_profile_ordered_by_strength_desc(client):
    body = client.get(f"/api/products/{_product_id(client)}/evidence-profile").json()
    levels = [row["level"] for row in body["by_level"]]
    assert levels[0] == "human_rct"  # 最强证据排最前
    assert levels.index("human_rct") < levels.index("unknown")


def test_evidence_profile_empty_product(client, session):
    p = Product(name="无断言产品", brand="测试品牌")
    session.add(p)
    session.commit()
    body = client.get(f"/api/products/{p.id}/evidence-profile").json()
    assert body["assertions_total"] == 0
    assert all(row["count"] == 0 and row["ratio"] == 0 for row in body["by_level"])


def test_evidence_profile_404(client):
    assert client.get("/api/products/99999/evidence-profile").status_code == 404
