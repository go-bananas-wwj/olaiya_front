"""生成者-验证者非对称校验循环（总纲模型层阶段 2，RARR 式）。

初稿由 rag_qa.answer_question 产出；verify_answer 把回答拆成含引用编号 [n]
的待核验句（无引用的过渡句不核验），逐句连同其引用编号对应的证据子集发给
VERIFY_PROMPT 核验——证据子集而非全包，控制 token。

全部通过一轮即终；有不通过且轮次未满 max_rounds 时，把未通过陈述与原因反馈
给生成者重写一轮再重验（带错误反馈的 RARR 循环）；仍有不通过则 final_answer
保留原样、对应句尾追加 ⚠️ 标记，verification 如实记录——不删改生成内容，
只标注。核验回复无法解析为 JSON 时按不通过处理并如实注明（安全方向）。
"""

from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from .llm_gateway import LLMGateway
from .rag_qa import SYSTEM_PROMPT

VERIFY_PROMPT = """你是证据核验员。给定【证据材料】和一句【陈述】，判断该陈述是否被证据材料直接支持。
只回答 JSON：{"supported": true/false, "reason": "一句话"}。陈述中的功效结论必须能在证据材料中找到出处才算支持。"""

# 待核验句切分：句号/分号/感叹/问号/换行
_CLAIM_SPLIT_RE = re.compile(r"[。；;！？!?\n]+")
_CITATION_RE = re.compile(r"\[(\d{1,3})\]")
_JSON_OBJ_RE = re.compile(r"\{[^{}]*\}", re.S)


def split_claims(answer: str) -> list[str]:
    """把回答拆成待核验句子：按句号/分号拆，只保留含引用编号 [n] 的句子（无引用的句子属于过渡语，不核验）。"""
    claims = []
    for seg in _CLAIM_SPLIT_RE.split(answer):
        seg = seg.strip()
        if seg and _CITATION_RE.search(seg):
            claims.append(seg)
    return claims


def _parse_verify_reply(reply: str) -> tuple[bool, str]:
    """解析核验回复 {"supported":..., "reason":...}；解析失败按不通过处理并如实注明。"""
    data = None
    try:
        data = json.loads(reply)
    except ValueError:
        m = _JSON_OBJ_RE.search(reply)
        if m:
            try:
                data = json.loads(m.group(0))
            except ValueError:
                data = None
    if not isinstance(data, dict) or "supported" not in data:
        return False, f"核验结果解析失败，按不通过处理（原始回复：{reply[:80]}）"
    return bool(data["supported"]), str(data.get("reason", ""))


def _verify_claim(gateway: LLMGateway, claim: str, pack_by_id: dict[int, dict]) -> dict:
    """单句核验：只带该句引用编号对应的证据子集（而非全包），控制 token。"""
    cids = [int(n) for n in _CITATION_RE.findall(claim)]
    cited = [pack_by_id[i] for i in dict.fromkeys(cids) if i in pack_by_id]
    if cited:
        materials = "\n".join(f"[{it['id']}] {it['text']}" for it in cited)
    else:  # 包外引用：无证据可附，如实标注，交由核验员判不通过
        materials = "（该陈述的引用编号在证据包中不存在）"
    user = f"【证据材料】\n{materials}\n\n【陈述】{claim}"
    reply = gateway.chat([
        {"role": "system", "content": VERIFY_PROMPT},
        {"role": "user", "content": user},
    ])
    supported, reason = _parse_verify_reply(reply)
    return {"claim": claim, "supported": supported, "reason": reason, "citations": cids}


def _rewrite(gateway: LLMGateway, question: str, answer: str,
             failed: list[dict], items: list[dict]) -> str:
    """带错误反馈的重写：未通过陈述+原因回给生成者，仍受铁律 SYSTEM_PROMPT 约束。"""
    if items:
        materials = "\n".join(f"[{it['id']}] {it['text']}" for it in items)
    else:
        materials = "（未检索到相关证据材料）"
    failed_lines = "\n".join(f"- {v['claim']}（原因：{v['reason']}）" for v in failed)
    user = (
        f"【证据材料】\n{materials}\n\n【问题】{question}\n\n"
        f"【上一轮回答】\n{answer}\n\n"
        f"【未通过核验的陈述】\n{failed_lines}\n\n"
        "请修正：只根据证据材料重新回答，未通过核验的陈述若找不到证据支持就删除"
        "或改为「证据不足」表述，已通过核验的陈述保持不变。引用编号格式 [n] 不变。"
    )
    return gateway.chat([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ])


def verify_answer(session: Session, gateway: LLMGateway, question: str,
                  rag_result: dict, *, max_rounds: int = 2) -> dict:
    """生成者-验证者循环。

    round 1：split_claims(rag_result["answer"]) → 逐句连同其引用编号对应的证据
    原文发给 VERIFY_PROMPT（证据子集而非全包，控制 token）。
    返回 {final_answer, verification: [{claim, supported, reason, citations}],
    rewritten, rounds}（rounds = 实际核验轮数；无可核验句时为 0）。
    若有 supported=false 且 rounds < max_rounds：把「未通过核验的陈述+原因」反馈
    给生成者重写一轮（带错误反馈的 RARR 循环），重验；仍有不通过 → final_answer
    保留原样但在对应句尾追加 ⚠️ 标记，verification 如实记录。

    session 保留与 answer_question 对称的签名；证据包直接取自 rag_result，
    本函数不再查库。
    """
    answer = rag_result["answer"]
    items = rag_result.get("evidence_pack", [])
    pack_by_id = {it["id"]: it for it in items}
    rounds = 0
    rewritten = False
    verifications: list[dict] = []

    while split_claims(answer):
        rounds += 1
        verifications = [_verify_claim(gateway, c, pack_by_id) for c in split_claims(answer)]
        failed = [v for v in verifications if not v["supported"]]
        if not failed or rounds >= max_rounds:
            break
        answer = _rewrite(gateway, question, answer, failed, items)
        rewritten = True

    final_answer = answer
    for v in verifications:  # 循环结束后仍不通过的陈述：句尾追加 ⚠️，不删改原句
        if not v["supported"] and v["claim"] in final_answer:
            final_answer = final_answer.replace(v["claim"], v["claim"] + "⚠️", 1)
    return {"final_answer": final_answer, "verification": verifications,
            "rewritten": rewritten, "rounds": rounds}
