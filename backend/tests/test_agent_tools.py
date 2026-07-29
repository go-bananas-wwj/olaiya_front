"""Agent 工具层单测（总纲 v4.1 §三支柱 4）：6 个确定性工具 + TOOLS 注册表。

玩具数据覆盖：找到 / 找不到 / 多候选排序；无推断、无证据、无宣称的诚实降级；
注册表结构完整（description + parameters JSON Schema）；全部输出 JSON 可序列化。
"""

import json

import pytest

from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.models.product import Product, ProductClaim, ProductIngredient
from app.services.agent_tools import (
    TOOLS,
    tool_dose_check,
    tool_ingredient_evidence,
    tool_product_claims,
    tool_product_lookup,
    tool_similar_products,
    tool_transdermal,
)

TOY_CID_MAP = {
    "NIACINAMIDE": {"status": "ok", "mw": "122.12", "xlogp": 2.0},
}


def _seed(session):
    """玩具数据：3 产品 / 3 成分 / 1 证据 1 断言 / 2 宣称 / 推断浓度（p1、p2 有，p3 无）。"""
    nia = Ingredient(inci_name="NIACINAMIDE", cn_name="烟酰胺")
    nia_complex = Ingredient(inci_name="NIACINAMIDE COMPLEX", cn_name="烟酰胺复合物")
    pan = Ingredient(inci_name="PANTHENOL", cn_name="泛醇")  # 无证据成分
    ev = Evidence(type=EvidenceType.PAPER, title="烟酰胺屏障 RCT", source="测试期刊",
                  year=2014, url="https://example.org/p1", excerpt="2% 烟酰胺改善屏障")
    session.add_all([nia, nia_complex, pan, ev])
    session.flush()
    session.add(EfficacyAssertion(
        ingredient_id=nia.id, efficacy="修护", evidence_id=ev.id,
        effective_conc_low=2.0, effective_conc_high=5.0,
        evidence_level="human_rct", evidence_strength=0.9, efficacy_canonical="修护"))
    p1 = Product(name="玻尿酸精华", brand="甲牌", nmpa_id="沪G妆网备字001")
    p2 = Product(name="玻尿酸精华露", brand="乙牌")
    p3 = Product(name="素颜面霜", brand="丙牌")
    session.add_all([p1, p2, p3])
    session.flush()
    session.add_all([
        ProductClaim(product_id=p1.id, claim="保湿", eval_category="人体功效评价试验",
                     method_name="角质层水分含量测试", metric="皮肤水分含量",
                     result_summary="使用 4 周显著提升", institution="某检测院"),
        ProductClaim(product_id=p1.id, claim="修护", eval_category="消费者使用测试",
                     result_summary="90% 受试者认同"),
    ])
    # p1/p2 共享烟酰胺且均有推断浓度；p3 仅泛醇关联、无推断浓度
    session.add_all([
        ProductIngredient(product_id=p1.id, ingredient_id=nia.id, position=2,
                          conc_low=4.0, conc_high=6.0, conc_confidence=0.8),
        ProductIngredient(product_id=p2.id, ingredient_id=nia.id, position=5,
                          conc_low=1.0, conc_high=3.0, conc_confidence=0.6),
        ProductIngredient(product_id=p3.id, ingredient_id=pan.id, position=1),
    ])
    session.commit()
    return {"nia": nia, "pan": pan, "p1": p1, "p2": p2, "p3": p3}


def _seed_alias(session):
    """别名测试镜像：抗坏血酸/生育酚/苯乙基间苯二酚 + 含抗坏血酸的产品「CE精华」。"""
    aa = Ingredient(inci_name="ASCORBIC ACID", cn_name="抗坏血酸（维生素C）")
    toco = Ingredient(inci_name="TOCOPHEROL", cn_name="生育酚（维生素E）")
    per = Ingredient(inci_name="PHENYLETHYL RESORCINOL", cn_name="苯乙基间苯二酚（377）")
    p = Product(name="CE精华", brand="乙牌")
    session.add_all([aa, toco, per, p])
    session.flush()
    session.add(ProductIngredient(product_id=p.id, ingredient_id=aa.id, position=3))
    session.commit()
    return {"aa": aa, "toco": toco, "per": per, "p": p}


