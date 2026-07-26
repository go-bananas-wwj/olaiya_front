"""成分真言 API。启动：仓库根目录
PYTHONPATH=backend .venv/bin/python -m uvicorn app.main:app --reload --port 8000
"""

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .db import SessionLocal, init_db
from .models.ingredient import EfficacyAssertion, Ingredient

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
