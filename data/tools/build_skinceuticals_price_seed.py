"""修丽可官网价格种子构建器：采集 JSON ↔ 库内产品规则匹配 → 扩展 price_specs.json。

双通道确定性匹配（拿不准不匹配，记 unmatched 与候选，不猜）：
- 英文通道：slug（CEferulic/TripleLipidRestore242）归一键 == 库内英文名归一键
  （剥 SkinCeuticals 前缀、括号内容单独成键、去标点/重音、大写；2:4:2 → 242）
- 中文通道：官网 H1 中文名（含繁体，内置繁→简映射）归一 == 库内中文名归一

消歧（多候选时依序）：剔除 (Discontinued) 变体 → 剔除（…-2）slug 后缀重复行 →
有序产品（有位次关联）优先 → 有功效宣称优先 → 已有人工采样价格优先；仍不唯一则
unmatched。已存在于 price_specs.json（同 source_url）的条目不覆盖（人工核订优先）。

CLI：PYTHONPATH=backend .venv/bin/python data/tools/build_skinceuticals_price_seed.py [--write]
默认 dry-run 只打印匹配报告；--write 才更新 data/seed/price_specs.json。
匹配报告同时落 data/research/skinceuticals_price_match.json（含 unmatched 候选）。
"""

import argparse
import datetime
import json
import re
import unicodedata
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models.product import Product, ProductClaim, ProductIngredient

RAW_DIR = Path(__file__).resolve().parents[1] / "raw" / "skinceuticals_cn"
PRICE_PATH = Path(__file__).resolve().parents[1] / "seed" / "price_specs.json"
REPORT_PATH = Path(__file__).resolve().parents[1] / "research" / "skinceuticals_price_match.json"

# 官网 H1 出现的繁体字 → 简体（按 2026-08 采集数据观察集合，非通用 opencc）
_TW2CN = str.maketrans("維間緊緻豐潤護復顏膚淨潔噴霧華曬專條時麵",
                       "维间紧致丰润护复颜肤净洁喷雾华晒专条时面")

_PAREN_RE = re.compile(r"[（(][^）)]*[）)]")
_NON_KEY_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]+")
_BRAND_PREFIX_RE = re.compile(r"^(?:SkinCeuticals|修丽可)\s*", re.I)


def _fold(s: str) -> str:
    """归一：NFKD 去重音、繁转简、去非字母数字/CJK、大写。"""
    s = unicodedata.normalize("NFKD", s.translate(_TW2CN))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return _NON_KEY_RE.sub("", s).upper()


def slug_key(slug: str) -> str:
    """官网 slug 归一键：TripleLipidRestore242 → TRIPLELIPIDRESTORE242。"""
    return _fold(slug)


def product_keys(name: str) -> list[str]:
    """库内产品名 → 归一键列表：整体（剥 SkinCeuticals/修丽可前缀、去括号）
    + 每个括号内容单独成键（如「紫米精华（H.A. Intensifier）」的英文名键）。"""
    variants = [_PAREN_RE.sub("", name)] + list(_PAREN_RE.findall(name))
    keys = []
    for v in variants:
        k = _fold(_BRAND_PREFIX_RE.sub("", v.strip("（）() ")))
        if k:
            keys.append(k)
    return list(dict.fromkeys(keys))


def _has_position(session: Session, pid: int) -> bool:
    return (session.query(ProductIngredient.id)
            .filter(ProductIngredient.product_id == pid,
                    ProductIngredient.position.isnot(None)).first()) is not None


def _has_claims(session: Session, pid: int) -> bool:
    return session.query(ProductClaim.id).filter_by(product_id=pid).first() is not None


def _disambiguate(session: Session, cands: list[Product]) -> Product | None:
    """多候选依序消歧；无法唯一则 None（不猜）。"""
    if len(cands) <= 1:
        return cands[0] if cands else None
    nondisc = [p for p in cands if "(Discontinued)" not in p.name]
    if nondisc:
        cands = nondisc
    clean = [p for p in cands if not re.search(r"（[^）]*-\d+）", p.name)]  # （…-2）后缀重复行
    if clean:
        cands = clean
    if len(cands) == 1:
        return cands[0]
    ordered = [p for p in cands if _has_position(session, p.id)]
    if ordered:
        cands = ordered
    if len(cands) == 1:
        return cands[0]
    with_claims = [p for p in cands if _has_claims(session, p.id)]
    if with_claims:
        cands = with_claims
    if len(cands) == 1:
        return cands[0]
    priced = [p for p in cands if p.price_current is not None]
    if priced:
        cands = priced
    return cands[0] if len(cands) == 1 else None


