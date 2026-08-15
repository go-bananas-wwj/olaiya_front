"""成分真言 API。启动（tmux，仓库根目录）：
tmux new-session -d -s cfz-web -c /root/workspace/olaiya \\
  "PYTHONPATH=backend .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8008"
（8000 端口被机器上其他程序占用，本项目统一用 8008；后台服务统一用 tmux，不用 nohup）
"""

import json
import re
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, joinedload

from .db import SessionLocal, init_db
from .models.evidence import Evidence, EvidenceType
from .models.ingredient import EfficacyAssertion, Ingredient
from .models.product import MarketSnapshot, Product, ProductClaim, ProductIngredient
from .services.dosecheck import dose_verdicts
from .services.efficacy_canon import canonicalize
from .services.evidence_level import HUMAN_CT, HUMAN_OPEN, HUMAN_RCT, REGULATION
from .services.llm_gateway import LLMGateway, LLMUnavailableError
from .services.rag_qa import answer_question
from .services.roundtable import run_roundtable
from .services.verify_loop import verify_answer
from .services.fingerprint import compute_fingerprint
from .services.evidence_profile import evidence_profile
from .services.scorecard import substitute_scorecard
from .services.similar_levels import level1_jaccard, level2_dose, level3_fingerprint
from .services.similarity import search_ingredients, search_products
from .services.transdermal import get_transdermal_info
from .services import vision_detect

# 成分理化映射（D3 透皮判定数据源）：启动时读入内存常量，避免每请求 IO
_CID_MAP_PATH = Path(__file__).resolve().parents[2] / "data" / "seed" / "cid_map.json"
CID_MAP: dict = json.loads(_CID_MAP_PATH.read_text(encoding="utf-8"))

# 功效胶囊筛选枚举 → 宣称关键词（多词 OR；拿不准的宣称不归类，同铁律 7 口径）
EFFICACY_KEYWORDS = {
    "美白": ["美白", "淡斑", "祛斑", "提亮"],
    "抗老": ["抗皱", "紧致", "淡纹", "抗老", "抗衰"],
    "保湿": ["保湿", "滋润", "补水"],
    "祛痘": ["祛痘", "清痘", "抗痘", "净痘"],
    "舒缓": ["舒缓", "舒敏", "修护"],
    "防晒": ["防晒"],
}
PRODUCT_SORTS = {"claim_count_desc", "ingredient_count_desc"}

# 功效产品榜 canon 枚举：efficacy_canonical 真实功效族（「其他」「防腐」为非功效族，
# 不在枚举内——口径同 fingerprint.py 的排除规则；拿不准的族不进枚举）
RANKING_CANONS = ("美白", "抗皱", "保湿", "舒缓", "控油祛痘", "修护", "抗氧化", "焕肤")
# 真人级证据层级（evidence_level 真实枚举值，见 services/evidence_level.py）
HUMAN_EVIDENCE_LEVELS = (HUMAN_RCT, HUMAN_CT, HUMAN_OPEN)

# 成分搜索折叠匹配：忽略大小写/空格/连字符（解码页逐成分查询依赖）
_FOLD_RE = re.compile(r"[\s\-]+")

app = FastAPI(title="成分真言 API", version="0.1.0")


@app.on_event("startup")
def _startup() -> None:
    init_db()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _assertion_dict(a: EfficacyAssertion) -> dict:
    ev = a.evidence
    return {
        "efficacy": a.efficacy,
        "effective_conc_low": a.effective_conc_low,
        "effective_conc_high": a.effective_conc_high,
        "note": a.note,
        "evidence": {
            "id": ev.id, "type": ev.type.value, "title": ev.title,
            "source": ev.source, "year": ev.year, "url": ev.url, "excerpt": ev.excerpt,
        },
    }


@app.get("/api/stats")
def stats(db: Session = Depends(get_db)):
    """全库统计：前端首页/页脚的规模展示。"""
    return {
        "products": db.query(Product).count(),
        "brands": db.query(func.count(func.distinct(Product.brand))).scalar(),
        "ingredients": db.query(Ingredient).count(),
        "ingredients_with_evidence": db.query(
            func.count(func.distinct(EfficacyAssertion.ingredient_id))).scalar(),
        "product_ingredients": db.query(ProductIngredient).count(),
        "claims": db.query(ProductClaim).count(),
        "assertions": db.query(EfficacyAssertion).count(),
        "evidence": db.query(Evidence).count(),
    }


