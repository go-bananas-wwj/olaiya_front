"""成分真言 API。启动：仓库根目录
PYTHONPATH=backend .venv/bin/python -m uvicorn app.main:app --reload --port 8000
"""

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .db import SessionLocal, init_db
from .models.ingredient import EfficacyAssertion, Ingredient
from .models.product import Product, ProductClaim, ProductIngredient

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


@app.get("/api/ingredients")
def list_ingredients(q: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Ingredient).order_by(Ingredient.id)
    if q:
        like = f"%{q}%"
        stmt = select(Ingredient).where(
            or_(Ingredient.cn_name.like(like), Ingredient.inci_name.like(like))
        ).order_by(Ingredient.id)
    rows = db.execute(stmt).scalars().all()
    return [{"id": i.id, "inci_name": i.inci_name, "cn_name": i.cn_name, "cas_no": i.cas_no}
            for i in rows]


@app.get("/api/ingredients/{ingredient_id}")
def ingredient_detail(ingredient_id: int, db: Session = Depends(get_db)):
    ing = db.get(Ingredient, ingredient_id)
    if ing is None:
        raise HTTPException(status_code=404, detail="成分不存在")
    assertions = (db.query(EfficacyAssertion)
                  .filter_by(ingredient_id=ing.id)
                  .order_by(EfficacyAssertion.id).all())
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
def list_products(q: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Product).order_by(Product.brand, Product.id)
    if q:
        like = f"%{q}%"
        stmt = (select(Product)
                .where(or_(Product.name.like(like), Product.brand.like(like)))
                .order_by(Product.brand, Product.id))
    rows = db.execute(stmt).scalars().all()
    out = []
    for p in rows:
        claim_count = db.query(ProductClaim).filter_by(product_id=p.id).count()
        ing_count = db.query(ProductIngredient).filter_by(product_id=p.id).count()
        out.append({
            "id": p.id, "name": p.name, "brand": p.brand,
            "nmpa_id": p.nmpa_id, "claim_count": claim_count,
            "ingredient_count": ing_count,
        })
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
    return {
        "id": p.id,
        "name": p.name,
        "brand": p.brand,
        "category": p.category,
        "nmpa_id": p.nmpa_id,
        "price_current": p.price_current,
        "note": p.note,
        "ingredients": [{
            "cn_name": l.ingredient.cn_name,
            "inci_name": l.ingredient.inci_name,
            "position": l.position,
            "safety_risk": l.safety_risk,
            "is_active": l.is_active,
            "purpose": l.purpose,
        } for l in links],
        "claims": [_claim_dict(c) for c in claims],
    }


# 静态前端（/web 目录，纯静态页，数据全部经 /api 获取）
app.mount("/", StaticFiles(directory="web", html=True), name="web")
