"""功效产品榜接口 GET /api/rankings/efficacy（一期改版：首页/排行榜页数据源）。

契约：
- canon 为 efficacy_canonical 真实功效族枚举（美白/抗皱/保湿/舒缓/控油祛痘/修护/
  抗氧化/焕肤）；未知值与「其他」「防腐」非功效族一律 422；
- 排名分 = 该族有断言的成分数 ×1 + 真人级证据断言数 ×3
  （真人级 = evidence_level ∈ human_rct/human_ct/human_open）；同分按产品 id 升序；
- 响应 {"canon", "total", "items": [{id, name, brand, score, ingredient_hits,
  human_evidence}]}；只含该族有断言命中的产品；total 为命中产品总数（不受 limit 截断）；
- 口径同功效指纹：法规类（evidence_level=regulation）与原料商宣称
  （evidence.type=supplier）断言不计入；efficacy_canonical 为 NULL 时按
  canonicalize 实时映射兜底。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_db
from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.models.product import Product, ProductIngredient


def _mk(session, *, products):
    """建行工具：products 为 [(产品名, [(成分INCI, [(efficacy, canonical, level, evidence)]), ...]), ...]"""
    ev_paper = Evidence(type=EvidenceType.PAPER, title="榜单文献", source="玩具期刊", year=2021)
    ev_reg = Evidence(type=EvidenceType.REGULATION, title="限用清单", source="规范", year=2015)
    session.add_all([ev_paper, ev_reg])
    session.flush()
    ev_by_level = {"regulation": ev_reg}
    ids = {}
    for name, ings in products:
        p = Product(name=name, brand="榜单牌")
        session.add(p)
        session.flush()
        ids[name] = p.id
        for pos, (inci, assertions) in enumerate(ings, start=1):
            ing = Ingredient(inci_name=inci, cn_name=f"玩具{inci}")
            session.add(ing)
            session.flush()
            for efficacy, canonical, level in assertions:
                session.add(EfficacyAssertion(
                    ingredient_id=ing.id, efficacy=efficacy,
                    efficacy_canonical=canonical, evidence_level=level,
                    evidence_id=ev_by_level.get(level, ev_paper).id,
                    evidence_strength=0.5))
            session.add(ProductIngredient(product_id=p.id, ingredient_id=ing.id,
                                          position=pos))
    session.commit()
    return ids


@pytest.fixture()
def client(session):
    """榜单玩具数据（canon=美白 预期排名）：

    - 双真人断言精华：1 成分 × 2 条 human_open 美白断言 → hits=1, human=2, score=7
    - 真人美白精华：1 成分 × 1 条 human_rct 美白断言（canonical NULL 走映射兜底）
      → hits=1, human=1, score=4
    - 双成分美白精华：2 成分各 1 条 in_vitro 美白断言 → hits=2, human=0, score=2
    - 平分精华A/B：各 1 成分 1 条 in_vitro 美白断言 → score=1（同分按 id 升序）
    - 仅保湿精华 / 无断言精华：不进美白榜；法规美白精华：regulation 断言排除，不进榜
    """
    _mk(session, products=[
        ("双成分美白精华", [
            ("RANK-A", [("美白", "美白", "in_vitro")]),
            ("RANK-B", [("美白（抑制黑素小体转运）", "美白", "in_vitro")]),
        ]),
        ("真人美白精华", [
            ("RANK-C", [("美白淡斑（黄褐斑）", None, "human_rct")]),  # canonical 兜底
        ]),
        ("双真人断言精华", [
            ("RANK-E", [("美白", "美白", "human_open"),
                        ("美白提亮", "美白", "human_ct")]),
        ]),
        ("仅保湿精华", [
            ("RANK-D", [("保湿", "保湿", "in_vitro")]),
        ]),
        ("无断言精华", []),
        ("法规美白精华", [
            ("RANK-F", [("美白", "美白", "regulation")]),
        ]),
        ("平分精华A", [("RANK-G", [("美白", "美白", "in_vitro")])]),
        ("平分精华B", [("RANK-H", [("美白", "美白", "in_vitro")])]),
    ])
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def _by_name(client, canon="美白", **params):
    body = client.get("/api/rankings/efficacy",
                      params={"canon": canon, **params}).json()
    return body


def test_ranking_score_and_order(client, session):
    """排名分 = 成分数×1 + 真人级断言数×3；按分降序，同分按产品 id 升序。"""
    ids = {p.name: p.id for p in session.query(Product).all()}
    body = _by_name(client)
    assert body["canon"] == "美白"
    assert body["total"] == 5
    got = [(i["id"], i["score"], i["ingredient_hits"], i["human_evidence"])
           for i in body["items"]]
    assert got == [
        (ids["双真人断言精华"], 7, 1, 2),
        (ids["真人美白精华"], 4, 1, 1),
        (ids["双成分美白精华"], 2, 2, 0),
        (ids["平分精华A"], 1, 1, 0),
        (ids["平分精华B"], 1, 1, 0),
    ]
    assert ids["平分精华A"] < ids["平分精华B"]  # 同分按 id 升序的前提
    item = body["items"][0]
    assert set(item) == {"id", "name", "brand", "score",
                         "ingredient_hits", "human_evidence"}
    assert item["name"] == "双真人断言精华" and item["brand"] == "榜单牌"


def test_ranking_excludes_no_hit_products(client):
    """无该族断言命中的产品不进榜（仅保湿/无断言/法规断言被排除）。"""
    body = _by_name(client)
    names = {i["name"] for i in body["items"]}
    assert "仅保湿精华" not in names
    assert "无断言精华" not in names
    assert "法规美白精华" not in names


def test_ranking_limit(client):
    """limit 截断 items 但不影响 total。"""
    body = _by_name(client, limit=2)
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert [i["name"] for i in body["items"]] == ["双真人断言精华", "真人美白精华"]


def test_ranking_other_canon(client):
    """其他功效族正常出榜（保湿族只有仅保湿精华一款）。"""
    body = _by_name(client, canon="保湿")
    assert body["total"] == 1
    assert body["items"][0]["name"] == "仅保湿精华"
    assert body["items"][0]["score"] == 1


def test_ranking_unknown_canon_422(client):
    """未知功效族与非功效族（其他/防腐）一律 422。"""
    for bad in ("防晒", "其他", "防腐", "whitening"):
        r = client.get("/api/rankings/efficacy", params={"canon": bad})
        assert r.status_code == 422, bad


def test_ranking_canon_required(client):
    assert client.get("/api/rankings/efficacy").status_code == 422
