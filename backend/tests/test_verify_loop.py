"""生成者-验证者非对称校验循环测试（总纲模型层阶段 2，RARR 式）。

拆句/引用提取/证据子集组装为确定性逻辑直接断言；gateway 用两阶段假件
（按 system prompt 区分生成/核验调用），不依赖真实 LLM 服务。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_db, get_llm_gateway
from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.services.rag_qa import SYSTEM_PROMPT, build_evidence_pack
from app.services.verify_loop import VERIFY_PROMPT, split_claims, verify_answer
from data.loaders.seed_loader import load_seed


class _StagedGateway:
    """两阶段假网关：system 为 VERIFY_PROMPT 的调用是核验，其余是生成（重写）。

    answers / verifies 各自按队列依次返回；队列只剩一个时重复返回它，
    方便表达「核验永远不通过」类场景。调用消息分别记入 gen_calls / verify_calls。
    """

    def __init__(self, answers=(), verifies=(), channel="local"):
        self._answers = list(answers)
        self._verifies = list(verifies)
        self.gen_calls: list[list[dict]] = []
        self.verify_calls: list[list[dict]] = []
        self.channel = channel

    def chat(self, messages, **kwargs):
        if messages[0]["content"] == VERIFY_PROMPT:
            self.verify_calls.append(messages)
            if len(self._verifies) > 1:
                return self._verifies.pop(0)
            return self._verifies[0]
        self.gen_calls.append(messages)
        if len(self._answers) > 1:
            return self._answers.pop(0)
        return self._answers[0]


def _seed_toy(session):
    """玩具数据：烟酰胺 2 断言（2 证据）。"""
    nia = Ingredient(inci_name="NIACINAMIDE", cn_name="烟酰胺")
    ev1 = Evidence(type=EvidenceType.PAPER, title="烟酰胺美白 RCT", source="测试期刊A",
                   year=2002, url="https://pubmed.ncbi.nlm.nih.gov/12100180/",
                   excerpt="5% 烟酰胺淡化色斑")
    ev2 = Evidence(type=EvidenceType.PAPER, title="烟酰胺屏障研究", source="测试期刊B",
                   year=2014, url="https://example.org/p2", excerpt="2% 烟酰胺改善屏障")
    session.add_all([nia, ev1, ev2])
    session.flush()
    session.add_all([
        EfficacyAssertion(ingredient_id=nia.id, efficacy="美白", evidence_id=ev1.id,
                          effective_conc_low=2.0, effective_conc_high=5.0,
                          evidence_level="human_rct"),
        EfficacyAssertion(ingredient_id=nia.id, efficacy="修护", evidence_id=ev2.id,
                          effective_conc_low=2.0, evidence_level="in_vitro"),
    ])
    session.commit()
    return nia


def _rag_result(session, answer: str, question="烟酰胺真的能美白吗？") -> dict:
    """手动组装 rag_result（跳过生成阶段，答案由用例直接给定）。"""
    pack = build_evidence_pack(session, question)
    return {"answer": answer, "evidence_pack": pack["items"],
            "citations_used": [], "hallucinated_citations": [], "channel": "fake"}


# ---------- VERIFY_PROMPT ----------

def test_verify_prompt_pins_json_schema():
    """核验 prompt 钉死输出契约：只回答 JSON，supported + reason，功效结论须有出处。"""
    assert "supported" in VERIFY_PROMPT
    assert "reason" in VERIFY_PROMPT
    assert "JSON" in VERIFY_PROMPT
    assert "出处" in VERIFY_PROMPT


# ---------- split_claims ----------

class TestSplitClaims:
    def test_keeps_only_sentences_with_citations(self):
        """无引用的过渡句不核验，只保留含 [n] 的句子。"""
        answer = "烟酰胺能美白[1]。这是一个过渡句。泛醇能保湿[2]。"
        assert split_claims(answer) == ["烟酰胺能美白[1]", "泛醇能保湿[2]"]

    def test_splits_on_semicolon(self):
        answer = "烟酰胺能美白[1]；无引用分句；泛醇能保湿[2]。"
        assert split_claims(answer) == ["烟酰胺能美白[1]", "泛醇能保湿[2]"]

    def test_no_citation_returns_empty(self):
        assert split_claims("证据不足，无法判定。") == []

    def test_strips_whitespace(self):
        assert split_claims("烟酰胺能美白[1] 。  泛醇保湿[2]。") == ["烟酰胺能美白[1]", "泛醇保湿[2]"]


# ---------- verify_answer ----------

class TestVerifyAnswer:
    def test_all_pass_single_round(self, session):
        """全部通过一轮即终：rounds=1，不重写，final_answer 原样。"""
        _seed_toy(session)
        answer = "烟酰胺美白有文献支持[1]。"
        gw = _StagedGateway(verifies=['{"supported": true, "reason": "证据[1]直接支持"}'])
        r = verify_answer(session, gw, "烟酰胺真的能美白吗？", _rag_result(session, answer))
        assert r["rounds"] == 1
        assert r["rewritten"] is False
        assert r["final_answer"] == answer
        assert len(r["verification"]) == 1
        v = r["verification"][0]
        assert v["claim"] == "烟酰胺美白有文献支持[1]"
        assert v["supported"] is True
        assert v["reason"] == "证据[1]直接支持"
        assert v["citations"] == [1]
        assert len(gw.verify_calls) == 1
        assert gw.gen_calls == []  # 一轮即过，不触发重写

    def test_verify_receives_only_cited_evidence_subset(self, session):
        """逐句核验只带该句引用编号对应的证据子集（而非全包），控制 token。"""
        _seed_toy(session)
        gw = _StagedGateway(verifies=['{"supported": true, "reason": "ok"}'])
        verify_answer(session, gw, "烟酰胺真的能美白吗？",
                      _rag_result(session, "烟酰胺美白有文献支持[1]。"))
        (messages,) = gw.verify_calls
        assert messages[0] == {"role": "system", "content": VERIFY_PROMPT}
        user = messages[1]["content"]
        assert "[1]" in user and "烟酰胺美白 RCT" in user  # 引用的 [1] 在子集中
        assert "烟酰胺屏障研究" not in user  # 未引用的 [2] 不进子集
        assert "【陈述】烟酰胺美白有文献支持[1]" in user

    def test_failed_claim_triggers_rewrite_with_feedback(self, session):
        """第一句不通过 → 把未通过陈述与原因反馈给生成者重写一轮，重验通过则终。"""
        _seed_toy(session)
        initial = "烟酰胺能美白祛斑[1]。"
        rewritten = "修正后：烟酰胺美白有文献支持[1]。"
        gw = _StagedGateway(
            answers=[rewritten],
            verifies=['{"supported": false, "reason": "证据未提及祛斑"}',
                      '{"supported": true, "reason": "有出处"}'],
        )
        r = verify_answer(session, gw, "烟酰胺真的能美白吗？", _rag_result(session, initial))
        assert r["rewritten"] is True
        assert r["rounds"] == 2
        assert r["final_answer"] == rewritten
        assert [v["supported"] for v in r["verification"]] == [True]
        # 验证 mock 收到了带错误反馈的修正请求
        assert len(gw.gen_calls) == 1
        feedback = gw.gen_calls[0][1]["content"]
        assert gw.gen_calls[0][0]["content"] == SYSTEM_PROMPT  # 重写仍受铁律约束
        assert "未通过核验" in feedback
        assert "烟酰胺能美白祛斑[1]" in feedback
        assert "证据未提及祛斑" in feedback
        assert "烟酰胺美白 RCT" in feedback  # 重写仍带证据材料

    def test_two_rounds_fail_appends_warning_mark(self, session):
        """两轮不过：final_answer 保留原样，对应句尾追加 ⚠️，verification 如实记录。"""
        _seed_toy(session)
        rewritten = "烟酰胺依然能祛斑[1]。"
        gw = _StagedGateway(
            answers=[rewritten],
            verifies=['{"supported": false, "reason": "证据未提及祛斑"}'],  # 永远不过
        )
        r = verify_answer(session, gw, "烟酰胺真的能美白吗？",
                          _rag_result(session, "烟酰胺能祛斑[1]。"))
        assert r["rounds"] == 2
        assert r["rewritten"] is True
        assert r["final_answer"] == "烟酰胺依然能祛斑[1]⚠️。"
        assert [v["supported"] for v in r["verification"]] == [False]
        assert r["verification"][0]["reason"] == "证据未提及祛斑"
        assert len(gw.verify_calls) == 2
        assert len(gw.gen_calls) == 1  # 只重写一轮（rounds 达到 max_rounds 即停）

    def test_answer_without_citations_not_verified(self, session):
        """无引用句不核验：不发起核验调用，不重写，原样返回。"""
        _seed_toy(session)
        answer = "证据不足，无法判定。"
        gw = _StagedGateway(verifies=['{"supported": true, "reason": "ok"}'])
        r = verify_answer(session, gw, "烟酰胺真的能美白吗？", _rag_result(session, answer))
        assert r["rounds"] == 0
        assert r["rewritten"] is False
        assert r["final_answer"] == answer
        assert r["verification"] == []
        assert gw.verify_calls == [] and gw.gen_calls == []

    def test_unparseable_verify_reply_counts_as_failed(self, session):
        """核验回复无法解析为 JSON → 按不通过处理并如实注明，触发重写与 ⚠️。"""
        _seed_toy(session)
        gw = _StagedGateway(answers=["烟酰胺美白[1]。"], verifies=["这不是 JSON"])
        r = verify_answer(session, gw, "烟酰胺真的能美白吗？",
                          _rag_result(session, "烟酰胺美白[1]。"))
        assert r["rounds"] == 2
        assert r["verification"][-1]["supported"] is False
        assert "解析失败" in r["verification"][-1]["reason"]
        assert "⚠️" in r["final_answer"]

    def test_hallucinated_citation_gets_empty_evidence_subset(self, session):
        """包外引用编号无证据可附：证据子集如实标注「不存在」，交由核验员判不通过。"""
        _seed_toy(session)
        gw = _StagedGateway(
            answers=["烟酰胺美白有文献支持[1]。"],
            verifies=['{"supported": false, "reason": "无证据"}',
                      '{"supported": true, "reason": "有出处"}'],
        )
        r = verify_answer(session, gw, "烟酰胺真的能美白吗？",
                          _rag_result(session, "烟酰胺能美白[9]。"))
        user = gw.verify_calls[0][1]["content"]
        assert "在证据包中不存在" in user
        assert "烟酰胺美白 RCT" not in user
        # verification 记录最后一轮（重写后）的核验；首轮的 [9] 判定体现在核验请求里
        assert r["verification"][0]["citations"] == [1]


# ---------- POST /api/chat 接入 ----------

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


class TestChatVerifyApi:
    def test_verify_false_keeps_original_response(self, client):
        """verify=false 走原逻辑：无 verification 字段，只调一次生成。"""
        gw = _StagedGateway(answers=["烟酰胺美白有文献支持[1]。"])
        app.dependency_overrides[get_llm_gateway] = lambda: gw
        r = client.post("/api/chat", json={"question": "烟酰胺真的能美白吗？", "verify": False})
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {"answer", "evidence_pack", "citations_used",
                             "hallucinated_citations", "channel"}
        assert len(gw.gen_calls) == 1
        assert gw.verify_calls == []

    def test_verify_default_true_adds_verification(self, client):
        """默认 verify=true：响应增加 verification（final_answer/verification/rewritten/rounds）。"""
        gw = _StagedGateway(
            answers=["烟酰胺美白有文献支持[1]。"],
            verifies=['{"supported": true, "reason": "有出处"}'],
        )
        app.dependency_overrides[get_llm_gateway] = lambda: gw
        r = client.post("/api/chat", json={"question": "烟酰胺真的能美白吗？"})
        assert r.status_code == 200
        body = r.json()
        assert "verification" in body
        vres = body["verification"]
        assert set(vres) == {"final_answer", "verification", "rewritten", "rounds"}
        assert vres["rounds"] == 1
        assert vres["rewritten"] is False
        assert vres["final_answer"] == body["answer"]
        assert vres["verification"][0]["supported"] is True

    def test_verify_true_marks_warning_after_failed_rounds(self, client):
        """核验两轮不过：verification.final_answer 带 ⚠️，原 answer 字段不删改。"""
        gw = _StagedGateway(
            answers=["烟酰胺能祛斑[1]。"],
            verifies=['{"supported": false, "reason": "证据未提及祛斑"}'],
        )
        app.dependency_overrides[get_llm_gateway] = lambda: gw
        r = client.post("/api/chat", json={"question": "烟酰胺真的能美白吗？", "verify": True})
        assert r.status_code == 200
        body = r.json()
        assert body["answer"] == "烟酰胺能祛斑[1]。"  # 原逻辑产物不删改
        vres = body["verification"]
        assert vres["rounds"] == 2
        assert vres["final_answer"] == "烟酰胺能祛斑[1]⚠️。"
        assert vres["verification"][-1]["supported"] is False