@app.get("/api/ingredients")
def list_ingredients(q: str | None = None, has_evidence: str | None = None,
                     limit: int = Query(0, ge=0), offset: int = Query(0, ge=0),
                     db: Session = Depends(get_db)):
    """成分列表。断言计数用聚合子查询一次出（避免逐成分 COUNT 的 N+1）。

    不带 limit/offset 时保持旧的纯 list 返回；带 limit>0 或 offset>0 时
    返回 {"total": 过滤后总数, "items": [...]}（item 字段不变），LIMIT/OFFSET
    下推到 SQL 层。limit=0 表示不限。
    """
    # 断言计数的聚合子查询：has_evidence 过滤与 assertion_count 字段共用
    assert_sq = (select(EfficacyAssertion.ingredient_id.label("ingredient_id"),
                        func.count().label("assertion_count"))
                 .group_by(EfficacyAssertion.ingredient_id).subquery())
    assert_cnt = func.coalesce(assert_sq.c.assertion_count, 0)
    stmt = (select(Ingredient, assert_cnt)
            .outerjoin(assert_sq, assert_sq.c.ingredient_id == Ingredient.id))
    if q:
        like = f"%{q}%"
        folded = _FOLD_RE.sub("", q).lower()
        stmt = stmt.where(or_(
            Ingredient.cn_name.like(like),
            Ingredient.inci_name.like(like),
            func.replace(func.replace(func.lower(Ingredient.inci_name), " ", ""), "-", "")
                .like(f"%{folded}%"),
        ))
    if has_evidence == "true":
        stmt = stmt.where(assert_cnt > 0)
    if has_evidence == "false":
        stmt = stmt.where(assert_cnt == 0)

    def _item(i: Ingredient, cnt: int) -> dict:
        return {"id": i.id, "inci_name": i.inci_name, "cn_name": i.cn_name,
                "cas_no": i.cas_no, "assertion_count": cnt}

    stmt = stmt.order_by(Ingredient.id)
    if limit > 0 or offset > 0:
        total = db.execute(
            select(func.count()).select_from(stmt.subquery())).scalar_one()
        page = stmt.offset(offset)
        if limit > 0:
            page = page.limit(limit)
        items = [_item(i, cnt) for i, cnt in db.execute(page).all()]
        return {"total": total, "items": items}
    return [_item(i, cnt) for i, cnt in db.execute(stmt).all()]


@app.get("/api/ingredients/{ingredient_id}")
def ingredient_detail(ingredient_id: int, product_limit: int = Query(50, ge=0),
                      product_offset: int = Query(0, ge=0),
                      db: Session = Depends(get_db)):
    """成分详情。含该成分的产品默认只给前 50 条（product_total 为去重总数），
    可用 product_limit / product_offset 翻页，product_limit=0 表示不限。"""
    ing = db.get(Ingredient, ingredient_id)
    if ing is None:
        raise HTTPException(status_code=404, detail="成分不存在")
    assertions = (db.query(EfficacyAssertion)
                  .filter_by(ingredient_id=ing.id)
                  .order_by(EfficacyAssertion.id).all())
    # 含该成分的产品（经 ProductIngredient 关联去重，按产品 id 排序；
    # join 一次查出，避免逐链接惰性加载的 N+1）
    pid_sq = (select(ProductIngredient.product_id.label("product_id"))
              .where(ProductIngredient.ingredient_id == ing.id)
              .distinct().subquery())
    product_total = db.execute(
        select(func.count()).select_from(pid_sq)).scalar_one()
    stmt = (select(Product.id, Product.name, Product.brand)
            .join(pid_sq, pid_sq.c.product_id == Product.id)
            .order_by(Product.id).offset(product_offset))
    if product_limit > 0:
        stmt = stmt.limit(product_limit)
    products = [{"id": pid, "name": name, "brand": brand}
                for pid, name, brand in db.execute(stmt).all()]
    return {
        "id": ing.id,
        "inci_name": ing.inci_name,
        "cn_name": ing.cn_name,
        "cas_no": ing.cas_no,
        "priors": {
            "iecic_max_leave_on": ing.iecic_max_leave_on,
            "iecic_max_rinse_off": ing.iecic_max_rinse_off,
            "legal_cap": ing.legal_cap,
            "cir_conc_low": ing.cir_conc_low,
            "cir_conc_high": ing.cir_conc_high,
            "sccs_limit": ing.sccs_limit,
            # 配方实践典型用量（配方实例聚合，非官方限值、非功效起效浓度）
            "typical_use_low": ing.typical_use_low,
            "typical_use_high": ing.typical_use_high,
        },
        "assertions": [_assertion_dict(a) for a in assertions],
        "products": products,
        "product_total": product_total,
        # D3 透皮判定（理化模型估计，未考虑递送系统与配方基质；not_applicable 为合法输出）
        "transdermal": get_transdermal_info(ing.inci_name, CID_MAP),
    }