# ---------- tool_product_lookup ----------

class TestProductLookup:
    def test_exact_match_single(self, session):
        d = _seed(session)
        r = tool_product_lookup(session, "素颜面霜")
        assert r["found"] is True and r["exact"] is True
        assert [p["id"] for p in r["products"]] == [d["p3"].id]

    def test_multi_candidates_sorted_by_match(self, session):
        d = _seed(session)
        r = tool_product_lookup(session, "玻尿酸精华")
        assert r["found"] is True and r["exact"] is True
        # 精确匹配排最前；「玻尿酸精华露」为次优候选
        assert [p["id"] for p in r["products"]] == [d["p1"].id, d["p2"].id]
        top = r["products"][0]
        assert top["nmpa_id"] == "沪G妆网备字001"
        assert top["claim_count"] == 2 and top["ingredient_count"] == 1

    def test_substring_no_exact(self, session):
        d = _seed(session)
        r = tool_product_lookup(session, "精华")
        assert r["found"] is True and r["exact"] is False
        # 同名级候选短名优先（更接近查询）
        assert [p["id"] for p in r["products"]] == [d["p1"].id, d["p2"].id]

    def test_not_found(self, session):
        _seed(session)
        r = tool_product_lookup(session, "不存在的产品")
        assert r == {"found": False, "products": [], "exact": False}

    def test_empty_query(self, session):
        r = tool_product_lookup(session, "  ")
        assert r["found"] is False and r["products"] == []

    def test_ingredient_alias_lookup(self, session):
        """名称无命中时经成分别名索引：「VC」找到含抗坏血酸的产品（同一用户语言）。"""
        _seed_alias(session)
        r = tool_product_lookup(session, "VC")
        assert r["found"] is True and r["exact"] is False
        assert [p["name"] for p in r["products"]] == ["CE精华"]
        top = r["products"][0]
        assert top["matched_via"] == "ingredient"
        assert top["matched_ingredient"]["inci_name"] == "ASCORBIC ACID"

    def test_name_hits_not_polluted_by_alias(self, session):
        """名称有命中时不追加成分索引候选（exact 语义不变）。"""
        d = _seed(session)
        r = tool_product_lookup(session, "玻尿酸精华")
        assert [p["id"] for p in r["products"]] == [d["p1"].id, d["p2"].id]
        assert all(p["matched_via"] == "name" for p in r["products"])


# ---------- tool_product_claims ----------

class TestProductClaims:
    def test_claims_returned_in_order(self, session):
        d = _seed(session)
        r = tool_product_claims(session, d["p1"].id)
        assert r["product_id"] == d["p1"].id
        assert [c["claim"] for c in r["claims"]] == ["保湿", "修护"]
        first = r["claims"][0]
        assert first["eval_category"] == "人体功效评价试验"
        assert first["method_name"] == "角质层水分含量测试"
        assert first["metric"] == "皮肤水分含量"
        assert first["result_summary"] == "使用 4 周显著提升"
        assert first["institution"] == "某检测院"
        # 未提供的字段如实为空，不编造
        assert r["claims"][1]["eval_category"] == "消费者使用测试"
        assert r["claims"][1]["method_name"] is None

    def test_no_claims_empty_list(self, session):
        d = _seed(session)
        r = tool_product_claims(session, d["p2"].id)
        assert r["claims"] == []

    def test_unknown_product_empty_list(self, session):
        r = tool_product_claims(session, 999)
        assert r == {"product_id": 999, "claims": []}


# ---------- tool_ingredient_evidence ----------

