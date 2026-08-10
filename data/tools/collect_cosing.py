"""CosIng 官方 INCI 词表采集器（欧盟委员会 CosIng 数据库官方后端 API）。

数据源链（全部为欧委会官方）：
- 入口站：https://ec.europa.eu/growth/tools-databases/cosing/（Angular SPA）
- SPA 配置 assets/env-json-config.json 指向官方搜索后端：
  https://api.tech.ec.europa.eu/search-api/prod/rest/search（apiKey 为 SPA 内置公开配置）
- 查询：itemType=ingredient、text=*、按 inciName 升序分页（pageSize 服务端上限 200），
  枚举全量 INCI 词表（含 inciName / functionName / casNo / substanceId / status 等元数据）。

深分页限制与分区策略（2026-08-10 实测）：
- 服务端结果窗口上限 10000 条（pageNumber×pageSize 超过即返回空），
  必须按 substanceId 的 range 过滤分区采集，每区 ≤9500 条；
- range 为**字典序**语义（实测：gte "110000" 匹配全部 5 位 id；双界须同为数字串，
  非数字上界被解析器吞掉返回 0；9xxxx 段字典序 >"100000" 无法双界圈出，只能单边
  gte "90000"），同长度数字段内字典序==数值序，分区边界据此设计；
- 收尾校验：唯一 reference 数须等于 totalResults，缺漏即报警（翻页漂移/分区遗漏）。

礼貌与熔断（对齐 collect_incidecoder 约定）：
- 每页 ≥4s 延时（含随机抖动）；429/403 → 冷却 120s 重试 1 次，仍失败则中止本次运行
- 连续 3 次失败 → 熔断中止（下波再采）；断点续采：已落盘的页直接跳过

运行：.venv/bin/python data/tools/collect_cosing.py [--page-size 200]
输出：data/raw/cosing/pages_id/{lo}-{hi}/page_NNN.json（git 忽略）+ data/raw/cosing/_meta.json
"""

import argparse
import json
import random
import time
from pathlib import Path

import requests

API = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
# CosIng SPA 公开配置（assets/env-json-config.json）中的 euSearchApiKey
API_KEY = "285a77fd-1257-4271-8507-f0c6b2961203"
ENTRY = "https://ec.europa.eu/growth/tools-databases/cosing/"
OUT_ROOT = Path(__file__).resolve().parents[1] / "raw" / "cosing"
PAGE_DELAY = 4.0          # 每页最小间隔秒数（礼貌采集，铁律 ≥4s）
COOLDOWN = 120.0          # 触发 429/403 后的冷却秒数
MAX_CONSECUTIVE_FAILURES = 3
SORT = [{"field": "inciName", "order": "ASC"}]

# substanceId 字典序分区（每区实测条数 ≤9500，深分页窗口 10000 内）：
# 5 位 id 段按万位切分；9xxxx 段只能单边 gte（双界会被字典序排除：'9xxxx' > '100000'，
# 非数字上界被解析器吞掉）；6 位 id 全在 "100000"-"110000" 内
ID_RANGES: tuple[tuple[str, str | None], ...] = (
    ("30000", "40000"),   # 4188 条
    ("40000", "50000"),   # 1332
    ("50000", "60000"),   # 5490
    ("60000", "70000"),   # 305
    ("70000", "80000"),   # 2872
    ("80000", "90000"),   # 6549
    ("90000", None),      # 8196（单边 gte：字典序 ≥"90000" 的恰好全是 9xxxx）
    ("100000", "110000"),  # 4721（全部 6 位 id）
)


def _query(lo: str, hi: str | None) -> dict:
    id_range: dict = {"gte": lo}
    if hi is not None:
        id_range["lt"] = hi
    return {"bool": {"must": [
        {"term": {"itemType": "ingredient"}},
        {"range": {"substanceId": id_range}},
    ]}}