def _claim_dict(c: ProductClaim) -> dict:
    return {
        "claim": c.claim,
        "eval_category": c.eval_category,
        "method_name": c.method_name,
        "method_source": c.method_source,
        "metric": c.metric,
        "test_period": c.test_period,
        "result_summary": c.result_summary,
        "institution": c.institution,
    }


@app.get("/api/brands")
def list_brands(db: Session = Depends(get_db)):
    """去重排序后的品牌名列表（轻量接口，供前端品牌下拉用）。"""
    rows = db.execute(select(Product.brand).distinct().order_by(Product.brand)).scalars().all()
    return [b for b in rows if b]


@app.get("/api/products")
def list_products(q: str | None = None, brand: str | None = None,
                  has_claims: str | None = None, efficacy: str | None = None,
                  sort: str | None = None,
                  limit: int = Query(0, ge=0), offset: int = Query(0, ge=0),
                  db: Session = Depends(get_db)):
    """产品列表。claim/成分计数用聚合子查询一次出（避免逐产品两条 COUNT 的 N+1）。

    不带 limit/offset 时保持旧的纯 list 返回；带 limit>0 或 offset>0 时
    返回 {"total": 过滤后总数, "items": [...]}（item 字段不变），LIMIT/OFFSET
    下推到 SQL 层。limit=0 表示不限。
    """
    claim_sq = (select(ProductClaim.product_id.label("product_id"),
                       func.count().label("claim_count"))
                .group_by(ProductClaim.product_id).subquery())
    ing_sq = (select(ProductIngredient.product_id.label("product_id"),
                     func.count().label("ingredient_count"))
              .group_by(ProductIngredient.product_id).subquery())
    claim_cnt = func.coalesce(claim_sq.c.claim_count, 0)
    ing_cnt = func.coalesce(ing_sq.c.ingredient_count, 0)
    stmt = (select(Product, claim_cnt, ing_cnt)
            .outerjoin(claim_sq, claim_sq.c.product_id == Product.id)
            .outerjoin(ing_sq, ing_sq.c.product_id == Product.id))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Product.name.like(like), Product.brand.like(like),
                              Product.nmpa_id.like(like)))
    if brand:
        stmt = stmt.where(Product.brand == brand)  # 品牌精确匹配
    # 按是否存在功效宣称过滤
    if has_claims == "true":
        stmt = stmt.where(claim_cnt > 0)
    if has_claims == "false":
        stmt = stmt.where(claim_cnt == 0)
    if efficacy is not None:
        kws = EFFICACY_KEYWORDS.get(efficacy)
        if kws is None:
            raise HTTPException(status_code=422, detail=f"未知功效枚举: {efficacy}")
        stmt = stmt.where(Product.id.in_(
            select(ProductClaim.product_id)
            .where(or_(*[ProductClaim.claim.like(f"%{k}%") for k in kws]))))
    if sort is not None:
        if sort not in PRODUCT_SORTS:
            raise HTTPException(status_code=422, detail=f"未知排序: {sort}")
        stmt = stmt.order_by(
            claim_cnt.desc() if sort == "claim_count_desc" else ing_cnt.desc(),
            Product.id)
    else:
        stmt = stmt.order_by(Product.brand, Product.id)

    def _item(p: Product, claim_count: int, ing_count: int) -> dict:
        return {
            "id": p.id, "name": p.name, "brand": p.brand,
            "nmpa_id": p.nmpa_id, "claim_count": claim_count,
            "ingredient_count": ing_count,
        }

    if limit > 0 or offset > 0:
        total = db.execute(
            select(func.count()).select_from(stmt.subquery())).scalar_one()
        page = stmt.offset(offset)
        if limit > 0:
            page = page.limit(limit)
        items = [_item(p, cc, ic) for p, cc, ic in db.execute(page).all()]
        return {"total": total, "items": items}
    return [_item(p, cc, ic) for p, cc, ic in db.execute(stmt).all()]


