"""修丽可中国官网（skinceuticals.com.cn）价格/规格采集器：纯 HTTP（静态 HTML 直出）。

robots.txt 无 Disallow 且声明 sitemap；sitemap 枚举全部产品页（~31 SKU）。
注意：sitemap 的 loc 是建站机内网地址（http://192.168.1.9:9010/...，lastmod 2023-06，
站点陈旧），采集时把 host 规范化为 www.skinceuticals.com.cn，路径不变。
页面结构（2026-08 实证）：价格 span.Js_DtlPrice、规格 div.Js_Capacity、
品名 h1.Js_ProName1（含繁体字，如「維」）、副标题 div.Js_ProName2。

礼貌与熔断（对齐 collect_incidecoder 约定）：每页 ≥4s、429/403 冷却 120s 重试 1 次、
连续 3 次失败熔断、已落盘 slug 断点续采、404 负缓存。

运行：.venv/bin/python data/tools/collect_skinceuticals_cn.py [--limit 3]
输出：data/raw/skinceuticals_cn/{slug}.json + .html（git 忽略）、_failures.jsonl
"""

import argparse
import json
import re
import time
from pathlib import Path

from data.tools.collect_incidecoder import (  # 复用同一套礼貌抓取/熔断实现
    MAX_CONSECUTIVE_FAILURES,
    CircuitOpen,
    Fetcher,
)

BASE = "https://www.skinceuticals.com.cn"
OUT_ROOT = Path(__file__).resolve().parents[1] / "raw" / "skinceuticals_cn"
SITEMAP_URL = f"{BASE}/sitemap.xml"

_WS = re.compile(r"\s+")
_LOC_RE = re.compile(r"<loc>\s*([^<]*?)\s*</loc>")
# 桌面产品页路径（/mobile/ 镜像页跳过）：/productdtl/productdtl-{slug}.html
_DTL_RE = re.compile(r"^/productdtl/productdtl-([A-Za-z0-9]+)\.html$")


def parse_sitemap(xml: str) -> list[str]:
    """sitemap XML → 去重后的桌面产品页 slug 列表（loc host 不可信，只取路径）。"""
    slugs: list[str] = []
    seen: set[str] = set()
    for loc in _LOC_RE.findall(xml):
        m = re.search(r"(/productdtl/productdtl-[A-Za-z0-9]+\.html)", loc)
        if not m or "/mobile/" in loc:
            continue
        slug = _DTL_RE.match(m.group(1))
        if slug and slug.group(1) not in seen:
            seen.add(slug.group(1))
            slugs.append(slug.group(1))
    return slugs


def parse_product_page(html: str) -> dict:
    """产品页 → {name_cn, subtitle, price, spec}。价格/规格缺失为 None（不猜）。"""
    def _cls_text(cls: str) -> str | None:
        m = re.search(rf'class="[^"]*{cls}[^"]*"[^>]*>(.*?)</', html, re.S)
        if not m:
            return None
        return _WS.sub(" ", re.sub(r"<[^>]+>", " ", m.group(1))).strip() or None

    name_cn = _cls_text("Js_ProName1")
    subtitle = _cls_text("Js_ProName2")
    spec = _cls_text("Js_Capacity")
    price_txt = _cls_text("Js_DtlPrice")
    price = None
    if price_txt:
        m = re.search(r"([\d,]+(?:\.\d+)?)", price_txt)
        if m:
            price = float(m.group(1).replace(",", ""))
    return {"name_cn": name_cn, "subtitle": subtitle, "price": price, "spec": spec}


def _log_failure(url: str, reason: str) -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    with (OUT_ROOT / "_failures.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"url": url, "reason": reason}, ensure_ascii=False) + "\n")


def _load_permanent_failures() -> set[str]:
    """负缓存：404（永久失败）URL 续采时直接跳过。"""
    path = OUT_ROOT / "_failures.jsonl"
    urls: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("reason") == "404" and rec.get("url"):
                urls.add(rec["url"])
    return urls


def collect_all(fetcher: Fetcher, limit: int = 0) -> dict:
    """sitemap 枚举 → 逐产品页采集落盘。幂等续采。返回计数。"""
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    permanent_failures = _load_permanent_failures()
    xml = fetcher.get(SITEMAP_URL)
    slugs = parse_sitemap(xml)
    if not slugs:
        raise CircuitOpen("sitemap 解析为 0 个产品页，疑似结构变更，熔断")
    if limit:
        slugs = slugs[:limit]
    print(f"sitemap 产品页 {len(slugs)} 个，开始采集")
    stats = {"hits": len(slugs), "new": 0, "skipped": 0, "failed": 0}
    empty_streak = 0
    for slug in slugs:
        url = f"{BASE}/productdtl/productdtl-{slug}.html"
        out_file = OUT_ROOT / f"{slug}.json"
        if out_file.exists() or url in permanent_failures:
            stats["skipped"] += 1
            continue
        try:
            raw = fetcher.get(url)
        except FileNotFoundError:
            _log_failure(url, "404")
            stats["failed"] += 1
            continue
        data = parse_product_page(raw)
        if data["price"] is None or not data["name_cn"]:
            _log_failure(url, "价格或品名解析为空，疑似结构变更或拦截")
            stats["failed"] += 1
            empty_streak += 1
            if empty_streak >= MAX_CONSECUTIVE_FAILURES:
                raise CircuitOpen(f"连续 {empty_streak} 页解析为空，熔断")
            continue
        empty_streak = 0
        (OUT_ROOT / f"{slug}.html").write_text(raw, encoding="utf-8")  # 原始存档
        data.update({
            "slug": slug,
            "source": {"site": "skinceuticals.com.cn", "url": url,
                       "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "note": "官网产品页静态直出价格/规格；sitemap lastmod 2023-06 站点陈旧，"
                               "价格现行性需抽查"},
        })
        out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        stats["new"] += 1
        print(f"  ✓ {data['name_cn']} | {data['price']} | {data['spec']}")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="最多采几个产品页；0 不限")
    args = ap.parse_args()
    fetcher = Fetcher()
    fetcher.encoding = "utf-8"  # 官网响应头无 charset（页面实为 UTF-8 含 BOM），防 requests 按 latin-1 误解码
    try:
        stats = collect_all(fetcher, limit=args.limit)
    except CircuitOpen as exc:
        print(f"⛔ 熔断：{exc}，终止本次运行")
        return
    print(f"汇总：命中 {stats['hits']} | 新采 {stats['new']} | "
          f"跳过 {stats['skipped']} | 失败 {stats['failed']}")


if __name__ == "__main__":
    main()