def fetch_page(page: int, page_size: int, query: dict) -> dict:
    resp = requests.post(
        API,
        params={"apiKey": API_KEY, "text": "*", "pageSize": page_size, "pageNumber": page},
        files={
            "query": (None, json.dumps(query), "application/json"),
            "sort": (None, json.dumps(SORT), "application/json"),
        },
        headers={"User-Agent": "cfz-research/1.0 (CosIng vocabulary fetch)"},
        timeout=120,
    )
    if resp.status_code in (403, 429):
        raise RuntimeError(f"HTTP {resp.status_code}")
    resp.raise_for_status()
    return resp.json()


def collect_range(lo: str, hi: str | None, page_size: int) -> None:
    """采集一个 substanceId 分区，断点续采。"""
    out_dir = OUT_ROOT / "pages_id" / f"{lo}-{hi or 'open'}"
    out_dir.mkdir(parents=True, exist_ok=True)
    query = _query(lo, hi)
    consecutive_failures = 0
    page, total_pages = 1, None
    while True:
        path = out_dir / f"page_{page:03d}.json"
        if path.exists():  # 断点续采
            page += 1
            continue
        if total_pages is not None and page > total_pages:
            break
        try:
            data = fetch_page(page, page_size, query)
        except RuntimeError as e:  # 429/403：冷却重试 1 次，仍失败则中止
            print(f"[{lo}-{hi}] page {page}: {e} → 冷却 {COOLDOWN}s 后重试", flush=True)
            time.sleep(COOLDOWN)
            try:
                data = fetch_page(page, page_size, query)
            except Exception as e2:
                print(f"[{lo}-{hi}] page {page}: 冷却重试仍失败（{e2}），中止本区", flush=True)
                return
        except Exception as e:
            consecutive_failures += 1
            print(f"[{lo}-{hi}] page {page}: 失败（{e}），连续失败 {consecutive_failures}",
                  flush=True)
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print("熔断中止", flush=True)
                return
            time.sleep(PAGE_DELAY)
            continue
        consecutive_failures = 0
        if total_pages is None:
            total = data["totalResults"]
            total_pages = (total + page_size - 1) // page_size
            if total > 9500:
                print(f"⚠ [{lo}-{hi}] 分区 {total} 条逼近深分页上限，请细分该区", flush=True)
            print(f"[{lo}-{hi}] totalResults={total} totalPages={total_pages}", flush=True)
        if not data["results"] and page <= (total_pages or 0):
            print(f"⚠ [{lo}-{hi}] page {page} 空页但未完，可能触深分页上限", flush=True)
            return
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        print(f"[{lo}-{hi}] page {page}/{total_pages}: {len(data['results'])} 条", flush=True)
        if page >= (total_pages or 0):
            break
        page += 1
        time.sleep(PAGE_DELAY + random.uniform(0, 1.5))


def verify() -> dict:
    """收尾校验：递归扫描全部分页，唯一 reference 数 vs totalResults。"""
    refs, total = set(), None
    n_results = 0
    for p in sorted(OUT_ROOT.rglob("page_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("totalResults"):
            total = max(total or 0, d["totalResults"])
        for r in d["results"]:
            refs.add(r["reference"])
            n_results += 1
    return {"total_results_reported": total, "rows_fetched": n_results,
            "unique_references": len(refs)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page-size", type=int, default=200)
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()

    started = time.strftime("%Y-%m-%d %H:%M:%S")
    if not args.verify_only:
        for lo, hi in ID_RANGES:
            collect_range(lo, hi, args.page_size)
            time.sleep(PAGE_DELAY)

    stats = verify()
    meta = {
        "source": "European Commission CosIng (official search backend)",
        "entry_url": ENTRY,
        "api_url": API,
        "partition_strategy": "substanceId 字典序 range 分区（深分页窗口上限 10000）",
        "collected_at": started,
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        **stats,
    }
    (OUT_ROOT / "_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    if stats["unique_references"] != stats["total_results_reported"]:
        print(f"⚠ 唯一 reference({stats['unique_references']}) != "
              f"totalResults({stats['total_results_reported']})：有缺漏，需补采")
    else:
        print("✓ 全量校验通过")


if __name__ == "__main__":
    main()