@app.get("/api/products/{product_id}")
def product_detail(product_id: int, db: Session = Depends(get_db)):
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    links = (db.query(ProductIngredient)
             .filter_by(product_id=p.id)
             .order_by(ProductIngredient.id).all())
    claims = (db.query(ProductClaim)
              .filter_by(product_id=p.id)
              .order_by(ProductClaim.id).all())
    # 有功效断言的成分 id 集合：前端据此标记「有证据的成分」
    ids_with_evidence = {
        row[0] for row in db.query(EfficacyAssertion.ingredient_id).distinct().all()
    }
    return {
        "id": p.id,
        "name": p.name,
        "brand": p.brand,
        "category": p.category,
        "nmpa_id": p.nmpa_id,
        "registrant": p.registrant,
        "filing_date": p.filing_date,
        "source_url": p.source_url,
        "price_current": p.price_current,
        "spec": p.spec,
        "buy_url": p.buy_url,
        "note": p.note,
        "ingredients": [{
            "ingredient_id": l.ingredient_id,
            "cn_name": l.ingredient.cn_name,
            "inci_name": l.ingredient.inci_name,
            "position": l.position,
            "safety_risk": l.safety_risk,
            "is_active": l.is_active,
            "purpose": l.purpose,
            "has_evidence": l.ingredient_id in ids_with_evidence,
        } for l in links],
        "claims": [_claim_dict(c) for c in claims],
    }


@app.get("/api/products/{product_id}/concentration")
def product_concentration(product_id: int, db: Session = Depends(get_db)):
    """浓度推断结果 + 剂量达标判定 + 每起效成本。

    浓度为模型估计值（推断引擎按位次/先验约束采样的 p5/p95 区间），非实测；
    dose.verdict 为估计区间与文献起效浓度的相对关系（effective/insufficient/
    uncertain/unknown/trace_level，trace_level 表示微量线以下 ppm 级可能起效、依赖原料披露）。
    产品级 price/spec 为人工采样的官方零售价与主规格；estimates[].cost_per_effective_dose
    为按起效浓度折算的每日使用成本（元/天，按 1ml 用量，估计值，折算基准优先官方
    披露锚点、无披露取推断区间中点，起效线取该成分最低文献起效浓度），无数据时为 None。
    无官方降序成分表的产品未推断，返回 inferred=false。
    """
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    estimates = dose_verdicts(db, product_id)
    if estimates is None:
        return {"product_id": product_id, "inferred": False,
                "reason": "无官方降序成分表，未推断"}
    return {"product_id": product_id, "inferred": True,
            "price": p.price_current, "spec": p.spec,
            "estimates": estimates}


@app.get("/api/products/{product_id}/market")
def product_market(product_id: int, db: Session = Depends(get_db)):
    """口碑/好价时间序列（当前来源 smzdm 好价页）：最新快照 + 历史点。

    value_ratio 为值率（smzdm 投票，值友「值/不值」投票百分比），不是电商好评率；
    price 为该渠道好价成交价（促销价有时效，过期件在 estimate_note 标注）；
    部分日期仅月日、年份按采集日推断（估计值，见 estimate_note）。
    无快照时 latest=null、history=[]。
    """
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    snaps = (db.query(MarketSnapshot)
             .filter_by(product_id=p.id)
             .order_by(MarketSnapshot.date.desc(), MarketSnapshot.id.desc()).all())

    def _snap(s: MarketSnapshot) -> dict:
        return {"date": s.date.isoformat(), "source": s.source, "price": s.price,
                "value_ratio": s.value_ratio, "comment_count": s.comment_count,
                "estimate_note": s.estimate_note}

    return {"product_id": product_id,
            "latest": _snap(snaps[0]) if snaps else None,
            "history": [_snap(s) for s in snaps[1:]],
            "note": "value_ratio 为值率（smzdm 投票）；价格为渠道好价，促销价有时效"}


