"""成分真言 API。启动（tmux，仓库根目录）：
tmux new-session -d -s cfz-web -c /root/workspace/olaiya \\
  "PYTHONPATH=backend .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8008"
（8000 端口被机器上其他程序占用，本项目统一用 8008；后台服务统一用 tmux，不用 nohup）
"""

import json
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .db import SessionLocal, init_db
from .models.evidence import Evidence
from .models.ingredient import EfficacyAssertion, Ingredient
from .models.product import Product, ProductClaim, ProductIngredient
from .services.dosecheck import dose_verdicts
from .services.llm_gateway import LLMGateway, LLMUnavailableError
from .services.rag_qa import answer_question
from .services.roundtable import run_roundtable
from .services.verify_loop import verify_answer
from .services.fingerprint import compute_fingerprint
from .services.similar_levels import level1_jaccard, level2_dose, level3_fingerprint
from .services.similarity import search_ingredients, search_products
from .services.transdermal import get_transdermal_info
from .services import vision_detect

# 成分理化映射（D3 透皮判定数据源）：启动时读入内存常量，避免每请求 IO
_CID_MAP_PATH = Path(__file__).resolve().parents[2] / "data" / "seed" / "cid_map.json"
CID_MAP: dict = json.loads(_CID_MAP_PATH.read_text(encoding="utf-8"))

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
                     db: Session = Depends(get_db)):
    stmt = select(Ingredient).order_by(Ingredient.id)
    if q:
        like = f"%{q}%"
        stmt = select(Ingredient).where(
            or_(Ingredient.cn_name.like(like), Ingredient.inci_name.like(like))
        ).order_by(Ingredient.id)
    rows = db.execute(stmt).scalars().all()
    out = []
    for i in rows:
        # 断言计数：has_evidence 过滤与 assertion_count 字段共用
        cnt = db.query(EfficacyAssertion).filter_by(ingredient_id=i.id).count()
        if has_evidence == "true" and cnt == 0:
            continue
        if has_evidence == "false" and cnt > 0:
            continue
        out.append({"id": i.id, "inci_name": i.inci_name, "cn_name": i.cn_name,
                    "cas_no": i.cas_no, "assertion_count": cnt})
    return out


@app.get("/api/ingredients/{ingredient_id}")
def ingredient_detail(ingredient_id: int, db: Session = Depends(get_db)):
    ing = db.get(Ingredient, ingredient_id)
    if ing is None:
        raise HTTPException(status_code=404, detail="成分不存在")
    assertions = (db.query(EfficacyAssertion)
                  .filter_by(ingredient_id=ing.id)
                  .order_by(EfficacyAssertion.id).all())
    # 含该成分的产品（经 ProductIngredient 关联去重，按产品 id 排序）
    links = (db.query(ProductIngredient)
             .filter_by(ingredient_id=ing.id)
             .order_by(ProductIngredient.product_id).all())
    products = []
    seen_product_ids = set()
    for l in links:
        if l.product_id in seen_product_ids:
            continue
        seen_product_ids.add(l.product_id)
        products.append({"id": l.product.id, "name": l.product.name, "brand": l.product.brand})
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
        },
        "assertions": [_assertion_dict(a) for a in assertions],
        "products": products,
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


@app.get("/api/products")
def list_products(q: str | None = None, brand: str | None = None,
                  has_claims: str | None = None, limit: int = 0,
                  db: Session = Depends(get_db)):
    stmt = select(Product)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Product.name.like(like), Product.brand.like(like)))
    if brand:
        stmt = stmt.where(Product.brand == brand)  # 品牌精确匹配
    stmt = stmt.order_by(Product.brand, Product.id)
    rows = db.execute(stmt).scalars().all()
    out = []
    for p in rows:
        claim_count = db.query(ProductClaim).filter_by(product_id=p.id).count()
        # 按是否存在功效宣称过滤
        if has_claims == "true" and claim_count == 0:
            continue
        if has_claims == "false" and claim_count > 0:
            continue
        ing_count = db.query(ProductIngredient).filter_by(product_id=p.id).count()
        out.append({
            "id": p.id, "name": p.name, "brand": p.brand,
            "nmpa_id": p.nmpa_id, "claim_count": claim_count,
            "ingredient_count": ing_count,
        })
    if limit > 0:  # 0 = 不限
        out = out[:limit]
    return out


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
    """浓度推断结果 + 剂量达标判定。

    浓度为模型估计值（推断引擎按位次/先验约束采样的 p5/p95 区间），非实测；
    dose.verdict 为估计区间与文献起效浓度的相对关系（effective/insufficient/
    uncertain/unknown/trace_level，trace_level 表示微量线以下 ppm 级可能起效、依赖原料披露）。
    无官方降序成分表的产品未推断，返回 inferred=false。
    """
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    estimates = dose_verdicts(db, product_id)
    if estimates is None:
        return {"product_id": product_id, "inferred": False,
                "reason": "无官方降序成分表，未推断"}
    return {"product_id": product_id, "inferred": True, "estimates": estimates}


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

# 静态前端（/web 目录，纯静态页，数据全部经 /api 获取）
app.mount("/", StaticFiles(directory="web", html=True), name="web")
