"""INCIDecoder（incidecoder.com）采集器：纯 HTTP（静态 HTML，无需 JS 渲染）。

robots.txt 明示 User-Agent: * Allow: /（仅禁 /auth/ 与 /products/recommend/）。
采集链路：品牌页（?offset=N 翻页，每页 50 个）→ 产品详情页 → 成分表（按包装标签降序）。
最大价值：成分顺序即真实降序位次，loader 按 position 1-based 如实入库。

礼貌与熔断（对齐 collect_guidechem / collect_waves 约定）：
- 每页 ≥4s 延时（含随机抖动）；429/403 → 冷却 120s 重试 1 次，仍失败则中止本次运行
- 连续 3 次超时/空解析 → 判定限流或结构变更，熔断中止（下波再采）
- 断点续采：已落盘的 product_slug 直接跳过

运行：.venv/bin/python data/tools/collect_incidecoder.py --brand cerave --limit 5
      .venv/bin/python data/tools/collect_incidecoder.py --pilot        # 2 品牌 × ~15 个
      .venv/bin/python data/tools/collect_incidecoder.py --all          # 全量品牌清单
输出：data/raw/incidecoder/{brand_slug}/{product_slug}.json + .html（git 忽略）
      data/raw/incidecoder/_failures.jsonl
"""

import argparse
import json
import random
import re
import time
from pathlib import Path

BASE = "https://incidecoder.com"
OUT_ROOT = Path(__file__).resolve().parents[1] / "raw" / "incidecoder"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
PAGE_DELAY = 4.0          # 每页最小间隔秒数（礼貌采集，铁律 ≥4s）
COOLDOWN = 120.0          # 触发 429/403 后的冷却秒数
MAX_CONSECUTIVE_FAILURES = 3

# 品牌 slug → 入库品牌名（对齐库内既有主名：纯中文优先；
# OLAY/SK-II/雅诗兰黛/资生堂库内只有既有字符串，沿用之）
BRANDS: dict[str, str] = {
    "cerave": "适乐肤",
    "la-roche-posay": "理肤泉",
    "skinceuticals": "修丽可",
    "lancome": "兰蔻",
    "kiehls": "科颜氏",
    "kerastase": "卡诗",
    "helena-rubinstein": "赫莲娜",
    "loreal": "巴黎欧莱雅",
    "olay": "OLAY 玉兰油",
    "sk-ii": "SK-II",
    "estee-lauder": "雅诗兰黛 Estée Lauder",
    "shiseido": "资生堂 Shiseido",
}
PILOT_BRANDS = ["cerave", "la-roche-posay"]

_ZWSP = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_WS = re.compile(r"\s+")
# 页面对活性成分会标注官方浓度（如 "Salicylic Acid (2%)"），入库前剥掉；
# 只剥末尾百分比括号，不动 "GLYCYRRHIZA GLABRA (LICORICE) ROOT EXTRACT" 这类合法括号
_DECLARED_CONC = re.compile(r"\s*\(\d+(?:\.\d+)?\s*%\)\s*$")


def normalize_inci(display: str) -> str:
    """页面展示名 → 归一 INCI 名：去零宽字符、剥末尾浓度标注、压空白、大写。"""
    s = _DECLARED_CONC.sub("", _ZWSP.sub("", display))
    return _WS.sub(" ", s).strip().upper()


def _clean_text(s: str) -> str:
    import html as html_mod
    return _WS.sub(" ", _ZWSP.sub("", html_mod.unescape(s))).strip()


def parse_brand_page(html: str) -> tuple[list[tuple[str, str]], int | None]:
    """品牌页 → ([(product_slug, 产品名)], 下一页 offset 或 None)。"""
    links = re.findall(
        r'<a href="/products/([^"]+)"[^>]*class="klavika simpletextlistitem[^"]*"[^>]*>([^<]*)</a>',
        html)
    if not links:  # class 属性顺序可能不同，放宽再试一次
        links = re.findall(
            r'<a href="/products/([^"]+)"[^>]*>([^<]*)</a>', html)
    links = [(slug, _clean_text(name)) for slug, name in links]
    m = re.search(r'href="/brands/[^"]+\?offset=(\d+)">\s*Next page', html)
    return links, (int(m.group(1)) if m else None)


