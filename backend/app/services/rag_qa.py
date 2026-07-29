"""prompt RAG 基线（总纲模型层阶段 1）：「成分问答」的证据包组装与引用校验。

检索为确定性逻辑（LLM 无关）：先查成分别名表（俗名/代号直达 INCI，与
agent_tools 同一张表），再做成分中文/INCI 名子串命中，最后按问题分词走
agent_tools 的模糊匹配兜底；命中成分取其全部断言（含证据标题/期刊/年份/
PMID URL/起效浓度），命中产品取其 NMPA 宣称摘要，组装为编号连续的证据包。

LLM 只根据证据包回答并按 [n] 引用（SYSTEM_PROMPT 铁律）；答案解析出的引用编号
与证据包比对，包外编号如实记入 hallucinated_citations——不删改答案，如实报告。
诚实语义与底层一致：起效浓度为文献值，推断浓度相关表述须带「估计」语义。
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.ingredient import EfficacyAssertion, Ingredient
from ..models.product import Product
from .agent_tools import _match_ingredient, _resolve_inci, tool_product_claims
from .aliases import aliases_in_text
from .llm_gateway import LLMGateway

SYSTEM_PROMPT = """你是「成分真言」的化妆品成分核验助手。铁律：
1. 只根据提供的【证据材料】回答，禁止用你自己的知识补充功效结论。
2. 每个功效断言句尾必须标注引用编号，格式 [1][2]，编号必须来自证据材料。
3. 证据材料不足时，明确回答「证据不足，无法判定」，禁止编造。
4. 涉及浓度时注明「估计值」。"""

# 单次命中上限：防止一个泛名塞进几十条证据撑爆上下文
_MAX_INGREDIENT_HITS = 3
_MAX_PRODUCT_HITS = 3
# 名字太短（<2 字符）不做子串命中，避免单字误匹配
_MIN_NAME_LEN = 2

_CITATION_RE = re.compile(r"\[(\d{1,3})\]")
# 兜底分词：拉丁/数字/连字符段（≥2 字符，数字开头如 377 合法）或连续中文段
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]{1,}|[一-鿿]{2,8}")


def _fmt_num(v: float) -> str:
    return f"{v:g}"


# ---------- 确定性检索：名字命中问题 ----------

def _ingredient_hits(session: Session, question: str) -> list[Ingredient]:
    """别名表直达 → 成分名子串 → 分词模糊兜底；别名命中优先于子串命中。

    别名（VC/377/维生素C…）按「长别名优先、同长先出现优先」解析到登记成分；
    子串扫描保持「长名优先、同级 id 小优先」；两段共用一个去重序列，凑满
    _MAX_INGREDIENT_HITS 即止。前两段均无命中时才按问题分词走 agent_tools
    模糊匹配兜底（token ⊆ 成分名）。
    """
    ids: list[int] = []

    def _add(iid: int) -> None:
        if iid not in ids and len(ids) < _MAX_INGREDIENT_HITS:
            ids.append(iid)

    # 1) 别名表：命中直达 INCI（防「维生素C」被「生育酚（维生素E）」类长名截胡）
    for _alias, incis in aliases_in_text(question):
        for inci in incis:
            ing = _resolve_inci(session, inci)
            if ing is not None:
                _add(ing.id)

    # 2) 成分中文名/INCI 名（大小写无关）作为子串出现在问题中的成分，长名优先
    if len(ids) < _MAX_INGREDIENT_HITS:
        q_upper = question.upper()
        rows = session.execute(
            select(Ingredient.id, Ingredient.cn_name, Ingredient.inci_name)).all()
        scored: list[tuple[int, int]] = []  # (命中名长度, id)
        for iid, cn_name, inci_name in rows:
            matched = 0
            if cn_name and len(cn_name) >= _MIN_NAME_LEN and cn_name in question:
                matched = max(matched, len(cn_name))
            if inci_name and len(inci_name) >= _MIN_NAME_LEN and inci_name.upper() in q_upper:
                matched = max(matched, len(inci_name))
            if matched:
                scored.append((matched, iid))
        scored.sort(key=lambda t: (-t[0], t[1]))  # 更具体的命中（长名）优先，同级 id 小优先
        for _, iid in scored:
            _add(iid)

    if not ids:  # 3) 兜底：分词后复用 agent_tools 模糊匹配（token ⊆ 成分名）
        for tok in _TOKEN_RE.findall(question):
            ing = _match_ingredient(session, tok)
            if ing is not None:
                _add(ing.id)
    return [session.get(Ingredient, iid) for iid in ids]


def _product_hits(session: Session, question: str) -> list[Product]:
    """产品名作为子串出现在问题中的产品，长名优先；无命中时分词模糊兜底。"""
    rows = session.execute(select(Product.id, Product.name)).all()
    scored = [(len(name), pid) for pid, name in rows
              if name and len(name) >= _MIN_NAME_LEN and name in question]
    scored.sort(key=lambda t: (-t[0], t[1]))
    ids = [pid for _, pid in scored[:_MAX_PRODUCT_HITS]]
    if not ids:
        for tok in _TOKEN_RE.findall(question):
            cands = session.execute(
                select(Product.id).where(Product.name.like(f"%{tok}%"))).scalars().all()
            for pid in cands:
                if pid not in ids:
                    ids.append(pid)
            if len(ids) >= _MAX_PRODUCT_HITS:
                break
    return [session.get(Product, pid) for pid in ids[:_MAX_PRODUCT_HITS]]


# ---------- 证据文本组装 ----------

def _assertion_text(ing: Ingredient, a: EfficacyAssertion) -> str:
    ev = a.evidence
    parts = [f"{ing.cn_name}（{ing.inci_name}）：{a.efficacy}"]
    if a.effective_conc_low is not None and a.effective_conc_high is not None:
        if a.effective_conc_low == a.effective_conc_high:  # 退化区间显示单值
            parts.append(f"起效浓度 {_fmt_num(a.effective_conc_low)}%"
                         "（文献值，非产品中浓度）")
        else:
            parts.append(f"起效浓度 {_fmt_num(a.effective_conc_low)}-{_fmt_num(a.effective_conc_high)}%"
                         "（文献值，非产品中浓度）")
    elif a.effective_conc_low is not None:
        parts.append(f"起效浓度 ≥{_fmt_num(a.effective_conc_low)}%（文献值，非产品中浓度）")
    if a.evidence_level:
        parts.append(f"证据层级 {a.evidence_level}")
    ev_chain = ev.title
    if ev.source:
        ev_chain += f"，{ev.source}"
    if ev.year:
        ev_chain += f"，{ev.year}"
    if ev.url:
        ev_chain += f"，{ev.url}"
    parts.append(f"证据：{ev_chain}")
    if a.note:  # 弱证据等注意事项由加载器如实写入 note，原样带出
        parts.append(f"注：{a.note}")
    return "，".join(parts)


def _claim_text(product: Product, claim: dict) -> str:
    parts = [f"产品「{product.name}」（{product.brand}）NMPA 宣称：{claim['claim']}"]
    if claim.get("eval_category"):
        parts.append(claim["eval_category"])
    if claim.get("result_summary"):
        parts.append(f"结果：{claim['result_summary']}")
    if claim.get("institution"):
        parts.append(f"机构：{claim['institution']}")
    return "，".join(parts)


def build_evidence_pack(session: Session, question: str, *, max_items: int = 8) -> dict:
    """根据问题检索证据，组装编号连续的证据项列表（kind: assertion | claim）。

    命中成分取全部断言（断言在前，按成分匹配度与断言 id 排序），命中产品取
    NMPA 宣称摘要；整体截断 max_items 后统一编号 1..N。无命中 items 为空，
    ingredients_hit / products_hit 如实记录命中实体（即使其无证据可引）。
    """
    ingredients = _ingredient_hits(session, question)
    products = _product_hits(session, question)

    texts: list[tuple[str, str]] = []  # (kind, text)
    for ing in ingredients:
        assertions = (session.query(EfficacyAssertion)
                      .filter_by(ingredient_id=ing.id)
                      .order_by(EfficacyAssertion.id).all())
        texts.extend(("assertion", _assertion_text(ing, a)) for a in assertions)
    for p in products:
        claims = tool_product_claims(session, p.id)["claims"]
        texts.extend(("claim", _claim_text(p, c)) for c in claims)

    items = [{"id": n, "kind": kind, "text": text}
             for n, (kind, text) in enumerate(texts[:max_items], start=1)]
    return {
        "question": question,
        "items": items,
        "ingredients_hit": [{"id": i.id, "cn_name": i.cn_name, "inci_name": i.inci_name}
                            for i in ingredients],
        "products_hit": [{"id": p.id, "name": p.name, "brand": p.brand} for p in products],
    }


# ---------- 问答：LLM 只根据证据包回答 ----------

def _user_message(question: str, items: list[dict]) -> str:
    if items:
        materials = "\n".join(f"[{it['id']}] {it['text']}" for it in items)
    else:
        materials = "（未检索到相关证据材料）"
    return f"【证据材料】\n{materials}\n\n【问题】{question}"


def answer_question(session: Session, gateway: LLMGateway, question: str) -> dict:
    """证据包 + 铁律 prompt 调 LLM，解析引用编号并检出包外引用（不删改答案）。"""
    pack = build_evidence_pack(session, question)
    answer = gateway.chat([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _user_message(question, pack["items"])},
    ])
    citations_used = sorted({int(n) for n in _CITATION_RE.findall(answer)})
    valid_ids = {it["id"] for it in pack["items"]}
    hallucinated = [n for n in citations_used if n not in valid_ids]
    return {
        "answer": answer,
        "evidence_pack": pack["items"],
        "citations_used": citations_used,
        "hallucinated_citations": hallucinated,
        "channel": getattr(gateway, "channel", "unknown"),
    }
