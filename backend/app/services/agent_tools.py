"""Agent 工具层（总纲 v4.1 §三支柱 4）：圆桌 Agent 的确定性工具函数，LLM 无关。

6 个工具统一「session 在前、业务参数在后」，返回 JSON 可序列化 dict，
后续圆桌 Agent 与 RAG 直接调用；TOOLS 注册表（name → {fn, description,
parameters(JSON Schema)}）供 LLM function calling 消费——session 与
cid_map 由调用方注入，不出现在 schema 中。

圆桌绑定：成分专家→product_lookup（产品库）/ 法规合规官→product_claims
（NMPA 宣称摘要库）/ 文献核验官→ingredient_evidence（证据库）/
剂量推断师→dose_check（浓度引擎）/ 透皮→transdermal / 平替→similar_products。

诚实语义与各底层服务一致：推断浓度是估计值（inferred=false 诚实降级）、
透皮判定为理化模型估计（not_applicable 为合法输出）、L2 相似含 available
语义、无证据/无宣称/无匹配一律如实空载，不编造。
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models.ingredient import EfficacyAssertion, Ingredient
from ..models.product import Product, ProductClaim, ProductIngredient
from .aliases import alias_exact, aliases_in_text
from .dosecheck import dose_verdicts
from .similar_levels import level1_jaccard, level2_dose, level3_fingerprint
from .transdermal import get_transdermal_info

# 成分理化映射（透皮判定数据源）：与 main.py 同一文件，懒加载缓存避免每请求 IO
_CID_MAP_PATH = Path(__file__).resolve().parents[3] / "data" / "seed" / "cid_map.json"
_cid_map_cache: dict | None = None


def _load_cid_map() -> dict:
    global _cid_map_cache
    if _cid_map_cache is None:
        _cid_map_cache = json.loads(_CID_MAP_PATH.read_text(encoding="utf-8"))
    return _cid_map_cache


def _match_rank(name: str, q: str) -> tuple[int, int]:
    """匹配度分级（小=更匹配）：精确 > 前缀 > 子串；同级短名优先（更接近查询）。"""
    if name == q:
        return (0, 0)
    if name.startswith(q):
        return (1, len(name))
    return (2, len(name))


def _resolve_inci(session: Session, inci: str) -> Ingredient | None:
    """按 INCI 精确（大小写无关）→ 前缀解析成分；未登记返回 None（不建 stub）。"""
    ing = session.execute(
        select(Ingredient).where(func.upper(Ingredient.inci_name) == inci)
    ).scalars().first()
    if ing is None:
        ing = session.execute(
            select(Ingredient).where(Ingredient.inci_name.like(f"{inci}%"))
            .order_by(func.length(Ingredient.inci_name), Ingredient.id)
        ).scalars().first()
    return ing


def _match_ingredient(session: Session, name: str) -> Ingredient | None:
    """按别名表 → 中文名/INCI 模糊匹配唯一成分：精确别名直达 INCI 优先。

    精确别名（整词命中，如「VC」「377」）直接解析到登记成分；别名指向的 INCI
    未登记时落回模糊匹配（精确（中文或 INCI 大小写无关）> 前缀 > 子串）。
    """
    q = name.strip()
    if not q:
        return None
    for inci in alias_exact(q) or ():
        ing = _resolve_inci(session, inci)
        if ing is not None:
            return ing
    like = f"%{q}%"
    rows = session.execute(
        select(Ingredient).where(
            or_(Ingredient.cn_name.like(like), Ingredient.inci_name.like(like)))
    ).scalars().all()
    if not rows:
        return None
    upper = q.upper()

    def rank(i: Ingredient) -> tuple:
        tiers = [_match_rank(i.cn_name, q), _match_rank(i.inci_name.upper(), upper)]
        return (*min(tiers), i.id)

    rows.sort(key=rank)
    return rows[0]


# ---------- 工具 1：产品库（成分专家） ----------

def tool_product_lookup(session: Session, product_name: str) -> dict:
    """按名称模糊查产品，多候选按匹配度排序（精确 > 前缀 > 子串，同级短名优先）。

    名称无命中时落回成分别名索引：查询词含俗名/别名（VC、377、玻尿酸…）时，
    经成分表查到含该成分的产品（matched_via=ingredient，并如实带出命中成分）。
    """
    q = product_name.strip()
    if not q:
        return {"found": False, "products": [], "exact": False}
    rows = session.execute(
        select(Product).where(Product.name.like(f"%{q}%"))
    ).scalars().all()
    rows.sort(key=lambda p: (*_match_rank(p.name, q), p.id))
    # (product, matched_via, matched_ingredient|None)
    hits: list[tuple[Product, str, Ingredient | None]] = [
        (p, "name", None) for p in rows]
    if not hits:  # 别名 → 成分 → 含该成分的产品（同一别名表，与用户语言一致）
        seen_ing: set[int] = set()
        seen_prod: set[int] = set()
        for _alias, incis in aliases_in_text(q):
            for inci in incis:
                ing = _resolve_inci(session, inci)
                if ing is None or ing.id in seen_ing:
                    continue
                seen_ing.add(ing.id)
                prows = session.execute(
                    select(Product)
                    .join(ProductIngredient, ProductIngredient.product_id == Product.id)
                    .where(ProductIngredient.ingredient_id == ing.id)
                    .order_by(Product.id)
                ).scalars().all()
                for p in prows:
                    if p.id not in seen_prod:
                        seen_prod.add(p.id)
                        hits.append((p, "ingredient", ing))
    ids = [p.id for p, _, _ in hits]
    # 计数走分组批量查询，不逐产品单查
    claim_counts = dict(
        session.query(ProductClaim.product_id, func.count())
        .filter(ProductClaim.product_id.in_(ids))
        .group_by(ProductClaim.product_id).all()
    ) if ids else {}
    ingredient_counts = dict(
        session.query(ProductIngredient.product_id, func.count())
        .filter(ProductIngredient.product_id.in_(ids))
        .group_by(ProductIngredient.product_id).all()
    ) if ids else {}
    products = [
        {"id": p.id, "name": p.name, "brand": p.brand, "nmpa_id": p.nmpa_id,
         "claim_count": claim_counts.get(p.id, 0),
         "ingredient_count": ingredient_counts.get(p.id, 0),
         "matched_via": via,
         "matched_ingredient": ({"id": ing.id, "inci_name": ing.inci_name,
                                 "cn_name": ing.cn_name} if ing else None)}
        for p, via, ing in hits
    ]
    return {"found": bool(products), "products": products,
            "exact": bool(rows) and rows[0].name == q}


# ---------- 工具 2：NMPA 宣称摘要库（法规合规官） ----------

def tool_product_claims(session: Session, product_id: int) -> dict:
    """产品的 NMPA 功效宣称依据摘要；无宣称或产品不存在时 claims=[]（不编造）。"""
    claims = (session.query(ProductClaim)
              .filter_by(product_id=product_id)
              .order_by(ProductClaim.id).all())
    return {
        "product_id": product_id,
        "claims": [
            {"claim": c.claim, "eval_category": c.eval_category,
             "method_name": c.method_name, "metric": c.metric,
             "result_summary": c.result_summary, "institution": c.institution}
            for c in claims
        ],
    }


# ---------- 工具 3：证据库（文献核验官） ----------

def tool_ingredient_evidence(session: Session, ingredient_name: str) -> dict:
    """按中文/INCI 模糊匹配成分，返回其功效断言及挂载证据（铁律：断言必有证据）。"""
    ing = _match_ingredient(session, ingredient_name)
    if ing is None:
        return {"found": False, "ingredient": None, "assertions": [],
                "note": f"未找到成分：{ingredient_name.strip()}"}
    assertions = (session.query(EfficacyAssertion)
                  .filter_by(ingredient_id=ing.id)
                  .order_by(EfficacyAssertion.id).all())
    out = []
    for a in assertions:
        ev = a.evidence
        out.append({
            "efficacy": a.efficacy,
            "efficacy_canonical": a.efficacy_canonical,
            "eff_low": a.effective_conc_low,
            "eff_high": a.effective_conc_high,
            "evidence_level": a.evidence_level,
            "evidence_strength": a.evidence_strength,
            "evidence": {"type": ev.type.value, "title": ev.title, "source": ev.source,
                         "year": ev.year, "url": ev.url, "excerpt": ev.excerpt},
        })
    return {
        "found": True,
        "ingredient": {"id": ing.id, "inci_name": ing.inci_name, "cn_name": ing.cn_name},
        "assertions": out,
        "note": None if out else "该成分暂无证据记录",
    }


# ---------- 工具 4：浓度引擎（剂量推断师） ----------

def tool_dose_check(session: Session, product_id: int) -> dict:
    """包装 dose_verdicts：浓度估计区间 + 逐断言剂量判定；无推断时 inferred=false。

    low/high 为推断引擎输出的模型估计值（p5/p95），非实测浓度。
    """
    estimates = dose_verdicts(session, product_id)
    if estimates is None:
        return {"product_id": product_id, "inferred": False,
                "reason": "无官方降序成分表，未推断"}
    return {"product_id": product_id, "inferred": True, "estimates": estimates}


# ---------- 工具 5：透皮判定 ----------

def tool_transdermal(session: Session, ingredient_name: str,
                     cid_map: dict | None = None) -> dict:
    """包装 get_transdermal_info：中文名先解析为 INCI；未入库成分按原名查映射表。

    cid_map 由调用方传入（测试/定制）；缺省时模块内加载 data/seed/cid_map.json。
    输出语义为理化模型估计（not_applicable 为合法输出），见 disclaimer 字段。
    """
    ing = _match_ingredient(session, ingredient_name)
    inci = ing.inci_name if ing else ingredient_name.strip().upper()
    info = get_transdermal_info(inci, cid_map if cid_map is not None else _load_cid_map())
    verdict = info["verdict"]
    return {
        "query": ingredient_name.strip(),
        "ingredient": ({"id": ing.id, "inci_name": ing.inci_name, "cn_name": ing.cn_name}
                       if ing else None),
        "inci_name": inci,
        "verdict": verdict.value if verdict is not None else None,
        "mw": info["mw"],
        "xlogp": info["xlogp"],
        "logkp": info["logkp"],
        "reason": info["reason"],
        "disclaimer": info["disclaimer"],
    }


# ---------- 工具 6：三级相似产品 ----------

def tool_similar_products(session: Session, product_id: int, k: int = 5) -> dict:
    """包装 similar-levels 的 l1/l3 与 l2（L2 需要浓度推断，含 available 语义）。"""
    if session.get(Product, product_id) is None:
        return {"product_id": product_id, "found": False, "l1": [],
                "l2": {"available": False, "reason": "产品不存在"}, "l3": []}
    return {
        "product_id": product_id,
        "found": True,
        "l1": level1_jaccard(session, product_id, k=k),
        "l2": level2_dose(session, product_id, k=k),
        "l3": level3_fingerprint(session, product_id, k=k),
    }


# ---------- 统一注册表（LLM function calling 直接消费） ----------

def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required}


_PRODUCT_ID = {"type": "integer", "description": "产品 id（由 product_lookup 获得）"}
_INGREDIENT_NAME = {"type": "string", "description": "成分中文名、INCI 名或俗名别名（VC/377 等），支持模糊匹配"}

TOOLS: dict[str, dict] = {
    "product_lookup": {
        "fn": tool_product_lookup,
        "description": "按名称模糊检索产品库，返回候选产品（id/名称/品牌/备案号/宣称数/成分数），多候选按匹配度排序；名称无命中时支持成分俗名/别名（VC、377、玻尿酸等）检索含该成分的产品",
        "parameters": _schema(
            {"product_name": {"type": "string", "description": "产品名称关键词，支持子串模糊匹配与成分俗名/别名"}},
            ["product_name"]),
    },
    "product_claims": {
        "fn": tool_product_claims,
        "description": "查询产品的 NMPA 功效宣称依据摘要（宣称/评价类别/方法/指标/结果/机构），法规合规官的信息源",
        "parameters": _schema({"product_id": _PRODUCT_ID}, ["product_id"]),
    },
    "ingredient_evidence": {
        "fn": tool_ingredient_evidence,
        "description": "按中文/INCI 名或俗名别名（VC、377、蓝铜胜肽等）查询成分的功效断言及挂载证据（文献/专利/法规，含证据层级与强度），文献核验官的信息源",
        "parameters": _schema({"ingredient_name": _INGREDIENT_NAME}, ["ingredient_name"]),
    },
    "dose_check": {
        "fn": tool_dose_check,
        "description": "查询产品成分浓度估计区间与逐断言剂量达标判定（估计值非实测；无推断时 inferred=false），剂量推断师的信息源",
        "parameters": _schema({"product_id": _PRODUCT_ID}, ["product_id"]),
    },
    "transdermal": {
        "fn": tool_transdermal,
        "description": "查询成分透皮可行性判定（500Da/logP 规则 + Potts-Guy；理化模型估计，未考虑递送系统与配方基质）",
        "parameters": _schema({"ingredient_name": _INGREDIENT_NAME}, ["ingredient_name"]),
    },
    "similar_products": {
        "fn": tool_similar_products,
        "description": "查询三级相似产品：L1 成分集合 Jaccard / L2 剂量级（需浓度推断，含 available 语义）/ L3 功效指纹余弦",
        "parameters": _schema(
            {"product_id": _PRODUCT_ID,
             "k": {"type": "integer", "description": "每级返回数量，默认 5", "default": 5}},
            ["product_id"]),
    },
}
