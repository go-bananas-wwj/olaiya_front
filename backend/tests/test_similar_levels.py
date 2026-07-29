"""三级相似检索单测（总纲 I3「诚实版」相似性报告）。

- L1 Jaccard 手算：shared/union 与得分逐一核对，零交集产品不入选；
- L3 余弦手算：两个玩具指纹（eff_low=None → 剂量因子 1.0，贡献=证据强度），
  「其他」维被排除（仅有「其他」维的产品不成候选）；
- L2 两路：无推断浓度 → available=false（诚实降级不伪造）；
  有推断 → min 加权余弦手算（分子 Σ_shared min(a,b)²，分母双方全向量二范数）；
- 无 N+1：每个级别批量计算，SQL 语句数 ≤3。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.db import engine
from app.main import app, get_db
from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.models.product import Product, ProductIngredient
from app.services.similar_levels import level1_jaccard, level2_dose, level3_fingerprint


def _mk(session, name, brand, ingredients):
    """建产品并按序挂成分（ingredients 为 Ingredient 列表）。"""
    p = Product(name=name, brand=brand)
    session.add(p)
    session.flush()
    for pos, ing in enumerate(ingredients, start=1):
        session.add(ProductIngredient(product_id=p.id, ingredient_id=ing.id, position=pos))
    session.flush()
    return p


@pytest.fixture()
def toy(session):
    """玩具数据集（L1/L3 共用）。

    成分断言（均无 eff_low → 剂量因子 1.0，贡献 = 证据强度）：
    A 美白0.8 / B 保湿0.4 / C 无断言 / D 美白0.6 / E 抗皱0.5 / X 仅「其他」族断言0.9

    产品：P1{A,B,C} P2{A,B,D} P3{D,E} P4{X} P5{A}
    手算指纹：P1={美白.8,保湿.4} P2={美白.8+.6=1.4,保湿.4}（同成分同族取 max，
    跨成分求和）P3={美白.6,抗皱.5} P4={其他.9} P5={美白.8}
    """
    ev = Evidence(type=EvidenceType.PAPER, title="玩具文献", source="玩具期刊", year=2020)
    a = Ingredient(inci_name="TOY-A", cn_name="玩具A")
    b = Ingredient(inci_name="TOY-B", cn_name="玩具B")
    c = Ingredient(inci_name="TOY-C", cn_name="玩具C")
    d = Ingredient(inci_name="TOY-D", cn_name="玩具D")
    e = Ingredient(inci_name="TOY-E", cn_name="玩具E")
    x = Ingredient(inci_name="TOY-X", cn_name="玩具X")
    session.add_all([ev, a, b, c, d, e, x])
    session.flush()
    session.add_all([
        EfficacyAssertion(ingredient_id=a.id, efficacy="美白", evidence_id=ev.id,
                          evidence_strength=0.8),
        EfficacyAssertion(ingredient_id=b.id, efficacy="保湿", evidence_id=ev.id,
                          evidence_strength=0.4),
        EfficacyAssertion(ingredient_id=d.id, efficacy="美白", evidence_id=ev.id,
                          evidence_strength=0.6),
        EfficacyAssertion(ingredient_id=e.id, efficacy="抗皱", evidence_id=ev.id,
                          evidence_strength=0.5),
        # 不命中任何功效族关键词 → canonical 落「其他」（L3 须排除该维）
        EfficacyAssertion(ingredient_id=x.id, efficacy="洋甘菊提取物合计", evidence_id=ev.id,
                          evidence_strength=0.9),
    ])
    p1 = _mk(session, "玩具P1", "玩具牌", [a, b, c])
    p2 = _mk(session, "玩具P2", "玩具牌", [a, b, d])
    p3 = _mk(session, "玩具P3", "玩具牌", [d, e])
    p4 = _mk(session, "玩具P4", "玩具牌", [x])
    p5 = _mk(session, "玩具P5", "玩具牌", [a])
    session.commit()
    return {"p1": p1, "p2": p2, "p3": p3, "p4": p4, "p5": p5,
            "ing": {"a": a, "b": b, "c": c, "d": d, "e": e, "x": x}}


# ---------- L1 成分集合 Jaccard ----------

def test_l1_jaccard_hand_calc(session, toy):
    hits = level1_jaccard(session, toy["p1"].id, k=5)
    # P2: 交{A,B}=2，并{A,B,C,D}=4 → 0.5；P5: 交{A}=1，并{A,B,C}=3 → 1/3
    assert [h["id"] for h in hits] == [toy["p2"].id, toy["p5"].id]
    h2, h5 = hits
    assert h2["score"] == pytest.approx(0.5)
    assert (h2["shared"], h2["union"]) == (2, 4)
    assert h5["score"] == pytest.approx(1 / 3, abs=1e-4)  # 输出 round(4)
    assert (h5["shared"], h5["union"]) == (1, 3)
    # 零交集的 P3/P4 不入选；自身不入选
    assert toy["p3"].id not in [h["id"] for h in hits]
    assert toy["p4"].id not in [h["id"] for h in hits]
    assert toy["p1"].id not in [h["id"] for h in hits]
    for h in hits:
        assert set(h) == {"id", "name", "brand", "score", "shared", "union"}
        assert h["name"] and h["brand"]


def test_l1_k_limit_and_empty(session, toy):
    assert len(level1_jaccard(session, toy["p1"].id, k=1)) == 1
    # P4 与任何产品零交集 → 空列表（不报错）
    assert level1_jaccard(session, toy["p4"].id, k=5) == []


# ---------- L3 功效指纹余弦 ----------

def test_l3_cosine_hand_calc(session, toy):
    hits = level3_fingerprint(session, toy["p1"].id, k=5)
    # P2={美白1.4,保湿.4} → 1.28/(sqrt(0.8)*sqrt(2.12)) ≈ 0.9829；
    # P5={美白.8} → 0.64/(sqrt(0.8)*0.8) ≈ 0.8944；
    # P3={美白.6,抗皱.5} → 0.48/(sqrt(0.8)*sqrt(0.61)) ≈ 0.6871
    assert [h["id"] for h in hits] == [toy["p2"].id, toy["p5"].id, toy["p3"].id]
    h2, h5, h3 = hits
    assert h2["score"] == pytest.approx(1.28 / (0.8**0.5 * 2.12**0.5), abs=1e-4)
    assert h2["dimensions"] == 2
    # top_shared_dims 按 min(双方得分) 降序：美白 min(.8,1.4)=.8 > 保湿 .4
    assert h2["top_shared_dims"] == ["美白", "保湿"]
    assert h5["score"] == pytest.approx(0.64 / (0.8**0.5 * 0.8), abs=1e-4)
    assert h5["dimensions"] == 1
    assert h5["top_shared_dims"] == ["美白"]
    assert h3["score"] == pytest.approx(0.48 / (0.8**0.5 * 0.61**0.5), abs=1e-4)
    assert h3["dimensions"] == 1
    assert h3["top_shared_dims"] == ["美白"]
    for h in hits:
        assert set(h) == {"id", "name", "brand", "score", "dimensions", "top_shared_dims"}


def test_l3_excludes_other_dimension(session, toy):
    """P4 指纹仅「其他」一维（0.9 高分）：该维被排除后为空向量，不成候选。"""
    hits = level3_fingerprint(session, toy["p1"].id, k=5)
    assert toy["p4"].id not in [h["id"] for h in hits]


def test_l3_empty_fingerprint_returns_empty(session, toy):
    """目标自身排除「其他」后无有效维 → 空列表（无功效信号可比对，不刷 0 分）。"""
    assert level3_fingerprint(session, toy["p4"].id, k=5) == []


# ---------- L2 剂量级 ----------

@pytest.fixture()
def dose_toy(session):
    """剂量玩具集：Q1/Q2 有推断浓度，Q3 无推断，Q4 有推断但成分不相交。

    Q1: A[1,3]→中点2.0, B[2,4]→中点3.0（norm²=13）
    Q2: A[1,3]→2.0, D[0,2]→1.0（norm²=5）；共享维 {A}：min(2,2)²=4
    → score = 4/sqrt(65) ≈ 0.4961
    """
    ev = Evidence(type=EvidenceType.PAPER, title="玩具文献", source="玩具期刊", year=2020)
    a = Ingredient(inci_name="DOSE-A", cn_name="剂量A")
    b = Ingredient(inci_name="DOSE-B", cn_name="剂量B")
    d = Ingredient(inci_name="DOSE-D", cn_name="剂量D")
    e = Ingredient(inci_name="DOSE-E", cn_name="剂量E")
    session.add_all([ev, a, b, d, e])
    session.flush()
    q1 = _mk(session, "剂量Q1", "玩具牌", [a, b])
    q2 = _mk(session, "剂量Q2", "玩具牌", [a, d])
    q3 = _mk(session, "剂量Q3", "玩具牌", [a])  # 无推断浓度
    q4 = _mk(session, "剂量Q4", "玩具牌", [e])  # 有推断但与 Q1 不相交
    conc_plan = {q1.id: [(1.0, 3.0), (2.0, 4.0)],   # A→2.0, B→3.0
                 q2.id: [(1.0, 3.0), (0.0, 2.0)],   # A→2.0, D→1.0
                 q4.id: [(1.0, 3.0)]}               # E→2.0；Q3 不设 → 无推断
    for pid, pairs in conc_plan.items():
        links = (session.query(ProductIngredient)
                 .filter_by(product_id=pid).order_by(ProductIngredient.id).all())
        for l, (lo, hi) in zip(links, pairs):
            l.conc_low, l.conc_high = lo, hi
    session.commit()
    return {"q1": q1, "q2": q2, "q3": q3, "q4": q4}


def test_l2_unavailable_without_inference(session, dose_toy):
    res = level2_dose(session, dose_toy["q3"].id, k=5)
    assert res["available"] is False
    assert "无推断浓度" in res["reason"]
    assert "similar" not in res  # 不可用时不伪造空榜单


def test_l2_min_weighted_cosine_hand_calc(session, dose_toy):
    res = level2_dose(session, dose_toy["q1"].id, k=5)
    assert res["available"] is True
    similar = res["similar"]
    assert [s["id"] for s in similar] == [dose_toy["q2"].id]
    assert similar[0]["score"] == pytest.approx(4 / 65**0.5, abs=1e-4)
    assert set(similar[0]) == {"id", "name", "brand", "score"}
    # 无推断的 Q3 不进候选池；有推断但零共享维的 Q4 不入选
    ids = [s["id"] for s in similar]
    assert dose_toy["q3"].id not in ids
    assert dose_toy["q4"].id not in ids


# ---------- 无 N+1：批量计算语句数上限 ----------

def _count_statements(fn):
    statements = []

    def _counter(*args):
        statements.append(args)

    event.listen(engine, "before_cursor_execute", _counter)
    try:
        result = fn()
    finally:
        event.remove(engine, "before_cursor_execute", _counter)
    return result, len(statements)


def test_no_n_plus_one(session, toy):
    """每个级别全库比对均为批量计算：数据查询 + 产品信息查询，≤3 条 SQL。"""
    _, n1 = _count_statements(lambda: level1_jaccard(session, toy["p1"].id, k=5))
    _, n3 = _count_statements(lambda: level3_fingerprint(session, toy["p1"].id, k=5))
    assert n1 <= 3, f"L1 发出 {n1} 条 SQL，疑似 N+1"
    assert n3 <= 3, f"L3 发出 {n3} 条 SQL，疑似 N+1"


def test_no_n_plus_one_l2(session, dose_toy):
    _, n2 = _count_statements(lambda: level2_dose(session, dose_toy["q1"].id, k=5))
    assert n2 <= 3, f"L2 发出 {n2} 条 SQL，疑似 N+1"


# ---------- API ----------

@pytest.fixture()
def client(session, toy, dose_toy):
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as c:
            yield c, toy
    finally:
        app.dependency_overrides.clear()


def test_similar_levels_api_structure(client):
    c, toy = client
    r = c.get(f"/api/products/{toy['p1'].id}/similar-levels")
    assert r.status_code == 200
    body = r.json()
    assert body["product_id"] == toy["p1"].id
    assert set(body) == {"product_id", "l1", "l2", "l3", "note"}
    assert "功效指纹" in body["note"]
    assert isinstance(body["l1"], list) and isinstance(body["l3"], list)
    # L1 首名是成分集最像的 P2
    assert body["l1"][0]["id"] == toy["p2"].id
    assert set(body["l1"][0]) == {"id", "name", "brand", "score", "shared", "union"}
    # L2：P1 无推断浓度 → 诚实降级
    assert body["l2"]["available"] is False
    assert body["l2"]["reason"]
    # L3 首名是指纹一致的 P2
    assert body["l3"][0]["id"] == toy["p2"].id
    assert set(body["l3"][0]) == {"id", "name", "brand", "score", "dimensions", "top_shared_dims"}


def test_similar_levels_api_k_and_404(client):
    c, toy = client
    r = c.get(f"/api/products/{toy['p1'].id}/similar-levels", params={"k": 1})
    assert r.status_code == 200
    body = r.json()
    assert len(body["l1"]) <= 1 and len(body["l3"]) <= 1
    assert c.get("/api/products/999999/similar-levels").status_code == 404