@app.get("/api/products/{product_id}/fingerprint")
def product_fingerprint(product_id: int, db: Session = Depends(get_db)):
    """功效指纹（总纲 I3）：功效空间稀疏向量，维度得分 = Σ(剂量因子 × 证据强度)。

    维度为规范功效族（efficacy_canonical）；法规类与防腐功效族断言不计分，
    仅在 detail 中标注 excluded/exclude_reason（coverage.excluded_count 计数）。
    分值为相对排序信号，非功效承诺；每维度的剂量口径见 detail[].dose_basis
    （推断区间 / 未知剂量 / 无起效浓度基准 / 微量线 ppm 口径）。
    coverage.dimensions 为非零维数。
    """
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    result = compute_fingerprint(db, product_id)
    result["coverage"]["dimensions"] = len(result["fingerprint"])
    return {"product_id": product_id, **result}


@app.get("/api/rankings/efficacy")
def efficacy_ranking(canon: str, limit: int = Query(20, ge=1, le=100),
                     db: Session = Depends(get_db)):
    """功效产品榜：按成分证据族（efficacy_canonical）对产品排名（首页/排行榜页数据源）。

    排名分 = 该族有断言的成分数 ×1 + 真人级证据断言数 ×3
    （真人级 = evidence_level ∈ human_rct/human_ct/human_open）；同分按产品 id 升序。
    只含该族有断言命中的产品；total 为命中产品总数（不受 limit 截断）。
    口径同功效指纹：法规类断言（evidence_level=regulation）与原料商宣称断言
    （evidence.type=supplier）不计入；efficacy_canonical 为 NULL 的断言按
    canonicalize 实时映射兜底。分数为成分证据强度的相对排序信号，非效果排名。
    """
    if canon not in RANKING_CANONS:
        raise HTTPException(status_code=422, detail=f"未知功效族: {canon}")
    # SQL 聚合下推主路径：efficacy_canonical 列已回填（2026-08-15 实测真实库
    # NULL 占比 0/2211），直接按列 group by，避免全量 join 后 Python 内存聚合
    # （旧实现真实库 33-43s）。evidence_level 可能为 NULL，SQL NULL != 'regulation'
    # 为 UNKNOWN 会被误排除，故显式保留 NULL（与原 Python `== REGULATION` 语义一致）。
    not_regulation = or_(EfficacyAssertion.evidence_level.is_(None),
                         EfficacyAssertion.evidence_level != REGULATION)
    human_case = case(
        (EfficacyAssertion.evidence_level.in_(HUMAN_EVIDENCE_LEVELS), 1), else_=0)
    rows = db.execute(
        select(ProductIngredient.product_id,
               func.count(func.distinct(ProductIngredient.ingredient_id)),
               func.sum(human_case))
        .join(EfficacyAssertion,
              EfficacyAssertion.ingredient_id == ProductIngredient.ingredient_id)
        .join(Evidence, Evidence.id == EfficacyAssertion.evidence_id)
        .where(EfficacyAssertion.efficacy_canonical == canon,
               not_regulation,
               Evidence.type != EvidenceType.SUPPLIER)
        .group_by(ProductIngredient.product_id)
    ).all()
    agg: dict[int, list[int]] = {  # product_id -> [成分命中数, 真人级断言数]
        pid: [hits, human or 0] for pid, hits, human in rows
    }
    # canonicalize 兜底：canonical 为 NULL 的断言无法在 SQL 侧映射（Python 函数），
    # 单独扫 NULL 子集；命中的产品整产品回退 Python 重算（覆盖 SQL 结果），
    # 保证「成分数按集合去重」语义与纯 Python 实现完全一致；真实库 NULL=0 时
    # 此分支零开销。
    null_rows = db.execute(
        select(ProductIngredient.product_id, ProductIngredient.ingredient_id,
               EfficacyAssertion.efficacy, EfficacyAssertion.evidence_level)
        .join(EfficacyAssertion,
              EfficacyAssertion.ingredient_id == ProductIngredient.ingredient_id)
        .join(Evidence, Evidence.id == EfficacyAssertion.evidence_id)
        .where(EfficacyAssertion.efficacy_canonical.is_(None),
               not_regulation,
               Evidence.type != EvidenceType.SUPPLIER)
    ).all()
    fallback_pids = {pid for pid, _iid, efficacy, _lvl in null_rows
                     if canonicalize(efficacy) == canon}
    for pid in fallback_pids:
        prows = db.execute(
            select(ProductIngredient.ingredient_id, EfficacyAssertion)
            .join(EfficacyAssertion,
                  EfficacyAssertion.ingredient_id == ProductIngredient.ingredient_id)
            .options(joinedload(EfficacyAssertion.evidence))
            .where(ProductIngredient.product_id == pid)
        ).unique().all()
        ingredients: set[int] = set()
        human = 0
        for iid, a in prows:
            canonical = a.efficacy_canonical or canonicalize(a.efficacy)
            if canonical != canon:
                continue
            if a.evidence_level == REGULATION or a.evidence.type == EvidenceType.SUPPLIER:
                continue
            ingredients.add(iid)
            if a.evidence_level in HUMAN_EVIDENCE_LEVELS:
                human += 1
        if ingredients:
            agg[pid] = [len(ingredients), human]
        else:
            agg.pop(pid, None)
    ranked = sorted(
        ((pid, s[0], s[1]) for pid, s in agg.items()),
        key=lambda t: (-(t[1] + 3 * t[2]), t[0]),
    )
    page = ranked[:limit]
    products = {p.id: p for p in db.execute(
        select(Product).where(Product.id.in_([pid for pid, _, _ in page]))
    ).scalars()} if page else {}
    items = [{
        "id": pid, "name": products[pid].name, "brand": products[pid].brand,
        "score": hits + 3 * human, "ingredient_hits": hits, "human_evidence": human,
    } for pid, hits, human in page]
    return {"canon": canon, "total": len(ranked), "items": items}


