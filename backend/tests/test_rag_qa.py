"""prompt RAG 基线测试（总纲模型层阶段 1）：证据包组装 + schema 强制引用 + 包外引用检测。

检索/组装/引用解析均为确定性逻辑（LLM 无关），直接断言；gateway 全部用假件，
不依赖真实 LLM 服务。种子数据用例验证「烟酰胺真的能美白吗？」命中烟酰胺断言。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_db, get_llm_gateway
from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.models.product import Product, ProductClaim
from app.services.llm_gateway import LLMUnavailableError
from app.services.rag_qa import SYSTEM_PROMPT, answer_question, build_evidence_pack
from data.loaders.seed_loader import load_seed


class _FakeGateway:
    """记录 chat 调用消息，按构造时给定内容/异常返回；channel 模拟 LLMGateway。"""

    def __init__(self, answer="回答", exc=None, channel="local"):
        self.calls = []
        self._answer = answer
        self._exc = exc
        self.channel = channel

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        if self._exc is not None:
            raise self._exc
        return self._answer


def _seed_toy(session):
    """玩具数据：烟酰胺 2 断言（2 证据）、泛醇无断言、产品「烟酰胺精华」2 宣称。"""
    nia = Ingredient(inci_name="NIACINAMIDE", cn_name="烟酰胺")
    pan = Ingredient(inci_name="PANTHENOL", cn_name="泛醇")
    ev1 = Evidence(type=EvidenceType.PAPER, title="烟酰胺美白 RCT", source="测试期刊A",
                   year=2002, url="https://pubmed.ncbi.nlm.nih.gov/12100180/",
                   excerpt="5% 烟酰胺淡化色斑")
    ev2 = Evidence(type=EvidenceType.PAPER, title="烟酰胺屏障研究", source="测试期刊B",
                   year=2014, url="https://example.org/p2", excerpt="2% 烟酰胺改善屏障")
    session.add_all([nia, pan, ev1, ev2])
    session.flush()
    session.add_all([
        EfficacyAssertion(ingredient_id=nia.id, efficacy="美白", evidence_id=ev1.id,
                          effective_conc_low=2.0, effective_conc_high=5.0,
                          evidence_level="human_rct", evidence_strength=0.9,
                          efficacy_canonical="美白", note="临床试验常用浓度 2%-5%"),
        EfficacyAssertion(ingredient_id=nia.id, efficacy="修护", evidence_id=ev2.id,
                          effective_conc_low=2.0, effective_conc_high=None,
                          evidence_level="in_vitro", evidence_strength=0.3,
                          efficacy_canonical="修护"),
    ])
    p = Product(name="烟酰胺精华", brand="甲牌")
    session.add(p)
    session.flush()
    session.add_all([
        ProductClaim(product_id=p.id, claim="保湿", eval_category="人体功效评价试验",
                     result_summary="使用 4 周显著提升", institution="某检测院"),
        ProductClaim(product_id=p.id, claim="提亮", eval_category="消费者使用测试",
                     result_summary="90% 受试者认同"),
    ])
    session.commit()
    return {"nia": nia, "pan": pan, "p": p}


def _seed_alias_toy(session):
    """镜像真实库命名的别名数据：VC/377/维A/蓝铜胜肽各有 1 断言，另设生育酚（维生素E）防误命中。"""
    aa = Ingredient(inci_name="ASCORBIC ACID", cn_name="抗坏血酸（维生素C）")
    toco = Ingredient(inci_name="TOCOPHEROL", cn_name="生育酚（维生素E）")
    per = Ingredient(inci_name="PHENYLETHYL RESORCINOL", cn_name="苯乙基间苯二酚（377）")
    ret = Ingredient(inci_name="RETINOL", cn_name="视黄醇")
    ghk = Ingredient(inci_name="COPPER TRIPEPTIDE-1", cn_name="铜三肽-1")
    ings = {"aa": aa, "toco": toco, "per": per, "ret": ret, "ghk": ghk}
    session.add_all(ings.values())
    session.flush()
    for n, ing in enumerate(ings.values(), start=1):
        ev = Evidence(type=EvidenceType.PAPER, title=f"{ing.cn_name}研究", source="测试期刊",
                      year=2020, url=f"https://example.org/a{n}")
        session.add(ev)
        session.flush()
        session.add(EfficacyAssertion(ingredient_id=ing.id, efficacy="美白", evidence_id=ev.id,
                                      effective_conc_low=1.0, effective_conc_high=2.0))
    session.commit()
    return ings


# ---------- SYSTEM_PROMPT ----------

def test_system_prompt_pins_citation_rules():
    """铁律入 prompt：只根据证据回答、句尾 [n] 引用、证据不足明说、浓度带估计语义。"""
    assert "证据材料" in SYSTEM_PROMPT
    assert "[1][2]" in SYSTEM_PROMPT
    assert "证据不足，无法判定" in SYSTEM_PROMPT
    assert "估计" in SYSTEM_PROMPT


# ---------- build_evidence_pack ----------

class TestBuildEvidencePack:
    def test_niacinamide_question_hits_assertion_on_seed(self, session):
        """真实种子：烟酰胺问题命中烟酰胺断言，编号连续，文本带证据链要素。"""
        load_seed(session)
        session.commit()
        pack = build_evidence_pack(session, "烟酰胺真的能美白吗？")
        items = pack["items"]
        assert items, "种子里的烟酰胺断言必须命中"
        assert [it["id"] for it in items] == list(range(1, len(items) + 1))
        first = items[0]
        assert first["kind"] == "assertion"
        assert "烟酰胺" in first["text"] and "美白" in first["text"]
        assert "起效浓度 2-5%" in first["text"]
        assert "12100180" in first["text"]  # PMID 在证据 URL 中

    def test_assertions_then_claims_continuous_numbering(self, session):
        _seed_toy(session)
        pack = build_evidence_pack(session, "烟酰胺精华里的烟酰胺有用吗")
        items = pack["items"]
        # 2 断言 + 2 宣称，编号连续 1..4，断言在前
        assert [it["id"] for it in items] == [1, 2, 3, 4]
        assert [it["kind"] for it in items] == ["assertion", "assertion", "claim", "claim"]
        assert "美白" in items[0]["text"] and "烟酰胺美白 RCT" in items[0]["text"]
        assert "测试期刊A" in items[0]["text"] and "2002" in items[0]["text"]
        # 弱证据断言如实带 note 之外的结构化层级信息
        assert "in_vitro" in items[1]["text"]
        # 产品宣称摘要含评价类别与结果
        assert "烟酰胺精华" in items[2]["text"] and "保湿" in items[2]["text"]
        assert "人体功效评价试验" in items[2]["text"]

    def test_max_items_truncation(self, session):
        _seed_toy(session)
        pack = build_evidence_pack(session, "烟酰胺精华里的烟酰胺有用吗", max_items=2)
        items = pack["items"]
        assert len(items) == 2
        assert [it["id"] for it in items] == [1, 2]  # 截断后编号仍连续

    def test_no_hit_empty_items(self, session):
        _seed_toy(session)
        pack = build_evidence_pack(session, "今天天气怎么样")
        assert pack["items"] == []

    def test_ingredient_without_assertion_contributes_nothing(self, session):
        """命中无断言成分 → 不产生证据项（不编造），但 ingredients_hit 如实记录。"""
        _seed_toy(session)
        pack = build_evidence_pack(session, "泛醇有什么用")
        assert pack["items"] == []
        assert [i["cn_name"] for i in pack["ingredients_hit"]] == ["泛醇"]

    def test_exact_match_prefers_specific_ingredient(self, session):
        """问题同时含「烟酰胺」时，不被更短的泛名干扰；命中集合含烟酰胺。"""
        _seed_toy(session)
        pack = build_evidence_pack(session, "烟酰胺真的能美白吗")
        names = [i["cn_name"] for i in pack["ingredients_hit"]]
        assert "烟酰胺" in names

    def test_all_items_json_serializable(self, session):
        import json
        _seed_toy(session)
        pack = build_evidence_pack(session, "烟酰胺精华里的烟酰胺有用吗")
        assert json.loads(json.dumps(pack, ensure_ascii=False)) == pack


# ---------- 别名召回（04a 审查修复） ----------

class TestAliasRecall:
    """俗名/代号经别名表直达 INCI；别名命中优先于子串命中与分词兜底。"""

    def test_vc_hits_ascorbic_acid(self, session):
        _seed_alias_toy(session)
        pack = build_evidence_pack(session, "VC真的能美白吗？")
        assert pack["ingredients_hit"][0]["inci_name"] == "ASCORBIC ACID"
        assert pack["items"] and "抗坏血酸" in pack["items"][0]["text"]

    def test_vitamin_c_hits_ascorbic_not_tocopherol(self, session):
        """「维生素C」必须命中抗坏血酸而非生育酚（别名优先，防长名/分词截胡）。"""
        _seed_alias_toy(session)
        pack = build_evidence_pack(session, "维生素C真的能美白吗？")
        assert pack["ingredients_hit"][0]["inci_name"] == "ASCORBIC ACID"
        assert all(i["inci_name"] != "TOCOPHEROL" for i in pack["ingredients_hit"])
        assert "抗坏血酸" in pack["items"][0]["text"]
        assert all("生育酚" not in it["text"] for it in pack["items"])

    def test_377_hits_phenylethyl_resorcinol(self, session):
        _seed_alias_toy(session)
        pack = build_evidence_pack(session, "377能美白吗？")
        assert pack["ingredients_hit"][0]["inci_name"] == "PHENYLETHYL RESORCINOL"
        assert pack["items"] and "苯乙基间苯二酚" in pack["items"][0]["text"]

    def test_retinol_aliases(self, session):
        _seed_alias_toy(session)
        for q in ("维A真的能抗老吗？", "A醇真的能抗老吗？"):
            pack = build_evidence_pack(session, q)
            assert pack["ingredients_hit"][0]["inci_name"] == "RETINOL", q
            assert pack["items"], q

    def test_blue_copper_peptide_hits_copper_tripeptide(self, session):
        _seed_alias_toy(session)
        pack = build_evidence_pack(session, "蓝铜胜肽修护有用吗")
        assert pack["ingredients_hit"][0]["inci_name"] == "COPPER TRIPEPTIDE-1"
        assert pack["items"] and "铜三肽-1" in pack["items"][0]["text"]

    def test_plain_name_matching_not_regressed(self, session):
        """原匹配行为不回归：烟酰胺中文子串、NIACINAMIDE 英文照常命中。"""
        _seed_toy(session)
        pack = build_evidence_pack(session, "烟酰胺真的能美白吗")
        assert pack["ingredients_hit"][0]["cn_name"] == "烟酰胺"
        assert "美白" in pack["items"][0]["text"]
        pack = build_evidence_pack(session, "NIACINAMIDE 有用吗")
        assert pack["ingredients_hit"][0]["inci_name"] == "NIACINAMIDE"


# ---------- 退化区间显示 ----------

def test_degenerate_interval_shows_single_value(session):
    """low==high 退化区间输出单值「起效浓度 5%」，不输出「5-5%」。"""
    ing = Ingredient(inci_name="DUMMY ACID", cn_name="仿真酸")
    ev = Evidence(type=EvidenceType.PAPER, title="退化区间研究", source="测试期刊",
                  year=2021, url="https://example.org/d1")
    session.add_all([ing, ev])
    session.flush()
    session.add(EfficacyAssertion(ingredient_id=ing.id, efficacy="保湿", evidence_id=ev.id,
                                  effective_conc_low=5.0, effective_conc_high=5.0))
    session.commit()
    pack = build_evidence_pack(session, "仿真酸有用吗")
    text = pack["items"][0]["text"]
    assert "起效浓度 5%" in text
    assert "5-5" not in text


# ---------- answer_question ----------

class TestAnswerQuestion:
    def test_citations_parsed_and_hallucinated_detected(self, session):
        """答案带 [1][2] 包内引用 + [9] 包外编号：如实解析与检出，不删改答案。"""
        _seed_toy(session)
        fake = _FakeGateway("烟酰胺可抑制黑素小体转运[1][2]，浓度为估计值。[9] 暂无依据。")
        r = answer_question(session, fake, "烟酰胺精华里的烟酰胺有用吗")
        assert r["citations_used"] == [1, 2, 9]
        assert r["hallucinated_citations"] == [9]
        assert r["answer"].startswith("烟酰胺可抑制黑素小体转运")
        assert r["channel"] == "local"
        assert [it["id"] for it in r["evidence_pack"]] == [1, 2, 3, 4]

    def test_no_citation_answer_clean(self, session):
        _seed_toy(session)
        fake = _FakeGateway("证据不足，无法判定")
        r = answer_question(session, fake, "烟酰胺精华里的烟酰胺有用吗")
        assert r["citations_used"] == [] and r["hallucinated_citations"] == []

    def test_all_citations_within_pack_no_hallucination(self, session):
        _seed_toy(session)
        fake = _FakeGateway("宣称保湿有试验支撑[3]，成分美白有文献[1]。")
        r = answer_question(session, fake, "烟酰胺精华里的烟酰胺有用吗")
        assert r["citations_used"] == [1, 3]
        assert r["hallucinated_citations"] == []

    def test_messages_structure(self, session):
        """chat 收到 [system, user]：system 为铁律 prompt，user 含编号证据材料与问题。"""
        _seed_toy(session)
        fake = _FakeGateway("[1]")
        answer_question(session, fake, "烟酰胺精华里的烟酰胺有用吗")
        (messages,) = fake.calls
        assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
        user = messages[1]["content"]
        assert messages[1]["role"] == "user"
        assert "[1]" in user and "烟酰胺美白 RCT" in user
        assert "烟酰胺精华里的烟酰胺有用吗" in user

    def test_empty_pack_user_message_marks_no_evidence(self, session):
        _seed_toy(session)
        fake = _FakeGateway("证据不足，无法判定")
        r = answer_question(session, fake, "今天天气怎么样")
        assert r["evidence_pack"] == []
        (messages,) = fake.calls
        assert "未检索到" in messages[1]["content"]


# ---------- POST /api/chat ----------

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


def _override_gateway(gw):
    app.dependency_overrides[get_llm_gateway] = lambda: gw


class TestChatApi:
    def test_empty_question_422(self, client):
        assert client.post("/api/chat", json={"question": ""}).status_code == 422
        assert client.post("/api/chat", json={"question": "   "}).status_code == 422

    def test_missing_question_422(self, client):
        assert client.post("/api/chat", json={}).status_code == 422

    def test_structure_and_citations(self, client):
        gw = _FakeGateway("烟酰胺美白有文献支撑[1]，浓度为估计值。[9]")
        _override_gateway(gw)
        r = client.post("/api/chat", json={"question": "烟酰胺真的能美白吗？"})
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {"answer", "evidence_pack", "citations_used",
                             "hallucinated_citations", "channel"}
        assert body["citations_used"] == [1, 9]
        assert body["hallucinated_citations"] == [9]
        assert body["channel"] == "local"
        assert body["evidence_pack"][0]["kind"] == "assertion"
        assert "烟酰胺" in body["evidence_pack"][0]["text"]

    def test_llm_unavailable_503(self, client):
        gw = _FakeGateway(exc=LLMUnavailableError("local 通道调用失败: refused"))
        _override_gateway(gw)
        r = client.post("/api/chat", json={"question": "烟酰胺真的能美白吗？"})
        assert r.status_code == 503
        assert "local" in r.json()["detail"]
