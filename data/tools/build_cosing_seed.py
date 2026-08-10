"""CosIng 词表 seed 构建器：data/raw/cosing/pages/ → data/seed/cosing_functions.json。

- 按 reference 去重、同名 INCI 合并功能集（并集），键为全大写 INCI；
- 只收录有 functionName 的条目（无功能申报的条目不占 seed 体积）；
- source 字段如实记录来源链（官方 SPA → 官方搜索后端 API，apiKey 为站点公开配置）；
- 功能码覆盖率自检：词表中出现的每个功能码必须落在 cosing_loader 的
  FUNCTION_MAP 或 SKIP_REASONS 中，否则报错（防止未知码被静默跳过）；
- --verify：随机抽 20 条，用 CosIng 在线查询页同款请求（官方搜索 API 按名称检索
  itemType=ingredient）比对功能码集合，≥4s/条礼貌延时，结果写入 source.verification。

运行：PYTHONPATH="backend:." .venv/bin/python data/tools/build_cosing_seed.py [--verify]
"""

import argparse
import json
import random
import time
from pathlib import Path

from data.loaders.cosing_loader import FUNCTION_MAP, SKIP_REASONS
from data.tools.collect_cosing import API, API_KEY, SORT

RAW_DIR = Path(__file__).resolve().parents[1] / "raw" / "cosing"
META_PATH = RAW_DIR / "_meta.json"
SEED_PATH = Path(__file__).resolve().parents[1] / "seed" / "cosing_functions.json"

# 在线核对用查询：与 CosIng 查询页同款（itemType=ingredient + 名称检索词）
VERIFY_QUERY = {"bool": {"must": [{"term": {"itemType": "ingredient"}}]}}

PAGE_DELAY = 4.0  # 核对请求礼貌延时（铁律 ≥4s）


def build_map(raw_dir: Path = RAW_DIR) -> tuple[dict, dict]:
    """读原始分页（递归扫描全部采集批次），返回 (INCI→功能码列表, 统计)。"""
    by_ref: dict[str, dict] = {}
    total_reported = None
    for p in sorted(raw_dir.rglob("page_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("totalResults"):
            total_reported = max(total_reported or 0, d["totalResults"])
        for r in d["results"]:
            m = r["metadata"]
            inci = (m.get("inciName") or [""])[0].strip()
            if not inci:
                continue
            entry = by_ref.setdefault(
                r["reference"],
                {"inci": inci.upper(), "functions": set(),
                 "status": (m.get("status") or [""])[0]})
            for fn in m.get("functionName") or []:
                entry["functions"].add(fn.strip().upper())

    merged: dict[str, set] = {}
    for entry in by_ref.values():
        if not entry["functions"]:
            continue
        merged.setdefault(entry["inci"], set()).update(entry["functions"])

    codes = sorted({c for fns in merged.values() for c in fns})
    unknown = [c for c in codes if c not in FUNCTION_MAP and c not in SKIP_REASONS]
    stats = {
        "total_results_reported": total_reported,
        "unique_references": len(by_ref),
        "entries_in_seed": len(merged),
        "distinct_function_codes": len(codes),
        "unknown_codes": unknown,
    }
    return ({k: sorted(v) for k, v in sorted(merged.items())}, stats)


def verify_sample(cos_map: dict, n: int = 20) -> str:
    """随机抽 n 条，按在线查询页同款请求比对功能码集合，返回核对说明文本。"""
    import requests

    rng = random.Random(20260810)
    sample = rng.sample(sorted(cos_map), min(n, len(cos_map)))
    ok, mismatches = 0, []
    for i, inci in enumerate(sample):
        if i:
            time.sleep(PAGE_DELAY)
        resp = requests.post(
            API,
            params={"apiKey": API_KEY, "text": inci, "pageSize": 20, "pageNumber": 1},
            files={
                "query": (None, json.dumps(VERIFY_QUERY), "application/json"),
                "sort": (None, json.dumps(SORT), "application/json"),
            },
            headers={"User-Agent": "cfz-research/1.0 (CosIng verification)"},
            timeout=60,
        )
        resp.raise_for_status()
        hit = None
        for r in resp.json()["results"]:
            m = r["metadata"]
            if (m.get("inciName") or [""])[0].strip().upper() == inci:
                hit = m
                break
        if hit is None:
            mismatches.append(f"{inci}: 在线检索未命中")
            continue
        online = sorted({f.strip().upper() for f in hit.get("functionName") or []})
        if online == cos_map[inci]:
            ok += 1
        else:
            mismatches.append(f"{inci}: seed={cos_map[inci]} online={online}")
    verdict = "全部一致" if not mismatches else "；".join(mismatches)
    return (f"随机抽 {len(sample)} 条与 CosIng 在线查询同款请求（官方搜索 API 按名称检索，"
            f"{time.strftime('%Y-%m-%d')}）逐条比对功能码集合：{ok} 条一致。{verdict}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="随机抽 20 条在线核对（较慢）")
    args = ap.parse_args()

    cos_map, stats = build_map()
    if stats["unknown_codes"]:
        raise SystemExit(f"词表出现 loader 未覆盖的功能码：{stats['unknown_codes']}，"
                         "请先在 cosing_loader 的 FUNCTION_MAP/SKIP_REASONS 中登记")

    meta = json.loads(META_PATH.read_text(encoding="utf-8")) if META_PATH.exists() else {}
    source = {
        "name": "European Commission CosIng — Cosmetic Ingredients and Substances",
        "entry_url": "https://ec.europa.eu/growth/tools-databases/cosing/",
        "api_url": API,
        "source_chain": ("CosIng 官方入口（Angular SPA）→ 站点公开配置 assets/env-json-config.json "
                         "指向的官方搜索后端 api.tech.ec.europa.eu（apiKey 为 SPA 内置公开配置）；"
                         "CosIng 仅提供逐成分 PDF 与附录清单导出，无批量 CSV，INCI 词表经官方搜索 "
                         "API（itemType=ingredient、inciName 升序分页）全量枚举"),
        "collected_at": meta.get("collected_at", "?"),
        "collector": "data/tools/collect_cosing.py（≥4s/页礼貌延时；原始分页在 "
                     "data/raw/cosing/（pages_id 为 substanceId 分区批次、pages_inci 为首批），git 忽略）",
        "builder": "data/tools/build_cosing_seed.py",
        **{k: v for k, v in stats.items() if k != "unknown_codes"},
        "verification": None,
    }
    if args.verify:
        source["verification"] = verify_sample(cos_map)

    seed = {"source": source, "map": cos_map}
    SEED_PATH.write_text(json.dumps(seed, ensure_ascii=False, indent=1) + "\n",
                         encoding="utf-8")
    print(f"seed 条目={stats['entries_in_seed']} 唯一 reference={stats['unique_references']} "
          f"/ reported={stats['total_results_reported']} 功能码={stats['distinct_function_codes']}")
    if source["verification"]:
        print(source["verification"])


if __name__ == "__main__":
    main()