@app.get("/api/products/{product_id}/similar")
def product_similar(product_id: int, k: int = Query(5, ge=1, le=50),
                    db: Session = Depends(get_db)):
    """成分表相似产品 Top-k（BGE-M3 嵌入 + Faiss，score 为余弦相似度）。
    索引未构建时 similar=null + reason 降级，不报错。
    """
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    hits = search_products(product_id, k=k)
    if hits is None:
        return {"product_id": product_id, "similar": None, "reason": "相似索引未构建"}
    rows = (db.execute(select(Product).where(Product.id.in_([h["product_id"] for h in hits])))
            .scalars().all()) if hits else []
    by_id = {r.id: r for r in rows}
    similar = [
        {"id": h["product_id"], "name": by_id[h["product_id"]].name,
         "brand": by_id[h["product_id"]].brand, "score": h["score"]}
        for h in hits if h["product_id"] in by_id  # 索引与库可能短暂不一致，跳过已删实体
    ]
    return {"product_id": product_id, "similar": similar}


@app.get("/api/products/{product_id}/similar-levels")
def product_similar_levels(product_id: int, k: int = Query(5, ge=1, le=50),
                           db: Session = Depends(get_db)):
    """三级相似产品（总纲 I3「诚实版」相似性报告）——真平替的技术底座。

    - l1 成分集合相似（确定性）：Jaccard(成分集合)，附 shared/union 可复算；
    - l2 剂量级相似：推断区间中点向量的 min 加权余弦；浓度为模型估计值，
      无推断浓度的产品不参与比对，目标无推断时 available=false 诚实降级；
    - l3 功效级相似：功效指纹余弦（排除「其他」维），相对排序信号非功效承诺，
      附共有功效维数 dimensions 与主要共享功效方向 top_shared_dims。
    """
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    return {
        "product_id": product_id,
        "l1": level1_jaccard(db, product_id, k=k),
        "l2": level2_dose(db, product_id, k=k),
        "l3": level3_fingerprint(db, product_id, k=k),
        "note": "功效指纹基于 35+ 成分证据库，覆盖深度见各产品 coverage",
    }