def match_all(session: Session) -> dict:
    """采集 JSON × 库内修丽可产品 → {matched: [{slug, product, page}], unmatched: [...]}"""
    pages = []
    for f in sorted(RAW_DIR.glob("*.json")):
        pages.append(json.loads(f.read_text(encoding="utf-8")))
    products = session.query(Product).filter(Product.brand.like("%修丽可%")).all()
    key_index: dict[str, list[Product]] = {}
    for p in products:
        for k in product_keys(p.name):
            key_index.setdefault(k, []).append(p)
    matched, unmatched = [], []
    for page in pages:
        cands: dict[int, Product] = {}
        for p in key_index.get(slug_key(page["slug"]), []):  # 英文通道
            cands[p.id] = p
        cn_key = _fold(_BRAND_PREFIX_RE.sub("", (page.get("name_cn") or "").strip()))
        if cn_key:  # 中文通道（官网 H1 全名 ↔ 库内中文名）
            for p in products:
                if cn_key in product_keys(p.name):
                    cands[p.id] = p
        pick = _disambiguate(session, list(cands.values()))
        if pick is not None:
            matched.append({"slug": page["slug"], "product": pick, "page": page,
                            "candidates": len(cands)})
        else:
            unmatched.append({"slug": page["slug"], "name_cn": page.get("name_cn"),
                              "price": page.get("price"),
                              "candidates": [{"id": p.id, "name": p.name}
                                             for p in cands.values()]})
    return {"matched": matched, "unmatched": unmatched}


def build_items(result: dict, existing_urls: set[str]) -> list[dict]:
    """匹配成功且 price_specs 尚无同 source_url 条目的 → price_specs item 列表。"""
    items = []
    for m in result["matched"]:
        page, p = m["page"], m["product"]
        url = page["source"]["url"]
        if url in existing_urls:
            continue
        items.append({
            "match": p.name,
            "product_id": p.id,  # 精确通道：规则匹配报告给出的 id，防 match 串漂移
            "brand": "修丽可",
            "price": page["price"],
            "spec": (page.get("spec") or "").replace("ML", "ml") or None,
            "price_note": "官方标价（修丽可中国官网产品页，2026-08-10 机器采集；站点陈旧 "
                          "sitemap lastmod 2023-06，价格现行性另经抽查）",
            "source_url": url,
            "buy_url": url,
        })
    return items


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="实际更新 price_specs.json（默认 dry-run）")
    args = ap.parse_args()
    init_db()
    with SessionLocal() as s:
        result = match_all(s)
    data = json.loads(PRICE_PATH.read_text(encoding="utf-8"))
    existing_urls = {it.get("source_url") for it in data["items"]}
    new_items = build_items(result, existing_urls)
    report = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "pages": len(result["matched"]) + len(result["unmatched"]),
        "matched": [{"slug": m["slug"], "product_id": m["product"].id,
                     "product_name": m["product"].name, "price": m["page"]["price"],
                     "spec": m["page"].get("spec"), "candidates": m["candidates"]}
                    for m in result["matched"]],
        "unmatched": result["unmatched"],
        "skipped_existing_source_url": [
            m["slug"] for m in result["matched"]
            if m["page"]["source"]["url"] in existing_urls],
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"产品页 {report['pages']} | 匹配 {len(report['matched'])} "
          f"（新条目 {len(new_items)}，已有条目跳过 {len(report['skipped_existing_source_url'])}）"
          f" | 未匹配 {len(report['unmatched'])}")
    for u in report["unmatched"]:
        cands = ", ".join(f"{c['id']}:{c['name']}" for c in u["candidates"]) or "无候选"
        print(f"  未匹配：{u['slug']} {u['name_cn']} ¥{u['price']} ← {cands}")
    if args.write and new_items:
        data["items"].extend(new_items)
        data["_说明"] += ("｜v2 增量（2026-08-10）：修丽可中国官网全量产品页机器采集"
                          "（collect_skinceuticals_cn.py → build_skinceuticals_price_seed.py），"
                          "slug/中文名规则匹配，未匹配不猜；buy_url 即官网产品页")
        data["_版本"] = "v2"
        PRICE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
        print(f"已写入 {len(new_items)} 个新条目 → {PRICE_PATH}")
    elif new_items:
        print("（dry-run，加 --write 才落盘）")


if __name__ == "__main__":
    main()
