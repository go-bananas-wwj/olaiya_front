"""圆桌四 Agent 编排测试（总纲 v4.1 §三支柱 4，信息不对称分工+SSE 事件流）。

编排为确定性逻辑（工具调用顺序、关键成分推断、事件序列）直接断言；
gateway 用队列假件（依次返回四段发言与裁决 JSON），不依赖真实 LLM 服务。
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_db, get_llm_gateway
from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.models.product import Product, ProductClaim, ProductIngredient
from app.services.llm_gateway import LLMUnavailableError
from app.services.roundtable import ROLES, VERDICT_LEVELS, run_roundtable


class _QueueGateway:
    """队列假网关：chat 按队列依次返回（4 段角色发言 + 1 条裁决 JSON）。

    每次调用的 messages 记入 calls，供断言「工具 JSON 确实塞进了角色 prompt」。
    """

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls: list[list[dict]] = []
        self.channel = "fake"

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        return self._replies.pop(0)


class _FailGateway:
    """LLM 通道不可达假件。"""

    channel = "fake"

    def chat(self, messages, **kwargs):
        raise LLMUnavailableError("local 通道调用失败: connection refused")


def _seed(session):
    """玩具数据：烟酰胺（1 断言 1 证据）+ 2 产品（共享烟酰胺、均有推断浓度）+ p1 宣称。"""
    nia = Ingredient(inci_name="NIACINAMIDE", cn_name="烟酰胺")
    ev = Evidence(type=EvidenceType.PAPER, title="烟酰胺屏障 RCT", source="测试期刊",
                  year=2014, url="https://example.org/p1", excerpt="2% 烟酰胺改善屏障")
    session.add_all([nia, ev])
    session.flush()
    session.add(EfficacyAssertion(
        ingredient_id=nia.id, efficacy="修护", evidence_id=ev.id,
        effective_conc_low=2.0, effective_conc_high=5.0,
        evidence_level="human_rct", evidence_strength=0.9, efficacy_canonical="修护"))
    p1 = Product(name="烟酰胺修护精华", brand="甲牌", nmpa_id="沪G妆网备字001")
    p2 = Product(name="烟酰胺保湿乳", brand="乙牌")
    session.add_all([p1, p2])
    session.flush()
    session.add(ProductClaim(product_id=p1.id, claim="修护",
                             eval_category="人体功效评价试验",
                             result_summary="使用 4 周屏障改善"))
    session.add_all([
        ProductIngredient(product_id=p1.id, ingredient_id=nia.id, position=2,
                          conc_low=4.0, conc_high=6.0, conc_confidence=0.8),
        ProductIngredient(product_id=p2.id, ingredient_id=nia.id, position=5,
                          conc_low=1.0, conc_high=3.0, conc_confidence=0.6),
    ])
    session.commit()
    return {"nia": nia, "p1": p1, "p2": p2}


REPLIES_OK = [
    "成分构成：烟酰胺排第 2 位，估计浓度 4-6%；相似产品有烟酰胺保湿乳。",
    "NMPA 宣称 1 条：修护（人体功效评价试验，4 周屏障改善）。",
    "烟酰胺修护证据为人体 RCT，起效浓度 2-5%，证据较强。",
    "烟酰胺估计浓度 4-6%（估计值），落在起效区间 2-5% 之上，剂量达标。",
    '{"level": 4, "label": "证据支持但剂量存疑", "reason": "证据支持，剂量达标但透皮未判定"}',
]

EXPECTED_ROLE_ORDER = ["ingredient_expert", "regulation_officer",
                       "evidence_verifier", "dose_analyst"]


# ---------- 事件序列完整性 ----------

class TestEventSequence:
    def test_full_sequence(self, session):
        d = _seed(session)
        gw = _QueueGateway(REPLIES_OK)
        events = list(run_roundtable(session, gw, "烟酰胺修护精华"))

        # start → 成分专家 2×tool_call+speak → 其余 3 角色各 tool_call+speak → verdict
        assert [e["event"] for e in events] == [
            "start",
            "tool_call", "tool_call", "speak",
            "tool_call", "speak",
            "tool_call", "speak",
            "tool_call", "speak",
            "verdict",
        ]

        start = events[0]
        assert start["product"]["found"] is True
        assert start["product"]["products"][0]["id"] == d["p1"].id

        tool_calls = [e for e in events if e["event"] == "tool_call"]
        assert [(t["role"], t["tool"]) for t in tool_calls] == [
            ("ingredient_expert", "product_lookup"),
            ("ingredient_expert", "similar_products"),
            ("regulation_officer", "product_claims"),
            ("evidence_verifier", "ingredient_evidence"),
            ("dose_analyst", "dose_check"),
        ]
        # 成分专家的 similar k=3；剂量/宣称按产品 id；文献按推断出的关键成分
        assert tool_calls[1]["args"] == {"product_id": d["p1"].id, "k": 3}
        assert tool_calls[2]["args"] == {"product_id": d["p1"].id}
        assert tool_calls[3]["args"] == {"ingredient_name": "烟酰胺"}
        assert tool_calls[4]["args"] == {"product_id": d["p1"].id}

        speaks = [e for e in events if e["event"] == "speak"]
        assert [s["role"] for s in speaks] == EXPECTED_ROLE_ORDER
        assert [s["content"] for s in speaks] == REPLIES_OK[:4]
        for s in speaks:
            assert s["name"] == ROLES[s["role"]]["name"]

        verdict = events[-1]
        assert verdict["level"] == 4
        assert verdict["label"] == "证据支持但剂量存疑"
        assert verdict["reason"]
        # verdict 附带的工具证据：宣称 + 关键成分证据 + 剂量判定
        ev = verdict["evidence"]
        assert ev["claims"]["claims"][0]["claim"] == "修护"
        assert ev["ingredient_evidence"]["ingredient"]["inci_name"] == "NIACINAMIDE"
        assert ev["dose"]["inferred"] is True

    def test_tool_json_fed_to_role_prompts(self, session):
        """每步工具 JSON 必须塞进角色 prompt（信息不对称：各角色只见自己的工具数据）。"""
        _seed(session)
        gw = _QueueGateway(REPLIES_OK)
        list(run_roundtable(session, gw, "烟酰胺修护精华"))
        assert len(gw.calls) == 5  # 4 发言 + 1 裁决
        for messages in gw.calls:
            assert messages[0]["role"] == "system"
        # 成分专家 prompt 含相似产品数据；文献官 prompt 含证据数据；剂量师 prompt 含浓度数据
        assert "similar_products" in gw.calls[0][1]["content"]
        assert "claims" in gw.calls[1][1]["content"]
        assert "烟酰胺屏障 RCT" in gw.calls[2][1]["content"]
        assert "estimates" in gw.calls[3][1]["content"]
        # 裁决 prompt 综合四份发言
        judge_user = gw.calls[4][1]["content"]
        for reply in REPLIES_OK[:4]:
            assert reply in judge_user

    def test_trace_false_hides_tool_calls(self, session):
        _seed(session)
        gw = _QueueGateway(REPLIES_OK)
        events = list(run_roundtable(session, gw, "烟酰胺修护精华", trace=False))
        assert [e["event"] for e in events] == [
            "start", "speak", "speak", "speak", "speak", "verdict"]

    def test_key_ingredient_falls_back_to_claim_text(self, session):
        """产品名无成分线索时，用首条宣称文本查询（工具如实返回未找到，不编造）。"""
        d = _seed(session)
        p3 = Product(name="素颜面霜", brand="丙牌")
        session.add(p3)
        session.flush()
        session.add(ProductClaim(product_id=p3.id, claim="保湿"))
        session.commit()
        gw = _QueueGateway(REPLIES_OK)
        events = list(run_roundtable(session, gw, "素颜面霜"))
        ev_tool = [e for e in events if e["event"] == "tool_call"
                   and e["tool"] == "ingredient_evidence"][0]
        assert ev_tool["args"] == {"ingredient_name": "保湿"}
        verdict = events[-1]
        assert verdict["evidence"]["ingredient_evidence"]["found"] is False
        assert verdict["evidence"]["dose"]["inferred"] is False


# ---------- 降级路径 ----------

class TestDegradation:
    def test_product_not_found(self, session):
        _seed(session)
        gw = _QueueGateway(REPLIES_OK)
        events = list(run_roundtable(session, gw, "不存在的产品"))
        assert len(events) == 1
        assert events[0]["event"] == "error"
        assert "不存在的产品" in events[0]["message"]
        assert gw.calls == []  # 未找到产品不消耗 LLM 调用

    def test_verdict_parse_failure_falls_back(self, session):
        """裁决 JSON 解析失败：label 落「无法判定」并带原始文本，不猜级别。"""
        _seed(session)
        gw = _QueueGateway(REPLIES_OK[:4] + ["我觉得这个产品大概率是有效的"])
        events = list(run_roundtable(session, gw, "烟酰胺修护精华"))
        verdict = events[-1]
        assert verdict["event"] == "verdict"
        assert verdict["level"] is None
        assert verdict["label"] == "无法判定"
        assert "我觉得这个产品大概率是有效的" in verdict["raw"]

    def test_verdict_label_filled_from_level(self, session):
        """裁决只给 level 不给 label 时按五级组合表补标签。"""
        _seed(session)
        gw = _QueueGateway(REPLIES_OK[:4] + ['{"level": 5, "reason": "全链路一致"}'])
        events = list(run_roundtable(session, gw, "烟酰胺修护精华"))
        verdict = events[-1]
        assert verdict["level"] == 5
        assert verdict["label"] == VERDICT_LEVELS[5] == "与证据·剂量·透皮一致（估计）"

    def test_verdict_invalid_level_falls_back(self, session):
        _seed(session)
        gw = _QueueGateway(REPLIES_OK[:4] + ['{"level": 9, "label": "x", "reason": "y"}'])
        events = list(run_roundtable(session, gw, "烟酰胺修护精华"))
        assert events[-1]["label"] == "无法判定"

    def test_llm_unavailable_emits_error(self, session):
        _seed(session)
        events = list(run_roundtable(session, _FailGateway(), "烟酰胺修护精华"))
        assert events[0]["event"] == "start"
        assert events[-1]["event"] == "error"
        assert "local" in events[-1]["message"]


# ---------- SSE 端点 ----------

def _sse_payloads(text: str) -> list[str]:
    """解析 SSE 响应体为 data 载荷序列。"""
    payloads = []
    for block in text.split("\n\n"):
        block = block.strip()
        if block:
            assert block.startswith("data: "), f"非 SSE 行：{block!r}"
            payloads.append(block[len("data: "):])
    return payloads


@pytest.fixture()
def client(session):
    _seed(session)
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def _override_gateway(gw):
    app.dependency_overrides[get_llm_gateway] = lambda: gw


class TestRoundtableAPI:
    def test_sse_event_stream(self, client):
        _override_gateway(_QueueGateway(REPLIES_OK))
        r = client.post("/api/roundtable", json={"product_name": "烟酰胺修护精华"})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        payloads = _sse_payloads(r.text)
        assert payloads[-1] == "[DONE]"
        events = [json.loads(p) for p in payloads[:-1]]
        assert events[0]["event"] == "start"
        assert events[-1]["event"] == "verdict"
        assert events[-1]["level"] == 4
        speaks = [e for e in events if e["event"] == "speak"]
        assert [s["role"] for s in speaks] == EXPECTED_ROLE_ORDER

    def test_sse_product_not_found(self, client):
        _override_gateway(_QueueGateway(REPLIES_OK))
        r = client.post("/api/roundtable", json={"product_name": "不存在的产品"})
        assert r.status_code == 200
        payloads = _sse_payloads(r.text)
        assert payloads[-1] == "[DONE]"
        events = [json.loads(p) for p in payloads[:-1]]
        assert len(events) == 1 and events[0]["event"] == "error"

    def test_sse_llm_unavailable(self, client):
        _override_gateway(_FailGateway())
        r = client.post("/api/roundtable", json={"product_name": "烟酰胺修护精华"})
        assert r.status_code == 200  # SSE 流内 error 事件诚实降级，不 503
        events = [json.loads(p) for p in _sse_payloads(r.text)[:-1]]
        assert events[-1]["event"] == "error"

    def test_blank_product_name_422(self, client):
        _override_gateway(_QueueGateway(REPLIES_OK))
        r = client.post("/api/roundtable", json={"product_name": "  "})
        assert r.status_code == 422