def _long_list(html: str) -> list[tuple[str, str]]:
    """长列表区段：每个成分一个 product-long-ingred-link，页面顺序即降序。"""
    i = html.find('id="showmore-section-ingredlist-long"')
    if i < 0:
        return []
    return re.findall(
        r'<a href="/ingredients/([^"]+)"\s*class="product-long-ingred-link[^"]*"\s*>\s*([^<]*)</a>',
        html[i:])


def _short_list(html: str) -> list[tuple[str, str]]:
    """短列表区段（长列表缺失时回退）：role="listitem" 内的 ingred-link，顺序即降序。"""
    i = html.find('id="showmore-section-ingredlist-short"')
    if i < 0:
        return []
    j = html.find('id="showmore-section-ingredlist-long"', i)
    seg = html[i:j if j > 0 else len(html)]
    return re.findall(
        r'role="listitem"><a href="/ingredients/([^"]+)"\s*\n?\s*class="ingred-link black[^"]*"[^>]*>([^<]*)</a>',
        seg)


def parse_product_page(html: str) -> dict:
    """产品详情页 → {name, ingredients: [{inci_name, slug, position}]}。成分顺序 = 包装降序。"""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    name = _clean_text(re.sub(r"<[^>]+>", " ", m.group(1))) if m else ""
    pairs = _long_list(html) or _short_list(html)
    ingredients = [{"slug": slug, "inci_name": normalize_inci(disp), "position": pos}
                   for pos, (slug, disp) in enumerate(pairs, start=1)]
    return {"name": name, "ingredients": ingredients}


class CircuitOpen(Exception):
    """熔断：触发限流（429/403 冷却后仍失败）或连续失败超阈值。"""


class Fetcher:
    """带礼貌延时与熔断的 HTTP 抓取。delay/cooldown/retry_wait 可注入（测试置 0）。"""

    def __init__(self, delay: float = PAGE_DELAY, cooldown: float = COOLDOWN,
                 retry_wait: float = 10.0):
        import requests  # 惰性导入：解析器单测不依赖网络库
        self._session = requests.Session()
        self._session.headers["User-Agent"] = UA
        self.delay = delay
        self.cooldown = cooldown
        self.retry_wait = retry_wait
        self._last = 0.0
        self.consecutive_failures = 0

    def get(self, url: str) -> str:
        wait = self.delay + random.uniform(0, 1.5) - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        for attempt in range(2):  # 首次 + 429/403 冷却后重试 1 次
            try:
                resp = self._session.get(url, timeout=30)
            except Exception as exc:
                self.consecutive_failures += 1
                if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    raise CircuitOpen(f"连续 {self.consecutive_failures} 次请求异常，熔断: {exc!r}")
                time.sleep(self.retry_wait)
                continue
            self._last = time.time()
            if resp.status_code == 200:
                self.consecutive_failures = 0
                return resp.text
            if resp.status_code in (403, 429):
                print(f"  ⛔ HTTP {resp.status_code}，冷却 {self.cooldown:.0f}s 后重试…")
                time.sleep(self.cooldown)
                continue
            if resp.status_code == 404:
                raise FileNotFoundError(url)
            self.consecutive_failures += 1
            if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                raise CircuitOpen(f"连续异常状态码（最近 {resp.status_code}），熔断")
            time.sleep(self.retry_wait)
        raise CircuitOpen(f"{url} 冷却后仍被限流，熔断中止（下波再采）")


def _log_failure(brand_slug: str, url: str, reason: str) -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    with (OUT_ROOT / "_failures.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"brand": brand_slug, "url": url, "reason": reason},
                           ensure_ascii=False) + "\n")


def _load_permanent_failures() -> set[str]:
    """负缓存：_failures.jsonl 中的 404（永久失败）URL，续采时直接跳过。

    「成分解析为 0」类不跳过——那可能是结构变更或临时拦截，下波应重试。
    """
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


