"""圆桌四 Agent 编排（总纲 v4.1 §三支柱 4，决赛演示形态）。

信息不对称分工：四角色各绑确定性工具（agent_tools）与独占信息源——
成分专家→产品库（lookup+similar）/ 法规合规官→NMPA 宣称摘要库 /
文献核验官→证据库 / 剂量推断师→浓度引擎。编排为确定性串行流程，LLM 只负责
把本角色的工具 JSON 转写为发言；裁决官用独立 prompt 综合四份发言+工具数据，
按五级判定组合表定级（映射规则写进 VERDICT_PROMPT）。

事件流（供 SSE）：start（tool_product_lookup 结果）→ 每角色 tool_call×n →
speak → verdict。诚实语义与各底层服务一致：产品未找到 → error 即终（不消耗
LLM）；LLM 不可达 → error 事件降级；裁决 JSON 解析失败 → label 落「无法判定」
并带原始文本，不猜级别；浓度相关表述由角色 prompt 强制「估计值」语义。
"""

from __future__ import annotations

import json
import re
from typing import Iterator

from sqlalchemy.orm import Session

from .agent_tools import (
    tool_dose_check,
    tool_ingredient_evidence,
    tool_product_claims,
    tool_product_lookup,
    tool_similar_products,
)
from .llm_gateway import LLMGateway, LLMUnavailableError
from .rag_qa import _ingredient_hits

ROLES = {
    "ingredient_expert": {"name": "成分专家", "prompt": "你是成分专家，负责分析产品的成分构成与相似产品。只根据工具数据发言，简洁专业，≤150字。"},
    "evidence_verifier": {"name": "文献核验官", "prompt": "你是文献核验官，负责核查功效宣称的文献证据。只根据工具数据发言，指出证据层级与弱项，≤150字。"},
    "dose_analyst": {"name": "剂量推断师", "prompt": "你是剂量推断师，负责剂量达标判定。只根据工具数据发言，浓度必须注明估计值，≤150字。"},
    "regulation_officer": {"name": "法规合规官", "prompt": "你是法规合规官，负责核对 NMPA 功效宣称依据摘要。只根据工具数据发言，≤150字。"},
}

# 发言顺序（总纲圆桌流程）：成分 → 法规 →（主功效关键成分）→ 文献 → 剂量
_SPEAK_ORDER = ["ingredient_expert", "regulation_officer",
                "evidence_verifier", "dose_analyst"]

# 五级判定组合表（创新计划 v3/总纲 v4.1 §三，命中即停）
VERDICT_LEVELS = {
    1: "证据相悖",
    2: "证据不足",
    3: "剂量达标但透皮存疑",
    4: "证据支持但剂量存疑",
    5: "与证据·剂量·透皮一致（估计）",
}
FALLBACK_LABEL = "无法判定"

VERDICT_PROMPT = """你是圆桌裁决官。综合四位角色的发言与工具数据，对产品的核心功效宣称给出五级判定。

五级判定组合表（优先级从高到低，命中即停）：
1「证据相悖」：文献证据与宣称矛盾。
2「证据不足」：检索不到支撑证据。
2「证据支持，剂量无法判定」：证据支持功效，但断言无起效浓度或产品无浓度推断（inferred=false）。
3「剂量达标但透皮存疑」：证据支持 ∧ 剂量达标 ∧ 透皮存疑；剂量与透皮双存疑并入本级并注明。
4「证据支持但剂量存疑」：证据支持 ∧ 剂量推断不足（insufficient）或不确定（uncertain）。
5「与证据·剂量·透皮一致（估计）」：证据支持 ∧ 剂量达标 ∧ 透皮无障碍；剂量未知或透皮不可判定时禁止给出本级。

只输出 JSON：{"level": 1-5 的整数, "label": "上表标签原文", "reason": "一句话依据"}"""

_JSON_OBJ_RE = re.compile(r"\{.*\}", re.S)


def _dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _infer_key_ingredient(session: Session, product_name: str, claims: list[dict]) -> str:
    """主功效关键成分（确定性推断，不经 LLM）：首条宣称文本 → 产品名，别名/成分名命中即止。

    均无命中时用首条宣称（无宣称用产品名）做查询——工具会如实返回未找到，
    文献核验官据此发言，不编造成分。
    """
    texts = [c["claim"] for c in claims[:1] if c.get("claim")] + [product_name]
    for text in texts:
        hits = _ingredient_hits(session, text)
        if hits:
            return hits[0].cn_name or hits[0].inci_name
    return texts[0]


def _speak(gateway: LLMGateway, role: str, product_name: str, tool_data: dict) -> str:
    """角色发言：本角色的工具 JSON 塞进其 prompt（信息不对称：只见自己的信息源）。"""
    return gateway.chat([
        {"role": "system", "content": ROLES[role]["prompt"]},
        {"role": "user", "content": f"【产品】{product_name}\n【工具数据】\n{_dump(tool_data)}"},
    ])


