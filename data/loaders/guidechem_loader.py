"""盖德采集数据加载器：把 data/raw/guidechem/**/*.json 导入数据库。

映射规则：
- product：按 nmpa_id（无则 name+brand）幂等；brand 取搜索关键词；note 记录来源与功效列表。
- 成分关联：成分为中文名（镜像站无 INCI 英文名），按名字 get-or-create；
  **position 一律置 NULL**——镜像站成分是拼音排序，不是备案降序，禁止伪造位次。
- 产品宣称（ProductClaim）：按 (product_id, claim, eval_category, method_name) 幂等。
"""

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models.ingredient import Ingredient
from app.models.product import Product, ProductClaim, ProductIngredient

RAW_ROOT = Path(__file__).resolve().parents[1] / "raw" / "guidechem"


def _get_or_create_ingredient(session: Session, cn_name: str) -> Ingredient:
    """中文名成分 get-or-create（INCI 英文名后续用成分词典回补）。"""
    # 先按中文名命中正式成分（INCI 英文条目），避免与证据库双头；
    # 找不到再按 stub 形式（inci_name==中文名）查找，最后才建 stub
    ing = (session.query(Ingredient)
           .filter(Ingredient.cn_name == cn_name)
           .order_by(Ingredient.id).first())
    if ing is None:
        ing = session.query(Ingredient).filter_by(inci_name=cn_name).one_or_none()
    if ing is None:
        ing = Ingredient(inci_name=cn_name, cn_name=cn_name)
        session.add(ing)
        session.flush()
    return ing


def load_product(session: Session, data: dict) -> Product:
    """导入单个产品的解析 JSON，返回 Product。幂等。"""
    brand = data["search_brand"]
    product = None
    if data.get("nmpa_id"):
        product = session.query(Product).filter_by(nmpa_id=data["nmpa_id"]).one_or_none()
    if product is None:
        product = (session.query(Product)
                   .filter_by(name=data["name"], brand=brand).one_or_none())
    if product is None:
        product = Product(name=data["name"], brand=brand)
        session.add(product)
        session.flush()
    product.nmpa_id = data.get("nmpa_id") or product.nmpa_id
    reg = data.get("registration") or {}
    effs = "、".join(data.get("efficacies") or [])
    product.note = (f"功效: {effs}；备案人: {reg.get('registrant')}；"
                    f"备案日期: {reg.get('filing_date')}；"
                    f"来源: {data['source']['url']}（镜像 NMPA 公示，成分表为拼音序）")

    # 成分关联：已有则跳过（幂等），position=None（顺序未知）
    if not session.query(ProductIngredient).filter_by(product_id=product.id).count():
        for item in data.get("ingredients", []):
            ing = _get_or_create_ingredient(session, item["name"])
            session.add(ProductIngredient(product_id=product.id, ingredient_id=ing.id,
                                          position=None, is_trace=False,
                                          safety_risk=item.get("safety_risk"),
                                          is_active=item.get("is_active"),
                                          purpose=item.get("purpose")))

    # 宣称：按四元组幂等
    for c in data.get("claims", []):
        exists = (session.query(ProductClaim)
                  .filter_by(product_id=product.id, claim=c["claim"],
                             eval_category=c.get("eval_category"),
                             method_name=c.get("method_name"))
                  .one_or_none())
        if exists is None:
            session.add(ProductClaim(
                product_id=product.id, claim=c["claim"],
                eval_category=c.get("eval_category"),
                method_name=c.get("method_name"),
                method_source=c.get("method_source"),
                metric=c.get("metric"),
                test_period=c.get("test_period"),
                result_summary=c.get("result_summary"),
                institution=c.get("institution"),
            ))
    return product


def load_directory(session: Session, root: Path = RAW_ROOT) -> dict:
    """导入目录下全部 JSON，返回计数。"""
    counts = {"files": 0, "products": 0}
    for path in sorted(Path(root).rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        load_product(session, data)
        counts["files"] += 1
    counts["products"] = session.query(Product).count()
    return counts


def main() -> None:
    init_db()
    with SessionLocal() as s:
        counts = load_directory(s)
        s.commit()
        claims = s.query(ProductClaim).count()
        links = s.query(ProductIngredient).count()
        print(f"files={counts['files']} products={counts['products']} "
              f"claims={claims} product_ingredients={links}")


if __name__ == "__main__":
    main()
