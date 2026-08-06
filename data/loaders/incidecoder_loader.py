"""INCIDecoder 采集数据加载器：把 data/raw/incidecoder/**/*.json 导入数据库。

映射规则：
- product：**身份按 product_slug（即 source_url）**；同名不同 slug 的配方变体分别建档
  （变体名带 slug 后缀），保证入库成分表与 source_url 指向的页面严格同源；
  source_url 只在新建/原本为空时写，绝不被另一变体改写。
- brand：按 brand_slug 归一到库内既有主名（映射表在 collect_incidecoder.BRANDS，
  纯中文优先），不采页面/旧 JSON 里的双语写法。
- 成分关联：**position 按页面顺序 1-based 如实填**——INCIDecoder 成分表为包装标签降序。
- 成分匹配：inci_name 大小写无关匹配；水变体（AQUA / AQUA (WATER) / AQUA/WATER /
  AQUA/WATER/EAU）归一到 WATER；匹配不到建 stub（cn_name 暂以 INCI 填充，**不机翻**），
  计入 stats["pending_cn"] 待后续专门中文化。
- 不采宣称：INCIDecoder 的产品描述不是官方宣称，不入 product_claims。

运行：PYTHONPATH="backend:." .venv/bin/python data/loaders/incidecoder_loader.py [目录]
"""

import json
import re
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models.ingredient import Ingredient
from app.models.product import Product, ProductIngredient
from data.tools.collect_incidecoder import BRANDS

RAW_ROOT = Path(__file__).resolve().parents[1] / "raw" / "incidecoder"

_WS = re.compile(r"\s+")
_WATER_TOKENS = {"AQUA", "WATER", "EAU"}


def _norm_name(name: str) -> str:
    """产品名归一化：压空白 + 小写，用于 (brand, name) 去重比对。"""
    return _WS.sub(" ", name).strip().casefold()


def canonical_inci(inci_name: str) -> str:
    """成分名归一：全部由 AQUA/WATER/EAU 组成的写法（含斜杠/括号变体）归一到 WATER。"""
    tokens = {t for t in re.split(r"[\s/()]+", inci_name.upper()) if t}
    if tokens and tokens <= _WATER_TOKENS:
        return "WATER"
    return inci_name


def _get_or_create_ingredient(session: Session, inci_name: str, stats: dict) -> Ingredient:
    """按归一 INCI 名（大小写无关）匹配现有成分；没有则建 stub 并计「待中文化」。"""
    canon = canonical_inci(inci_name)
    ing = (session.query(Ingredient)
           .filter(func.upper(Ingredient.inci_name) == canon.upper())
           .order_by(Ingredient.id).first())
    if ing is None:
        ing = Ingredient(inci_name=canon, cn_name=canon)  # 不机翻，后续专门任务补
        session.add(ing)
        session.flush()
        stats["pending_cn"] = stats.get("pending_cn", 0) + 1
        stats.setdefault("pending_cn_names", set()).add(canon)
    return ing


def _find_product(session: Session, brand: str, name: str, url: str, slug: str):
    """定位产品行：(product, is_variant_new)。

    1. source_url 精确命中 → 本行（幂等重跑）。
    2. 同品牌同名候选：无来源页（或其他来源）→ 跨源合并；来源页是另一 slug → 变体，建新行。
    """
    product = session.query(Product).filter_by(source_url=url).one_or_none()
    if product is not None:
        return product, False
    target = _norm_name(name)
    for cand in session.query(Product).filter_by(brand=brand).all():
        if _norm_name(cand.name) != target:
            continue
        if not cand.source_url or "incidecoder.com/products/" not in cand.source_url:
            return cand, False  # 跨源合并（guidechem/种子行），补写 source_url
        # 已有指向另一 slug 的 INCIDecoder 行 → 配方变体，另行建档
        return None, True
    return None, False


def load_product(session: Session, data: dict, stats: dict | None = None) -> Product:
    """导入单个产品的解析 JSON，返回 Product。幂等。"""
    if stats is None:
        stats = {}
    slug = data["product_slug"]
    url = (data.get("source") or {}).get("url") or f"https://incidecoder.com/products/{slug}"
    brand = BRANDS.get(data.get("brand_slug") or "", data["brand"])
    name = data["name"]

    product, is_variant = _find_product(session, brand, name, url, slug)
    if product is None:
        if is_variant:  # 变体名带 slug 后缀，避免与主行混淆
            name = f"{name}（{slug}）"
        product = Product(name=name, brand=brand)
        session.add(product)
        session.flush()
    product.source_url = product.source_url or url  # 只补空，绝不覆盖另一变体的 url
    if not product.note:
        product.note = "INCIDecoder 成分表（包装标签降序，position 为真实位次）"

    # 成分关联：已有则跳过（幂等，不覆盖已有位次数据）
    if not session.query(ProductIngredient).filter_by(product_id=product.id).count():
        for item in data.get("ingredients", []):
            ing = _get_or_create_ingredient(session, item["inci_name"], stats)
            session.add(ProductIngredient(product_id=product.id, ingredient_id=ing.id,
                                          position=item["position"], is_trace=False))
    return product


def load_directory(session: Session, root: Path = RAW_ROOT) -> dict:
    """导入目录下全部产品 JSON，返回计数（含待中文化新成分数）。"""
    stats: dict = {"files": 0, "pending_cn": 0, "pending_cn_names": set()}
    # 排序键保证 base slug（如 xxx-cleanser）先于其数字后缀变体（xxx-cleanser-5）入库，
    # 让 base 行保留原名、变体行带后缀（纯展示顺序，不影响幂等性）
    for path in sorted(Path(root).glob("*/*.json"), key=lambda p: (len(p.stem), p.stem)):
        data = json.loads(path.read_text(encoding="utf-8"))
        load_product(session, data, stats=stats)
        stats["files"] += 1
    stats["products"] = session.query(Product).count()
    return stats


def main() -> None:
    import sys
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else RAW_ROOT
    init_db()
    with SessionLocal() as s:
        stats = load_directory(s, root)
        s.commit()
        links = s.query(ProductIngredient).count()
        print(f"files={stats['files']} products={stats['products']} "
              f"product_ingredients={links} 待中文化新成分={stats['pending_cn']}")
        if stats["pending_cn_names"]:
            print("待中文化清单（前 20）：" + ", ".join(sorted(stats["pending_cn_names"])[:20]))


if __name__ == "__main__":
    main()