def _parse_verdict(raw: str) -> dict:
    """解析裁决 JSON；解析失败/级别越界 → label 落「无法判定」并带原始文本（安全方向）。"""
    data = None
    try:
        data = json.loads(raw)
    except ValueError:
        m = _JSON_OBJ_RE.search(raw)
        if m:
            try:
                data = json.loads(m.group(0))
            except ValueError:
                data = None
    if isinstance(data, dict):
        level = data.get("level")
        if isinstance(level, int) and level in VERDICT_LEVELS:
            label = data.get("label")
            if not isinstance(label, str) or not label.strip():
                label = VERDICT_LEVELS[level]  # 缺 label 时按组合表补
            return {"event": "verdict", "level": level, "label": label.strip(),
                    "reason": str(data.get("reason", "")).strip()}
    return {"event": "verdict", "level": None, "label": FALLBACK_LABEL,
            "reason": "裁决输出无法解析，按无法判定处理", "raw": raw}


def _judge(gateway: LLMGateway, product: dict, speeches: dict, tool_data: dict) -> dict:
    """独立裁决 prompt：四份发言 + 宣称/证据/剂量工具数据 → 五级判定 JSON。"""
    lines = "\n".join(f"【{ROLES[r]['name']}】{speeches[r]}" for r in _SPEAK_ORDER)
    brand = product.get("brand") or ""
    user = (f"【产品】{product['name']}（{brand}）\n"
            f"【四方发言】\n{lines}\n\n"
            f"【工具数据】\n{_dump(tool_data)}")
    raw = gateway.chat([
        {"role": "system", "content": VERDICT_PROMPT},
        {"role": "user", "content": user},
    ], response_format={"type": "json_object"})
    return _parse_verdict(raw)


def run_roundtable(session: Session, gateway: LLMGateway, product_name: str,
                   *, trace: bool = True) -> Iterator[dict]:
    """圆桌编排生成器：按顺序产出事件 dict（供 SSE 逐条推送）。

    start（tool_product_lookup 结果，未找到 → error 即终）→
    成分专家（product_lookup + similar_products k=3）→ 法规合规官（product_claims）→
    文献核验官（对主功效关键成分 ingredient_evidence）→ 剂量推断师（dose_check）→
    verdict（独立裁决 prompt 综合四份发言+工具数据，五级判定组合表）。
    trace=False 时省略 tool_call 事件（只留 start/speak/verdict）。
    """
    lookup = tool_product_lookup(session, product_name)
    if not lookup["found"]:
        yield {"event": "error",
               "message": f"未找到产品：{product_name.strip()}", "lookup": lookup}
        return
    yield {"event": "start", "product": lookup}
    product = lookup["products"][0]  # 首个候选（匹配度排序）作为圆桌对象
    pid = product["id"]

    def _tool(role: str, name: str, args: dict) -> dict:
        return {"event": "tool_call", "role": role, "tool": name, "args": args}

    try:
        speeches: dict[str, str] = {}

        # 1) 成分专家：产品库（即 start 的 lookup，不重复查询）+ 三级相似 k=3
        role = "ingredient_expert"
        if trace:
            yield _tool(role, "product_lookup", {"product_name": product_name})
        similar = tool_similar_products(session, pid, k=3)
        if trace:
            yield _tool(role, "similar_products", {"product_id": pid, "k": 3})
        speeches[role] = _speak(gateway, role, product["name"],
                                {"product_lookup": lookup, "similar_products": similar})
        yield {"event": "speak", "role": role, "name": ROLES[role]["name"],
               "content": speeches[role]}

        # 2) 法规合规官：NMPA 功效宣称依据摘要
        role = "regulation_officer"
        claims = tool_product_claims(session, pid)
        if trace:
            yield _tool(role, "product_claims", {"product_id": pid})
        speeches[role] = _speak(gateway, role, product["name"], claims)
        yield {"event": "speak", "role": role, "name": ROLES[role]["name"],
               "content": speeches[role]}

        # 3) 文献核验官：主功效关键成分（首条宣称或产品名推断）的功效断言与证据
        role = "evidence_verifier"
        ingredient_name = _infer_key_ingredient(session, product["name"], claims["claims"])
        evidence = tool_ingredient_evidence(session, ingredient_name)
        if trace:
            yield _tool(role, "ingredient_evidence", {"ingredient_name": ingredient_name})
        speeches[role] = _speak(gateway, role, product["name"],
                                {"key_ingredient": ingredient_name,
                                 "ingredient_evidence": evidence})
        yield {"event": "speak", "role": role, "name": ROLES[role]["name"],
               "content": speeches[role]}

        # 4) 剂量推断师：浓度估计区间 + 逐断言剂量判定（估计值语义由工具保证）
        role = "dose_analyst"
        dose = tool_dose_check(session, pid)
        if trace:
            yield _tool(role, "dose_check", {"product_id": pid})
        speeches[role] = _speak(gateway, role, product["name"], dose)
        yield {"event": "speak", "role": role, "name": ROLES[role]["name"],
               "content": speeches[role]}

        # 5) 裁决：独立 prompt 综合四份发言 + 宣称/证据/剂量工具数据
        verdict_evidence = {"key_ingredient": ingredient_name, "claims": claims,
                            "ingredient_evidence": evidence, "dose": dose}
        verdict = _judge(gateway, product, speeches, verdict_evidence)
        verdict["evidence"] = verdict_evidence
        yield verdict
    except LLMUnavailableError as e:
        yield {"event": "error", "message": str(e)}