class TestIngredientEvidence:
    def test_found_by_cn_name(self, session):
        d = _seed(session)
        r = tool_ingredient_evidence(session, "烟酰胺")
        assert r["found"] is True
        assert r["ingredient"]["id"] == d["nia"].id
        a = r["assertions"][0]
        assert a["efficacy"] == "修护" and a["efficacy_canonical"] == "修护"
        assert a["eff_low"] == 2.0 and a["eff_high"] == 5.0
        assert a["evidence_level"] == "human_rct" and a["evidence_strength"] == 0.9
        assert a["evidence"]["type"] == "paper"
        assert a["evidence"]["title"] == "烟酰胺屏障 RCT"
        assert a["evidence"]["url"] == "https://example.org/p1"
        assert r["note"] is None

    def test_found_by_inci_substring(self, session):
        _seed(session)
        r = tool_ingredient_evidence(session, "panthenol")
        assert r["found"] is True and r["ingredient"]["cn_name"] == "泛醇"

    def test_exact_beats_multi_candidates(self, session):
        """多候选时精确匹配优先（烟酰胺 精确 > 烟酰胺复合物 子串）。"""
        d = _seed(session)
        r = tool_ingredient_evidence(session, "烟酰胺")
        assert r["ingredient"]["id"] == d["nia"].id

    def test_no_assertions_note(self, session):
        _seed(session)
        r = tool_ingredient_evidence(session, "泛醇")
        assert r["found"] is True and r["assertions"] == []
        assert r["note"] == "该成分暂无证据记录"

    def test_not_found(self, session):
        _seed(session)
        r = tool_ingredient_evidence(session, "查无此成分")
        assert r["found"] is False and r["ingredient"] is None and r["assertions"] == []
        assert "查无此成分" in r["note"]

    def test_alias_vc_hits_ascorbic_not_tocopherol(self, session):
        """别名直达：VC → 抗坏血酸（非生育酚）。"""
        _seed_alias(session)
        r = tool_ingredient_evidence(session, "VC")
        assert r["found"] is True and r["ingredient"]["inci_name"] == "ASCORBIC ACID"

    def test_alias_377_hits_phenylethyl_resorcinol(self, session):
        _seed_alias(session)
        r = tool_ingredient_evidence(session, "377")
        assert r["found"] is True and r["ingredient"]["cn_name"] == "苯乙基间苯二酚（377）"

    def test_alias_unregistered_inci_falls_back_to_fuzzy(self, session):
        """别名指向的 INCI 未登记时落回模糊匹配（如「…（377）」命名的 stub 成分）。"""
        stub = Ingredient(inci_name="苯乙基间苯二酚（377）", cn_name="苯乙基间苯二酚（377）")
        session.add(stub)
        session.commit()
        r = tool_ingredient_evidence(session, "377")
        assert r["found"] is True and r["ingredient"]["id"] == stub.id


# ---------- tool_dose_check ----------

class TestDoseCheck:
    def test_inferred_with_verdicts(self, session):
        d = _seed(session)
        r = tool_dose_check(session, d["p1"].id)
        assert r["inferred"] is True
        est = r["estimates"][0]
        assert est["inci_name"] == "NIACINAMIDE"
        assert est["low"] == 4.0 and est["high"] == 6.0
        # 区间整体过起效线 2.0 → effective
        assert est["dose"][0]["verdict"] == "effective"
        assert est["dose"][0]["efficacy"] == "修护"

    def test_not_inferred(self, session):
        d = _seed(session)
        r = tool_dose_check(session, d["p3"].id)
        assert r["inferred"] is False and r["reason"]

    def test_unknown_product_not_inferred(self, session):
        r = tool_dose_check(session, 999)
        assert r["inferred"] is False


# ---------- tool_transdermal ----------

class TestTransdermal:
    def test_cn_name_resolved_to_inci(self, session):
        _seed(session)
        r = tool_transdermal(session, "烟酰胺", cid_map=TOY_CID_MAP)
        assert r["ingredient"]["inci_name"] == "NIACINAMIDE"
        assert r["inci_name"] == "NIACINAMIDE"
        # MW 122.12 ≤ 500 且 logP=2.0 在最优窗口 → easy
        assert r["verdict"] == "easy"
        assert r["mw"] == 122.12 and r["xlogp"] == 2.0
        assert r["logkp"] == round(-2.7 + 0.71 * 2.0 - 0.0061 * 122.12, 4)
        assert r["disclaimer"]

    def test_unknown_name_not_applicable(self, session):
        _seed(session)
        r = tool_transdermal(session, "神秘提取物", cid_map={})
        assert r["ingredient"] is None
        assert r["verdict"] == "not_applicable" and r["reason"]

    def test_default_cid_map_loaded(self, session):
        """不传 cid_map 时模块内加载 data/seed/cid_map.json（腺苷 MW 267 域内）。"""
        _seed(session)
        r = tool_transdermal(session, "ADENOSINE")
        assert r["mw"] == 267.24
        assert r["verdict"] in ("easy", "medium", "hard", "not_applicable")
        assert r["disclaimer"]