@app.get("/api/products/{product_id}/evidence-profile")
def product_evidence_profile(product_id: int, db: Session = Depends(get_db)):
    """证据充分度面板（借鉴 EWG「数据充分度」维度）：产品功效断言按证据层级分布。

    全部 9 个层级键都返回（含 0 计数），按证据强度默认分降序；unknown 如实展示
    （「不知道」是一等公民，不隐藏）；ratio = count / assertions_total。
    前端据此渲染分布条与分级徽章（label 已附中文名）。
    """
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    return {"product_id": product_id, **evidence_profile(db, product_id)}


@app.get("/api/products/{product_id}/substitutes")
def product_substitutes(product_id: int, k: int = Query(5, ge=1, le=50),
                        db: Session = Depends(get_db)):
    """白盒平替得分卡：成分+功效+价格三维组合得分，每维可拆解（借鉴匹配得分卡，白盒化）。

    score = 归一化权重加权和（默认 成分 0.5 / 功效 0.3 / 价格 0.2），任一维不可用时
    该维 null 且权重在可用维上重归一化（weights_used 记录实际权重，诚实降级不伪造）。
    零成分交集产品不入选；目标无成分表时 substitutes=[] + reason 降级。
    分数为相对排序信号，非功效承诺。
    """
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    return {"product_id": product_id, **substitute_scorecard(db, product_id, k=k),
            "note": "分数为成分/功效/价格三维的相对排序信号，非功效承诺；缺失维度诚实降级"}


@app.get("/api/ingredients/{ingredient_id}/penetration")
def ingredient_penetration(ingredient_id: int, db: Session = Depends(get_db)):
    """成分渗透率统计（借鉴 INCI Beauty「出现在 X% 产品中」）。

    penetration = 含该成分的产品数 / 库中有成分表的产品总数（round 4）；
    avg_position 只统计 position 非空的关联（NULL 位次不计入），无则为 null。
    """
    ing = db.get(Ingredient, ingredient_id)
    if ing is None:
        raise HTTPException(status_code=404, detail="成分不存在")
    total = (db.query(func.count(func.distinct(ProductIngredient.product_id)))
             .scalar()) or 0
    cnt, avg_pos = (db.query(func.count(func.distinct(ProductIngredient.product_id)),
                             func.avg(ProductIngredient.position))
                    .filter(ProductIngredient.ingredient_id == ingredient_id).one())
    return {
        "ingredient_id": ingredient_id,
        "inci_name": ing.inci_name, "cn_name": ing.cn_name,
        "product_count": cnt, "total_products": total,
        "penetration": round(cnt / total, 4) if total else 0,
        "avg_position": round(avg_pos, 1) if avg_pos is not None else None,
        "note": "渗透率 = 含该成分的产品数 / 库中有成分表的产品总数",
    }


@app.get("/api/ingredients/{ingredient_id}/similar")
def ingredient_similar(ingredient_id: int, k: int = Query(5, ge=1, le=50),
                       db: Session = Depends(get_db)):
    """证据文本相似成分 Top-k（BGE-M3 嵌入 + Faiss）。索引未构建时 similar=null 降级。"""
    ing = db.get(Ingredient, ingredient_id)
    if ing is None:
        raise HTTPException(status_code=404, detail="成分不存在")
    hits = search_ingredients(ingredient_id, k=k)
    if hits is None:
        return {"ingredient_id": ingredient_id, "similar": None, "reason": "相似索引未构建"}
    rows = (db.execute(select(Ingredient).where(Ingredient.id.in_([h["ingredient_id"] for h in hits])))
            .scalars().all()) if hits else []
    by_id = {r.id: r for r in rows}
    similar = [
        {"id": h["ingredient_id"], "inci_name": by_id[h["ingredient_id"]].inci_name,
         "cn_name": by_id[h["ingredient_id"]].cn_name, "score": h["score"]}
        for h in hits if h["ingredient_id"] in by_id
    ]
    return {"ingredient_id": ingredient_id, "similar": similar}


