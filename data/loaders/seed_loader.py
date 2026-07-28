"""种子数据加载器：幂等写入证据/成分/断言/产品。

产品中出现的未登记成分自动建 stub（cn_name 暂用 INCI 名，先验留空）。
CLI：仓库根目录执行  PYTHONPATH=backend .venv/bin/python -m data.loaders.seed_loader
"""

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.models.product import Product, ProductIngredient

SEED_PATH = Path(__file__).resolve().parents[1] / "seed" / "seed_data.json"
ORDERED_PATH = Path(__file__).resolve().parents[1] / "seed" / "ordered_products.json"


def _load_evidence(session: Session, items: list[dict]) -> dict[str, Evidence]:
    """按 title 幂等 upsert，返回 title -> Evidence 映射。"""
    by_title: dict[str, Evidence] = {}
    for item in items:
        ev = session.query(Evidence).filter_by(title=item["title"]).one_or_none()
        if ev is None:
            ev = Evidence(
                type=EvidenceType(item["type"]),
                title=item["title"],
                source=item["source"],
                year=item.get("year"),
                url=item.get("url"),
                excerpt=item.get("excerpt"),
            )
            session.add(ev)
            session.flush()
        by_title[item["title"]] = ev
    return by_title


def _get_or_create_ingredient(session: Session, inci_name: str, cn_name: str | None = None) -> Ingredient:
    ing = session.query(Ingredient).filter_by(inci_name=inci_name).one_or_none()
    if ing is None:
        ing = Ingredient(inci_name=inci_name, cn_name=cn_name or inci_name)
        session.add(ing)
        session.flush()
    return ing


def _load_ingredients(session: Session, items: list[dict], evidence_by_title: dict[str, Evidence]) -> None:
    prior_fields = ("iecic_max_leave_on", "iecic_max_rinse_off", "legal_cap",
                    "cir_conc_low", "cir_conc_high", "sccs_limit")
    for item in items:
        ing = _get_or_create_ingredient(session, item["inci_name"], item["cn_name"])
        ing.cas_no = item.get("cas_no")
        for f in prior_fields:
            if item.get(f) is not None:
                setattr(ing, f, item[f])
        for a in item.get("assertions", []):
            ev = evidence_by_title[a["evidence_title"]]
            exists = (session.query(EfficacyAssertion)
                      .filter_by(ingredient_id=ing.id, efficacy=a["efficacy"], evidence_id=ev.id)
                      .one_or_none())
            if exists is None:
                session.add(EfficacyAssertion(
                    ingredient_id=ing.id,
                    efficacy=a["efficacy"],
                    evidence_id=ev.id,
                    effective_conc_low=a.get("effective_conc_low"),
                    effective_conc_high=a.get("effective_conc_high"),
                    note=a.get("note"),
                ))


def _load_products(session: Session, items: list[dict]) -> None:
    for item in items:
        product = (session.query(Product)
                   .filter_by(name=item["name"], brand=item["brand"]).one_or_none())
        if product is None:
            product = Product(
                name=item["name"], brand=item["brand"],
                category=item.get("category"), nmpa_id=item.get("nmpa_id"),
                price_current=item.get("price_current"), note=item.get("note"),
            )
            session.add(product)
            session.flush()
        existing = session.query(ProductIngredient).filter_by(product_id=product.id).count()
        if existing:  # 已有成分表则跳过，保证幂等
            continue
        disclosed = item.get("disclosed", {})
        position = 0
        for inci in item.get("ingredients", []):
            position += 1
            ing = _get_or_create_ingredient(session, inci)
            session.add(ProductIngredient(product_id=product.id, ingredient_id=ing.id,
                                          position=position, is_trace=False,
                                          disclosed_conc=disclosed.get(inci)))
        for inci in item.get("trace_ingredients", []):
            position += 1
            ing = _get_or_create_ingredient(session, inci)
            session.add(ProductIngredient(product_id=product.id, ingredient_id=ing.id,
                                          position=position, is_trace=True,
                                          disclosed_conc=disclosed.get(inci)))


def load_seed(session: Session, path: Path = SEED_PATH) -> None:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    evidence_by_title = _load_evidence(session, data["evidence"])
    _load_ingredients(session, data["ingredients"], evidence_by_title)
    _load_products(session, data["products"])


def load_ordered_products(session: Session, path: Path = ORDERED_PATH) -> None:
    """官方降序成分表产品集：position 为 1-based 真实降序，disclosed 锚点写入 disclosed_conc。

    幂等：产品按 name+brand 查重，已有成分关联则跳过；ingredient_source_url 存 product.source_url。
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for item in data["products"]:
        product = (session.query(Product)
                   .filter_by(name=item["name"], brand=item["brand"]).one_or_none())
        if product is None:
            product = Product(
                name=item["name"], brand=item["brand"],
                category=item.get("category"),
                price_current=item.get("price_current"), note=item.get("note"),
                source_url=item.get("ingredient_source_url"),
            )
            session.add(product)
            session.flush()
        existing = session.query(ProductIngredient).filter_by(product_id=product.id).count()
        if existing:  # 已有成分表则跳过，保证幂等
            continue
        disclosed = item.get("disclosed", {})
        position = 0
        for inci in item.get("ingredients", []):
            position += 1
            ing = _get_or_create_ingredient(session, inci)
            session.add(ProductIngredient(product_id=product.id, ingredient_id=ing.id,
                                          position=position, is_trace=False,
                                          disclosed_conc=disclosed.get(inci)))
        for inci in item.get("trace_ingredients", []):
            position += 1
            ing = _get_or_create_ingredient(session, inci)
            session.add(ProductIngredient(product_id=product.id, ingredient_id=ing.id,
                                          position=position, is_trace=True,
                                          disclosed_conc=disclosed.get(inci)))


def main() -> None:
    init_db()
    with SessionLocal() as s:
        load_seed(s)
        load_ordered_products(s)
        s.commit()
        anchors = s.query(ProductIngredient).filter(ProductIngredient.disclosed_conc.isnot(None)).count()
        print(f"evidence={s.query(Evidence).count()} "
              f"ingredients={s.query(Ingredient).count()} "
              f"assertions={s.query(EfficacyAssertion).count()} "
              f"products={s.query(Product).count()} "
              f"disclosed_anchors={anchors}")


if __name__ == "__main__":
    main()
