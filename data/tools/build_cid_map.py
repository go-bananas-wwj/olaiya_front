"""成分 → PubChem CID 映射表构建器（透皮判定 D3 的前置工件）。

对 cfz.db 中全部有功效断言的成分：
1. 混合物/提取物/聚合物直接标 no_single_cid——无单一 CID，不得硬配（数据铁律）；
2. 其余成分先按 CAS 号查 PubChem PUG-REST，未命中再按 INCI 英文名查；
3. 命中后拉取 MW / XLogP / TPSA / Title（一次请求）；
4. 幂等写入 data/seed/cid_map.json：已映射的成分跳过，--force 强制全部重建。

多 CID 歧义裁决：PUG-REST 按相关度降序返回，取首个（最佳匹配）CID，
候选数 > 1 时在条目中记录 candidates 供人工复核。

用法：/root/workspace/olaiya/.venv/bin/python data/tools/build_cid_map.py [--force] [--db cfz.db] [--out data/seed/cid_map.json]
"""

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

PUG_CIDS = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{name}/cids/JSON"
PUG_PROPS = ("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}"
             "/property/MolecularWeight,XLogP,TPSA,Title/JSON")
REQUEST_INTERVAL = 0.4  # PubChem 限速 5 req/s，保守取 2.5

# 无单一 CID 的判定：名称命中以下关键词即视为混合物/提取物/聚合物
MIXTURE_KEYWORDS = ("EXTRACT", "FERMENT", " OIL", "BUTTER", "WAX", "HYDROLYZED", "CROSSPOLYMER")
# 关键词覆盖不到的聚合物/混合物，逐个点名
MIXTURE_EXPLICIT = {"HYALURONIC ACID", "COLLAGEN", "SODIUM HYALURONATE"}


def is_mixture(inci_name: str) -> str | None:
    """返回 no_single_cid 的判定理由；单一化合物返回 None。"""
    name = inci_name.upper()
    for kw in MIXTURE_KEYWORDS:
        if kw in name:
            return f"名称含「{kw.strip()}」，混合物/提取物，无单一 CID"
    if name in MIXTURE_EXPLICIT:
        return "聚合物/混合物（显式名单），无单一 CID"
    return None


def query_ingredients(db_path: str) -> list[dict]:
    """取全部有功效断言的成分（与 D3 透皮判定同一口径）。"""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT DISTINCT i.inci_name, i.cn_name, i.cas_no
        FROM ingredients i
        JOIN efficacy_assertions ea ON ea.ingredient_id = i.id
        ORDER BY i.inci_name
    """).fetchall()
    con.close()
    return [dict(r) for r in rows]


def _get_json(url: str) -> dict | None:
    """GET JSON；404 返回 None（未命中），ServerBusy 重试一次。"""
    for attempt in range(2):
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (500, 503) and attempt == 0:
                time.sleep(2.0)
                continue
            raise
    return None


def resolve_cid(cas_no: str | None, inci_name: str) -> tuple[int | None, str | None, list[int]]:
    """先 CAS 后 INCI 解析 CID。返回 (cid, matched_by, 全部候选)。"""
    for matched_by, name in (("cas", cas_no), ("inci", inci_name)):
        if not name:
            continue
        time.sleep(REQUEST_INTERVAL)
        data = _get_json(PUG_CIDS.format(name=urllib.parse.quote(name, safe="")))
        if data:
            cids = data["IdentifierList"]["CID"]
            return cids[0], matched_by, cids  # 歧义裁决：取相关度最高的首个
    return None, None, []


def fetch_properties(cid: int) -> dict | None:
    time.sleep(REQUEST_INTERVAL)
    data = _get_json(PUG_PROPS.format(cid=cid))
    if not data:
        return None
    p = data["PropertyTable"]["Properties"][0]
    return {"pubchem_title": p.get("Title"), "mw": p.get("MolecularWeight"),
            "xlogp": p.get("XLogP"), "tpsa": p.get("TPSA")}


def build_entry(ing: dict) -> dict:
    inci, cas = ing["inci_name"], ing.get("cas_no")
    reason = is_mixture(inci)
    if reason:
        return {"cid": None, "matched_by": None, "status": "no_single_cid", "note": reason}
    cid, matched_by, candidates = resolve_cid(cas, inci)
    if cid is None:
        return {"cid": None, "matched_by": None, "status": "not_found",
                "note": "CAS 与 INCI 均未命中 PubChem"}
    props = fetch_properties(cid) or {}
    entry = {"cid": cid, "matched_by": matched_by, "status": "ok",
             "pubchem_title": props.get("pubchem_title"),
             "mw": props.get("mw"), "xlogp": props.get("xlogp"), "tpsa": props.get("tpsa")}
    if len(candidates) > 1:
        entry["candidates"] = candidates  # 多 CID 候选，供人工复核
    return entry


def main() -> None:
    ap = argparse.ArgumentParser(description="成分 → PubChem CID 映射表构建器")
    ap.add_argument("--force", action="store_true", help="忽略已有映射，全部重建")
    ap.add_argument("--db", default="cfz.db", help="SQLite 数据库路径")
    ap.add_argument("--out", default="data/seed/cid_map.json", help="映射表输出路径")
    args = ap.parse_args()

    cid_map: dict = {}
    if os.path.exists(args.out) and not args.force:
        cid_map = json.load(open(args.out, encoding="utf-8"))
        print(f"已加载现有映射 {len(cid_map)} 条（--force 可强制重建）")

    ingredients = query_ingredients(args.db)
    skipped = resolved = 0
    for ing in ingredients:
        inci = ing["inci_name"]
        if inci in cid_map:
            skipped += 1
            continue
        cid_map[inci] = build_entry(ing)
        e = cid_map[inci]
        resolved += 1
        if e["status"] == "ok":
            print(f"  ✓ {inci} → CID {e['cid']}（{e['matched_by']}）"
                  + (f" [歧义 {len(e['candidates'])} 候选]" if "candidates" in e else ""))
        else:
            print(f"  – {inci}: {e['status']}（{e['note']}）")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump(cid_map, open(args.out, "w", encoding="utf-8"), ensure_ascii=False,
              indent=2, sort_keys=True)
    print(f"\n本次解析 {resolved} 个，跳过 {skipped} 个（幂等），总计 {len(cid_map)} 条 → {args.out}")

    # 汇总表：成分 | CID | MW | XLogP | TPSA | 匹配方式
    print(f"\n{'成分':<42} {'CID':>9} {'MW':>8} {'XLogP':>6} {'TPSA':>7}  匹配方式")
    print("-" * 90)
    for inci in sorted(cid_map):
        e = cid_map[inci]
        if e["status"] == "ok":
            print(f"{inci:<42} {e['cid']:>9} {str(e['mw']):>8} {str(e['xlogp']):>6} "
                  f"{str(e['tpsa']):>7}  {e['matched_by']}")
        else:
            print(f"{inci:<42} {'—':>9} {'—':>8} {'—':>6} {'—':>7}  {e['status']}")


if __name__ == "__main__":
    main()