# ---------- 成分问答（prompt RAG 基线，总纲模型层阶段 1） ----------


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    verify: bool = True

    @field_validator("question")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("question 不能为空")
        return v


def get_llm_gateway() -> LLMGateway:
    """按环境变量构建 LLM 网关（默认 local 通道）；测试可覆盖注入假件。"""
    return LLMGateway()


@app.post("/api/chat")
def chat(req: ChatRequest, db: Session = Depends(get_db),
         gateway: LLMGateway = Depends(get_llm_gateway)):
    """成分问答：确定性检索组装编号证据包 → LLM 按铁律引用 [n] 回答。

    citations_used 为答案解析出的引用编号；hallucinated_citations 为证据包外
    编号（如实报告，不删改答案）。verify=true（默认）时再跑生成者-验证者
    校验循环（RARR ≤2 轮），响应增加 verification 字段（final_answer/
    verification/rewritten/rounds），answer 字段保留原逻辑产物不删改。
    LLM 通道不可达时 503 诚实降级。
    """
    try:
        result = answer_question(db, gateway, req.question)
        if req.verify:
            result["verification"] = verify_answer(db, gateway, req.question, result)
        return result
    except LLMUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))


# ---------- 圆桌四 Agent 核验（总纲支柱 4，信息不对称分工，SSE 事件流） ----------


class RoundtableRequest(BaseModel):
    product_name: str = Field(min_length=1, max_length=200)

    @field_validator("product_name")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("product_name 不能为空")
        return v


@app.post("/api/roundtable")
def roundtable(req: RoundtableRequest, db: Session = Depends(get_db),
               gateway: LLMGateway = Depends(get_llm_gateway)):
    """圆桌四 Agent 核验：成分专家 → 法规合规官 → 文献核验官 → 剂量推断师 → 五级裁决。

    SSE 事件流（text/event-stream，逐事件 `data: {json}`，结束后 `data: [DONE]`）：
    start（产品定位）→ 每角色 tool_call×n + speak → verdict（五级判定组合表，
    附宣称/证据/剂量工具数据）。产品未找到或 LLM 不可达时流内 error 事件降级。
    """
    def _stream():
        for ev in run_roundtable(db, gateway, req.product_name):
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


# ---------- 图片鉴伪（赛题「多模态」：AI 生图检测，代理转发视觉 sidecar） ----------


@app.post("/api/detect-image")
def detect_image(file: UploadFile = File(...)):
    """AI 生图检测：转发视觉 sidecar（DINOv2 ViT-S/14 + 线性探针，独立 torch 进程）。

    返回 {score, verdict(ai/real/uncertain), threshold, note}；score 为模型估计值，
    仅供演示。sidecar 非 200 透传其错误语义；sidecar 不可达时 503 诚实降级。
    """
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="空文件")
    try:
        status, payload = vision_detect.detect_image(
            content,
            file.filename or "upload",
            file.content_type or "application/octet-stream",
        )
    except vision_detect.VisionUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    if status != 200:
        if not 400 <= status < 600:
            status = 502
        raise HTTPException(status_code=status, detail=payload.get("detail", "检测失败"))
    return payload


# 高保真首页原型（lab/hero-demo 构建产物）挂在 /lab
app.mount("/lab", StaticFiles(directory="lab/hero-demo/dist", html=True), name="lab")

# 页面线框参考图（lab/wireframes 纯静态，设计评审用）
app.mount("/wireframes", StaticFiles(directory="lab/wireframes", html=True), name="wireframes")


# 无尾斜杠直达路径重定向（StaticFiles 挂载根不匹配无斜杠路径，会落进 "/" 挂载 404）
@app.get("/lab", include_in_schema=False)
@app.get("/wireframes", include_in_schema=False)
def static_root_redirect(request: Request):
    return RedirectResponse(f"{request.url.path}/")


# 静态前端（/web 目录，纯静态页，数据全部经 /api 获取）
app.mount("/", StaticFiles(directory="web", html=True), name="web")