# ---------- tool_similar_products ----------

class TestSimilarProducts:
    def test_l1_l3_hit_and_l2_available(self, session):
        d = _seed(session)
        r = tool_similar_products(session, d["p1"].id, k=5)
        assert r["product_id"] == d["p1"].id and r["found"] is True
        # L1：p1/p2 成分集均为 {烟酰胺} → Jaccard 1/1
        assert [x["id"] for x in r["l1"]] == [d["p2"].id]
        assert r["l1"][0]["shared"] == 1 and r["l1"][0]["union"] == 1
        assert r["l1"][0]["score"] == 1.0
        # L2：双方均有推断浓度 → available
        assert r["l2"]["available"] is True
        assert [x["id"] for x in r["l2"]["similar"]] == [d["p2"].id]
        # L3：功效指纹共享「修护」维
        assert [x["id"] for x in r["l3"]] == [d["p2"].id]
        assert r["l3"][0]["top_shared_dims"] == ["修护"]

    def test_l2_unavailable_without_inference(self, session):
        d = _seed(session)
        r = tool_similar_products(session, d["p3"].id)
        assert r["l2"]["available"] is False and r["l2"]["reason"]

    def test_unknown_product(self, session):
        r = tool_similar_products(session, 999)
        assert r["found"] is False
        assert r["l1"] == [] and r["l3"] == []
        assert r["l2"]["available"] is False


# ---------- TOOLS 注册表 ----------

class TestToolsRegistry:
    EXPECTED = {"product_lookup", "product_claims", "ingredient_evidence",
                "dose_check", "transdermal", "similar_products"}

    def test_all_tools_registered(self):
        assert set(TOOLS) == self.EXPECTED

    def test_registry_structure(self):
        for name, spec in TOOLS.items():
            assert callable(spec["fn"]), name
            assert spec["fn"].__name__ == f"tool_{name}", name
            assert isinstance(spec["description"], str) and spec["description"], name
            params = spec["parameters"]
            assert params["type"] == "object", name
            assert isinstance(params["properties"], dict) and params["properties"], name
            # required 中的参数必须都在 properties 里；session 由调用方注入，不进 schema
            assert set(params.get("required", [])) <= set(params["properties"]), name
            assert "session" not in params["properties"], name


# ---------- JSON 可序列化 ----------

def test_all_outputs_json_serializable(session):
    d = _seed(session)
    outputs = [
        tool_product_lookup(session, "精华"),
        tool_product_lookup(session, "不存在"),
        tool_product_claims(session, d["p1"].id),
        tool_ingredient_evidence(session, "烟酰胺"),
        tool_ingredient_evidence(session, "泛醇"),
        tool_ingredient_evidence(session, "查无此成分"),
        tool_dose_check(session, d["p1"].id),
        tool_dose_check(session, d["p3"].id),
        tool_transdermal(session, "烟酰胺", cid_map=TOY_CID_MAP),
        tool_transdermal(session, "神秘提取物", cid_map={}),
        tool_similar_products(session, d["p1"].id),
        tool_similar_products(session, d["p3"].id),
        tool_similar_products(session, 999),
    ]
    for out in outputs:
        # 不抛异常且可 round-trip
        assert json.loads(json.dumps(out, ensure_ascii=False)) == out


def test_registry_itself_json_serializable():
    """注册表的 description/parameters 供 LLM function calling 消费，必须可序列化。"""
    meta = {name: {"description": s["description"], "parameters": s["parameters"]}
            for name, s in TOOLS.items()}
    assert json.loads(json.dumps(meta, ensure_ascii=False)) == meta