def collect_brand(fetcher: Fetcher, brand_slug: str, limit: int = 0,
                  max_pages: int = 0) -> dict:
    """采集单个品牌：翻页取产品列表 → 逐个详情页解析落盘。返回计数。幂等续采。

    空解析熔断用独立的 empty_streak 计数（HTTP 200 只重置网络层计数，
    不得掩盖连续空解析——结构变更的典型信号）。
    """
    brand_name = BRANDS.get(brand_slug, brand_slug)
    out_dir = OUT_ROOT / brand_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    permanent_failures = _load_permanent_failures()
    empty_streak = 0
    stats = {"hits": 0, "new": 0, "skipped": 0, "failed": 0}

    # 1) 翻页收集产品链接（offset 递增，直到没有 Next page）
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    offset, page = 0, 0
    while True:
        url = f"{BASE}/brands/{brand_slug}" + (f"?offset={offset}" if offset else "")
        html = fetcher.get(url)
        page_links, next_offset = parse_brand_page(html)
        page += 1
        if not page_links:  # 列表页解析为 0 = 失败，不得静默正常结束
            _log_failure(brand_slug, url, "品牌列表页解析为 0，疑似结构变更或拦截")
            stats["failed"] += 1
            empty_streak += 1
            if empty_streak >= MAX_CONSECUTIVE_FAILURES:
                raise CircuitOpen(f"连续 {empty_streak} 页解析为空，熔断")
            break
        empty_streak = 0
        new = [(s, n) for s, n in page_links if s not in seen]
        for s, _ in new:
            seen.add(s)
        links.extend(new)
        print(f"[{brand_slug}] 第 {page} 页：{len(new)} 个产品（累计 {len(links)}）")
        if next_offset is None:
            break
        if max_pages and page >= max_pages:
            break
        if limit and len(links) >= limit:  # 限量采集时不必翻完整个品牌
            break
        offset = next_offset
    if limit:
        links = links[:limit]
    stats["hits"] = len(links)
    print(f"[{brand_slug}] 产品清单 {len(links)} 个，开始采详情页")

    # 2) 逐个详情页
    for slug, list_name in links:
        out_file = out_dir / f"{slug}.json"
        url = f"{BASE}/products/{slug}"
        if out_file.exists():  # 断点续采
            stats["skipped"] += 1
            continue
        if url in permanent_failures:  # 负缓存：404 永久失败不再重试
            stats["skipped"] += 1
            continue
        try:
            raw = fetcher.get(url)
        except FileNotFoundError:
            _log_failure(brand_slug, url, "404")
            stats["failed"] += 1
            continue
        data = parse_product_page(raw)
        if not data["ingredients"]:
            _log_failure(brand_slug, url, "成分解析为 0，疑似结构变更或拦截")
            stats["failed"] += 1
            empty_streak += 1
            if empty_streak >= MAX_CONSECUTIVE_FAILURES:
                raise CircuitOpen(f"连续 {empty_streak} 个详情页解析为空，熔断")
            continue
        empty_streak = 0
        (out_dir / f"{slug}.html").write_text(raw, encoding="utf-8")  # 原始存档，可离线重放
        data.update({
            "name": data["name"] or list_name,
            "brand": brand_name,
            "brand_slug": brand_slug,
            "product_slug": slug,
            "source": {"site": "incidecoder.com", "url": url,
                       "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "note": "成分表为包装标签降序；position 为真实位次"},
        })
        out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        stats["new"] += 1
        print(f"  ✓ {data['name']} | 成分 {len(data['ingredients'])}")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", action="append", help="品牌 slug（可多次）")
    ap.add_argument("--pilot", action="store_true", help="试点：cerave + la-roche-posay 各 ~15 个")
    ap.add_argument("--all", action="store_true", help="全量品牌清单")
    ap.add_argument("--limit", type=int, default=0, help="每品牌最多采几个产品；0 不限")
    ap.add_argument("--max-pages", type=int, default=0, help="每品牌最多翻几页品牌列表；0 不限")
    args = ap.parse_args()

    brands = list(args.brand or [])
    if args.pilot:
        brands += PILOT_BRANDS
        args.limit = args.limit or 15
    if args.all:
        brands += [s for s in BRANDS if s not in brands]
    if not brands:
        ap.error("--brand / --pilot / --all 至少给一个")

    fetcher = Fetcher()
    for slug in brands:
        try:
            stats = collect_brand(fetcher, slug, limit=args.limit, max_pages=args.max_pages)
        except CircuitOpen as exc:
            print(f"[{slug}] ⛔ 熔断：{exc}，终止本次运行")
            break
        except Exception as exc:  # 单品牌异常不中断整个任务
            print(f"[{slug}] 采集异常中断：{exc!r}")
            continue
        print(f"[{slug}] 汇总：命中 {stats['hits']} | 新采 {stats['new']} | "
              f"跳过 {stats['skipped']} | 失败 {stats['failed']}")


if __name__ == "__main__":
    main()
