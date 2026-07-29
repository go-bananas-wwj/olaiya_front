"""功效指纹单测（总纲 I3）：功效空间稀疏向量，维度得分 = Σ(剂量因子 × 证据强度)。

dose_factor 四分支：无起效浓度基准 / 推断区间中点比（cap 1.5）/ 未知剂量保守默认 /
微量线 ppm 口径（与 dosecheck 的 trace_level 同口径，优先于推断区间）。
compute_fingerprint：同成分同功效多断言取 max contribution 不重复累加；
coverage 的 inferred_dose/unknown_dose 为成分级计数（合计 = ingredients_total）。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_db
from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.models.product import Product, ProductIngredient
from app.services.fingerprint import UNKNOWN_DOSE_FACTOR, compute_fingerprint, dose_factor


@pytest.mark.parametrize(
    "conc_low,conc_high,eff_low,is_trace,expected_factor,expected_basis",
    [
        # 无起效浓度基准：证据强度全额计入（无论有无推断区间）
        (1.0, 3.0, None, False, 1.0, "无起效浓度基准"),
        (None, None, None, False, 1.0, "无起效浓度基准"),
        # 推断区间：中点 / eff_low
        (1.0, 3.0, 2.0, False, 1.0, "推断区间"),      # 中点 2.0 / 2.0
        (0.5, 1.5, 2.0, False, 0.5, "推断区间"),      # 中点 1.0 / 2.0
        (0.2, 0.8, 4.0, False, 0.125, "推断区间"),    # 中点 0.5 / 4.0
        # 推断区间：充足度 cap 到 1.5（超过起效线最多按 1.5 倍计）
        (2.0, 6.0, 2.0, False, 1.5, "推断区间"),      # 中点 4.0 / 2.0 = 2.0 → cap
        (9.0, 11.0, 1.0, False, 1.5, "推断区间"),     # 中点 10.0 / 1.0 = 10.0 → cap
        # 无推断区间 → 保守默认（诚实默认：不虚报也不抹杀）
        (None, None, 2.0, False, UNKNOWN_DOSE_FACTOR, "未知剂量"),
        # 微量线 ppm 口径：微量段成分且起效线 < 0.1%，存在即可能起效
        (None, None, 0.05, True, 1.0, "微量线 ppm 口径"),
        # trace 优先于推断区间（与 dosecheck「trace 仍优先」一致）
        (0.001, 0.01, 0.0003, True, 1.0, "微量线 ppm 口径"),
        # is_trace 但起效线不在微量区间：不触发 ppm 口径
        (None, None, 0.5, True, UNKNOWN_DOSE_FACTOR, "未知剂量"),
        (None, None, 0.1, True, UNKNOWN_DOSE_FACTOR, "未知剂量"),   # 恰等 0.1 不算 ppm
    ],
)
def test_dose_factor_branches(conc_low, conc_high, eff_low, is_trace,
                              expected_factor, expected_basis):
    factor, basis = dose_factor(conc_low=conc_low, conc_high=conc_high,
                                eff_low=eff_low, is_trace=is_trace)
    assert factor == pytest.approx(expected_factor)
    assert basis == expected_basis


def _toy_product(session):
    """玩具产品：A 有推断区间（中点 2.0），B/C 无；C 无任何断言。

    手算贡献：
    - A 美白（eff_low 2.0，强度 0.8）：dose = 2.0/2.0 = 1.0 → 0.8
    - A 美白（eff_low 1.0，强度 0.5）：dose = cap(2.0/1.0) = 1.5 → 0.75（同成分同功效取 max，丢弃）
    - A 保湿（无 eff_low，强度 0.4）：dose = 1.0（无基准）→ 0.4
    - B 美白（eff_low 2.0，强度 0.6，无区间）：dose = 0.5（未知剂量）→ 0.3
    指纹：美白 = 0.8 + 0.3 = 1.1，保湿 = 0.4
    """
    ev = Evidence(type=EvidenceType.PAPER, title="玩具文献", source="玩具期刊", year=2020)
    a = Ingredient(inci_name="TOY-A", cn_name="玩具成分A")
    b = Ingredient(inci_name="TOY-B", cn_name="玩具成分B")
    c = Ingredient(inci_name="TOY-C", cn_name="玩具成分C")
    p = Product(name="玩具精华", brand="玩具牌")
    session.add_all([ev, a, b, c, p])
    session.flush()
    session.add_all([
        EfficacyAssertion(ingredient_id=a.id, efficacy="美白", evidence_id=ev.id,
                          effective_conc_low=2.0, evidence_strength=0.8),
        EfficacyAssertion(ingredient_id=a.id, efficacy="美白", evidence_id=ev.id,
                          effective_conc_low=1.0, evidence_strength=0.5),
        EfficacyAssertion(ingredient_id=a.id, efficacy="保湿", evidence_id=ev.id,
                          effective_conc_low=None, evidence_strength=0.4),
        EfficacyAssertion(ingredient_id=b.id, efficacy="美白", evidence_id=ev.id,
                          effective_conc_low=2.0, evidence_strength=0.6),
        ProductIngredient(product_id=p.id, ingredient_id=a.id, position=1,
                          conc_low=1.0, conc_high=3.0),
        ProductIngredient(product_id=p.id, ingredient_id=b.id, position=None),
        ProductIngredient(product_id=p.id, ingredient_id=c.id, position=None),
    ])
    session.commit()
    return p


def test_compute_fingerprint_scores(session):
    p = _toy_product(session)
    result = compute_fingerprint(session, p.id)
    # 美白 = max(0.8, 0.75) + 0.3 = 1.1（同成分同功效取 max，不累加 0.75）
    assert result["fingerprint"] == {"美白": 1.1, "保湿": 0.4}


def test_compute_fingerprint_detail(session):
    p = _toy_product(session)
    result = compute_fingerprint(session, p.id)
    detail = result["detail"]
    assert len(detail) == 4  # C 无断言不产生 detail 行
    a_mei = [d for d in detail if d["inci_name"] == "TOY-A" and d["efficacy"] == "美白"]
    assert len(a_mei) == 2  # 两条断言都入 detail（max 只影响维度加总）
    strong = next(d for d in a_mei if d["evidence_strength"] == 0.8)
    assert strong["dose_factor"] == 1.0
    assert strong["dose_basis"] == "推断区间"
    assert strong["contribution"] == 0.8
    capped = next(d for d in a_mei if d["evidence_strength"] == 0.5)
    assert capped["dose_factor"] == 1.5  # 2.0/1.0 被 cap
    assert capped["contribution"] == 0.75
    b = next(d for d in detail if d["inci_name"] == "TOY-B")
    assert b["dose_factor"] == 0.5
    assert b["dose_basis"] == "未知剂量"
    assert b["contribution"] == 0.3  # round(0.5*0.6, 4)，无浮点尾巴
    a_bao = next(d for d in detail if d["efficacy"] == "保湿")
    assert a_bao["dose_basis"] == "无起效浓度基准"
    assert a_bao["contribution"] == 0.4


def test_compute_fingerprint_coverage(session):
    p = _toy_product(session)
    cov = compute_fingerprint(session, p.id)["coverage"]
    assert cov == {"ingredients_total": 3, "ingredients_with_assertion": 2,
                   "inferred_dose": 1, "unknown_dose": 2, "excluded_count": 0}


def _preservative_product(session):
    """含苯氧乙醇的产品：法规类防腐断言（0.9 高分）+ 一条普通保湿断言作对照。

    防腐断言证据为法规（evidence_level=regulation），命中两条排除规则，
    不得进入指纹维度与 coverage 计分，但 detail 须如实标注。
    """
    reg_ev = Evidence(type=EvidenceType.REGULATION, title="准用防腐剂清单", source="规范", year=2015)
    paper_ev = Evidence(type=EvidenceType.PAPER, title="保湿文献", source="玩具期刊", year=2021)
    pe = Ingredient(inci_name="PHENOXYETHANOL", cn_name="苯氧乙醇")
    ha = Ingredient(inci_name="TOY-HA", cn_name="玩具保湿成分")
    p = Product(name="防腐玩具精华", brand="玩具牌")
    session.add_all([reg_ev, paper_ev, pe, ha, p])
    session.flush()
    session.add_all([
        EfficacyAssertion(ingredient_id=pe.id, efficacy="防腐（准用防腐剂）", evidence_id=reg_ev.id,
                          evidence_level="regulation", evidence_strength=0.9),
        EfficacyAssertion(ingredient_id=ha.id, efficacy="保湿", evidence_id=paper_ev.id,
                          evidence_level="in_vitro", evidence_strength=0.5),
        ProductIngredient(product_id=p.id, ingredient_id=pe.id, position=1),
        ProductIngredient(product_id=p.id, ingredient_id=ha.id, position=2),
    ])
    session.commit()
    return p


def test_fingerprint_excludes_preservative_dimension(session):
    """含苯氧乙醇的产品：指纹无「防腐」维，保湿维正常计分（eff_low None → 因子 1.0）。"""
    p = _preservative_product(session)
    result = compute_fingerprint(session, p.id)
    assert "防腐" not in result["fingerprint"]
    assert result["fingerprint"] == {"保湿": 0.5}


def test_fingerprint_excluded_detail_marked(session):
    """被排除条目仍在 detail：excluded=true + exclude_reason；未排除条目不带 reason。"""
    p = _preservative_product(session)
    result = compute_fingerprint(session, p.id)
    excluded = [d for d in result["detail"] if d.get("excluded")]
    assert len(excluded) == 1
    row = excluded[0]
    assert row["inci_name"] == "PHENOXYETHANOL"
    assert row["efficacy"] == "防腐（准用防腐剂）"
    assert row["exclude_reason"]
    included = [d for d in result["detail"] if not d.get("excluded")]
    assert len(included) == 1
    assert included[0]["efficacy"] == "保湿"
    assert "exclude_reason" not in included[0]
    assert result["coverage"]["excluded_count"] == 1


def test_fingerprint_exclusion_two_branches(session):
    """两条排除规则独立生效：

    ① evidence_level=regulation 的非防腐断言（法规事实不是皮肤功效）；
    ② 非 regulation 的防腐族断言（如体外证据的防腐增效，规则命中「防腐」族）。
    """
    reg_ev = Evidence(type=EvidenceType.REGULATION, title="限用清单", source="规范", year=2015)
    paper_ev = Evidence(type=EvidenceType.PAPER, title="防腐协同文献", source="玩具期刊", year=2021)
    x = Ingredient(inci_name="TOY-X", cn_name="玩具成分X")
    y = Ingredient(inci_name="TOY-Y", cn_name="玩具成分Y")
    p = Product(name="双排除玩具", brand="玩具牌")
    session.add_all([reg_ev, paper_ev, x, y, p])
    session.flush()
    session.add_all([
        EfficacyAssertion(ingredient_id=x.id, efficacy="美白", evidence_id=reg_ev.id,
                          evidence_level="regulation", evidence_strength=0.9),
        EfficacyAssertion(ingredient_id=y.id, efficacy="防腐增效（通过防腐挑战测试）",
                          evidence_id=paper_ev.id,
                          evidence_level="in_vitro", evidence_strength=0.5),
        ProductIngredient(product_id=p.id, ingredient_id=x.id, position=1),
        ProductIngredient(product_id=p.id, ingredient_id=y.id, position=2),
    ])
    session.commit()
    result = compute_fingerprint(session, p.id)
    assert result["fingerprint"] == {}
    assert result["coverage"]["excluded_count"] == 2
    reasons = {d["efficacy"]: d["exclude_reason"] for d in result["detail"]}
    assert "法规" in reasons["美白"]
    assert "防腐" in reasons["防腐增效（通过防腐挑战测试）"]


def test_fingerprint_aggregates_by_canonical(session):
    """不同原文、同 canonical 的断言合为一维；同成分同 canonical 取 max；detail 保留原文。

    - A 两条美白族断言（原文不同）：0.8 与 0.5 → 同成分同 canonical 取 max = 0.8
      （第一条显式写 efficacy_canonical 走列路径，第二条留 NULL 走实时映射路径）
    - B 一条「美白提亮…」：0.6 → 与 A 聚合为同一「美白」维
    指纹：美白 = 0.8 + 0.6 = 1.4
    """
    ev = Evidence(type=EvidenceType.PAPER, title="美白文献", source="玩具期刊", year=2020)
    a = Ingredient(inci_name="TOY-NIA", cn_name="玩具烟酰胺")
    b = Ingredient(inci_name="TOY-AA", cn_name="玩具熊果苷")
    p = Product(name="聚合玩具精华", brand="玩具牌")
    session.add_all([ev, a, b, p])
    session.flush()
    session.add_all([
        EfficacyAssertion(ingredient_id=a.id, efficacy="美白（抑制黑素小体转运）",
                          evidence_id=ev.id, evidence_strength=0.8,
                          efficacy_canonical="美白"),
        EfficacyAssertion(ingredient_id=a.id, efficacy="美白淡斑（黄褐斑）",
                          evidence_id=ev.id, evidence_strength=0.5),
        EfficacyAssertion(ingredient_id=b.id, efficacy="美白提亮（降低黑色素指数）并改善皮肤状态",
                          evidence_id=ev.id, evidence_strength=0.6),
        ProductIngredient(product_id=p.id, ingredient_id=a.id, position=1),
        ProductIngredient(product_id=p.id, ingredient_id=b.id, position=2),
    ])
    session.commit()
    result = compute_fingerprint(session, p.id)
    assert result["fingerprint"] == {"美白": 1.4}
    raw = {d["efficacy"] for d in result["detail"]}
    assert raw == {"美白（抑制黑素小体转运）", "美白淡斑（黄褐斑）",
                   "美白提亮（降低黑色素指数）并改善皮肤状态"}
    assert all(d["efficacy_canonical"] == "美白" for d in result["detail"])


@pytest.fixture()
def client(session):
    _toy_product(session)
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def test_fingerprint_api(client):
    r = client.get("/api/products/1/fingerprint")
    assert r.status_code == 200
    body = r.json()
    assert body["product_id"] == 1
    assert body["fingerprint"] == {"美白": 1.1, "保湿": 0.4}
    assert body["coverage"]["dimensions"] == 2  # 非零维数
    assert body["coverage"]["ingredients_total"] == 3
    assert len(body["detail"]) == 4
    assert {"ingredient_id", "inci_name", "efficacy", "dose_factor", "dose_basis",
            "evidence_strength", "contribution"} <= set(body["detail"][0])


def test_fingerprint_api_404(client):
    r = client.get("/api/products/9999/fingerprint")
    assert r.status_code == 404
