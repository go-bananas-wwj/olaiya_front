"""白盒平替得分卡 API 测试：成分+功效+价格三维可拆解的匹配备选（借鉴真我得分卡，白盒化）。

score = 归一化权重加权和（成分 Jaccard 0.5 / 功效指纹余弦 0.3 / 价格比值 0.2），
任一维缺失时该维 null 且权重在可用维上重归一化（诚实降级，不伪造）。
零成分交集产品不入选；目标无成分时 substitutes=[] + reason 降级。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_db
from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.models.product import Product, ProductIngredient
from app.services.similar_levels import reset_similar_levels_cache


@pytest.fixture()
def client(session):
    ings = [Ingredient(inci_name=f"ING{i}", cn_name=f"成分{i}") for i in range(1, 6)]
    session.add_all(ings)
    session.flush()
    ev = Evidence(type=EvidenceType.PAPER, title="t", source="s")
    session.add(ev)
    session.flush()

    def mk(name, ing_ids, price=None, with_fp=False):
        p = Product(name=name, brand="测试品牌", price_current=price)
        session.add(p)
        session.flush()
        for pos, iid in enumerate(ing_ids, start=1):
            session.add(ProductIngredient(product_id=p.id, ingredient_id=iid, position=pos))
        if with_fp:
            session.add(EfficacyAssertion(
                ingredient_id=ing_ids[0], efficacy="保湿", evidence_id=ev.id,
                evidence_level="human_rct", evidence_strength=1.0,
                efficacy_canonical="保湿"))
        return p

    target = mk("目标精华", [ings[0].id, ings[1].id, ings[2].id], price=100.0, with_fp=True)
    mk("全同产品", [ings[0].id, ings[1].id, ings[2].id], price=150.0, with_fp=True)   # 三维全有
    mk("低交集产品", [ings[1].id, ings[3].id])                    # 成分维 + 零共享功效维（ING4 有美白断言）
    mk("无交集产品", [ings[4].id])                                                     # 不入选
    mk("半同有价产品", [ings[1].id, ings[2].id], price=100.0)     # 成分+价格，无功效（不含 ING1/ING4）
    # ING4 的美白断言：目标指纹为保湿、低交集为美白 → 双方有指纹但零共享维（score=0.0 不降级）
    session.add(EfficacyAssertion(
        ingredient_id=ings[3].id, efficacy="美白", evidence_id=ev.id,
        evidence_level="human_rct", evidence_strength=1.0, efficacy_canonical="美白"))
    session.commit()
    session.expire_all()
    reset_similar_levels_cache()
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        reset_similar_levels_cache()


def _targets(client):
    return {p["name"]: p["id"] for p in client.get("/api/products").json()}


def test_scorecard_composite_and_decomposition(client):
    ids = _targets(client)
    r = client.get(f"/api/products/{ids['目标精华']}/substitutes")
    assert r.status_code == 200
    body = r.json()
    subs = {s["name"]: s for s in body["substitutes"]}
    assert "无交集产品" not in subs  # 零交集不入选
    assert [s["name"] for s in body["substitutes"]] == ["全同产品", "半同有价产品", "低交集产品"]

    full = subs["全同产品"]
    assert full["components"]["ingredient"]["score"] == 1.0
    assert full["components"]["ingredient"]["shared"] == 3
    assert full["components"]["efficacy"]["score"] == 1.0
    assert full["components"]["price"]["similarity"] == pytest.approx(100 / 150, abs=1e-3)
    assert full["components"]["price"]["candidate_price"] == 150.0
    assert full["score"] == pytest.approx(0.5 + 0.3 + 0.2 * (100 / 150), abs=1e-3)
    assert full["weights_used"] == {"ingredient": 0.5, "efficacy": 0.3, "price": 0.2}

    half = subs["半同有价产品"]
    assert half["components"]["ingredient"]["score"] == pytest.approx(2 / 3, abs=1e-3)
    assert half["components"]["efficacy"] is None  # 无功效指纹，诚实 null
    assert half["components"]["price"]["similarity"] == 1.0
    expected = (0.5 * (2 / 3) + 0.2 * 1.0) / 0.7  # 权重重归一化
    assert half["score"] == pytest.approx(expected, abs=1e-3)
    assert half["weights_used"]["efficacy"] == 0.0
    assert half["weights_used"]["ingredient"] == pytest.approx(0.5 / 0.7, abs=1e-3)

    low = subs["低交集产品"]
    # 双方有功效指纹但零共享维：真实零重叠信号 score=0.0 照常计权，不当缺失降级
    assert low["components"]["efficacy"] == {"score": 0.0, "dimensions": 0, "top_shared_dims": []}
    assert low["components"]["price"] is None  # 无价格，诚实 null
    assert low["score"] == pytest.approx((0.5 * 0.25 + 0.3 * 0.0) / 0.8, abs=1e-3)
    assert low["weights_used"] == {"ingredient": 0.625, "efficacy": 0.375, "price": 0.0}


def test_scorecard_target_without_ingredients_degrades(client, session):
    p = Product(name="空产品", brand="测试品牌")
    session.add(p)
    session.commit()
    reset_similar_levels_cache()
    body = client.get(f"/api/products/{p.id}/substitutes").json()
    assert body["substitutes"] == []
    assert body["reason"]


def test_scorecard_zero_price_degrades(client, session):
    """双方价格均为 0：无法计算比值，价格维诚实 null 降级（不除零、不伪造）。"""
    iid = session.query(Ingredient).filter_by(inci_name="ING5").first().id
    zt = Product(name="零价目标", brand="测试品牌", price_current=0.0)
    zc = Product(name="零价候选", brand="测试品牌", price_current=0.0)
    session.add_all([zt, zc])
    session.flush()
    for p in (zt, zc):
        session.add(ProductIngredient(product_id=p.id, ingredient_id=iid, position=1))
    session.commit()
    reset_similar_levels_cache()
    body = client.get(f"/api/products/{zt.id}/substitutes").json()
    subs = {s["name"]: s for s in body["substitutes"]}
    assert subs["零价候选"]["components"]["price"] is None
    assert subs["零价候选"]["weights_used"]["price"] == 0.0


def test_scorecard_404(client):
    assert client.get("/api/products/99999/substitutes").status_code == 404
