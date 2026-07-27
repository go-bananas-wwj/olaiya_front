"""盖德化工网化妆品数据库采集器（Playwright 无头浏览器）。

采集内容：品牌关键词搜索 → 产品详情页 → 备案号/备案信息/全成分表/功效宣称依据摘要。
注意：
- 盖德镜像 NMPA 公示数据，但成分表是拼音排序，不是备案降序（position 语义不可用，入库时置 NULL）。
- 礼貌采集：串行 + 固定延时，单 context 复用挑战 cookie。
运行：/tmp/pwenv/bin/python data/tools/collect_guidechem.py --brand 修丽可 --pages 2 --limit 12
      /tmp/pwenv/bin/python data/tools/collect_guidechem.py --brand-file data/tools/brands.txt --pages 3 --limit 0
输出：data/raw/guidechem/{关键词}/{详情页id}.json（原始解析结果，git 忽略）
      data/raw/guidechem/_failures.jsonl（重试后仍失败的产品记录）
"""

import argparse
import json
import os
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "https://china.guidechem.com"
PROXY_SERVER = "http://127.0.0.1:7891"  # 本机 mihomo/Clash 混合端口
OUT_ROOT = Path(__file__).resolve().parents[1] / "raw" / "guidechem"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
PAGE_DELAY = 4.0  # 每页间隔秒数，礼貌采集

# ---- 代理节点轮换（本机 mihomo 控制端；CFZ_ROTATE=off 禁用） ----
MIHOMO_API = "http://127.0.0.1:9091"
MIHOMO_SECRET = "a9fb1657dc3b17e1"
MIHOMO_GROUP = "主代理"
_ROTATE_STATE = {"nodes": [], "idx": 0, "failed_once": False}


def _mihomo(path: str, method: str = "GET", body: dict | None = None) -> dict | None:
    import urllib.request
    from urllib.parse import quote
    url = f"{MIHOMO_API}{quote(path, safe='/:')}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {MIHOMO_SECRET}")
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8")) if resp.length else {}
    except Exception:
        return None


def rotate_proxy() -> str | None:
    """被限流时切换到代理组的下一个节点，返回新节点名；失败返回 None。"""
    if os.environ.get("CFZ_ROTATE", "").lower() == "off":
        return None
    st = _ROTATE_STATE
    if not st["nodes"]:
        info = _mihomo(f"/proxies/{MIHOMO_GROUP}")
        if not info or not info.get("all"):
            return None
        current = info.get("now")
        nodes = [n for n in info["all"] if n != current and "套餐" not in n]
        if current and current in info["all"]:
            st["idx"] = 0
        st["nodes"] = nodes
        st["idx"] = 0
    for _ in range(len(st["nodes"])):
        node = st["nodes"][st["idx"] % len(st["nodes"])]
        st["idx"] += 1
        r = _mihomo(f"/proxies/{MIHOMO_GROUP}", method="PUT", body={"name": node})
        if r is not None:
            time.sleep(2)
            print(f"  🌐 代理出口已切换（{node}）")
            return node
    return None


def text_lines(raw_html: str) -> list[str]:
    """把渲染后的 HTML 压成非空文本行（沿用探测阶段验证过的方法）。"""
    import html as html_mod
    raw = re.sub(r"<script.*?</script>", "", raw_html, flags=re.S)
    raw = re.sub(r"<style.*?</style>", "", raw, flags=re.S)
    t = re.sub(r"<[^>]+>", "\n", raw)
    t = html_mod.unescape(t)
    return [l.strip() for l in t.splitlines() if l.strip()]


def parse_search(html_text: str) -> list[tuple[str, str]]:
    """搜索结果页 → [(详情页路径, 产品名)]。"""
    return re.findall(r'href="(/datacenter/hzpdetails-[^"]+)"[^>]*>([^<]*)', html_text)


def _parse_ingredient_table(raw_html: str) -> list[dict]:
    """解析成分表（含 安全风险/活性成分/使用目的 列；顺序为拼音序，不代表备案降序）。"""
    import html as html_mod
    tables = re.findall(r"<table.*?</table>", raw_html, re.S)
    for tb in tables:
        if "成分名称" not in tb:
            continue
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S)
        out = []
        for r in rows[1:]:  # 跳过表头
            cells = [html_mod.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                     for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
            if len(cells) >= 5 and cells[0] and "查看全部" not in cells[0]:
                out.append({
                    "name": cells[0],
                    "safety_risk": cells[1],
                    "is_active": cells[2] == "有",
                    "purpose": cells[4],
                })
        return out
    return []


def _section(lines: list[str], start_marker: str, end_markers: tuple[str, ...]) -> list[str]:
    """截取文本行中 start_marker 到任一 end_marker 之间的内容。"""
    try:
        i = lines.index(start_marker)
    except ValueError:
        return []
    end = len(lines)
    for j in range(i + 1, len(lines)):
        if lines[j] in end_markers:
            end = j
            break
    return lines[i + 1:end]


def _parse_claims(lines: list[str]) -> list[dict]:
    """解析「功效宣称依据」段（NMPA 功效宣称依据摘要的镜像）。

    结构：N、【宣称】 → 评价类型行 → 方法名称/方法来源/(功效判定指标)/(测试方式)/
    试验起止日期/试验结果简述/评价机构。
    """
    # 「功效宣称依据」在页面出现多次（导航标签 + 正文标题），正文才是内容段：
    # 取所有出现位置中后面跟着「N、【...】」结构的那个。
    start = None
    for idx, line in enumerate(lines):
        if line == "功效宣称依据" and idx + 1 < len(lines) and re.match(r"^\d+、【", lines[idx + 1]):
            start = idx
            break
    if start is None:
        return []
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j] == "备案信息":
            end = j
            break
    seg = lines[start + 1:end]
    claims: list[dict] = []
    cur: dict | None = None
    eval_types = ("人体功效评价试验简述", "消费者使用测试简述", "研究数据简述", "文献资料简述", "实验室试验简述")

    i = 0
    while i < len(seg):
        line = seg[i]
        m = re.match(r"^(\d+)、【(.+?)】$", line)
        if m:
            if cur:
                claims.append(cur)
            cur = {"claim": m.group(2), "eval_category": None, "method_name": None,
                   "method_source": None, "metric": None, "test_period": None,
                   "result_summary": None, "institution": None}
            i += 1
            continue
        if cur is None:
            i += 1
            continue
        if line in eval_types:
            cur["eval_category"] = line.replace("简述", "")
        elif line == "方法名称" and i + 1 < len(seg):
            cur["method_name"] = seg[i + 1]; i += 1
        elif line == "方法来源" and i + 1 < len(seg):
            cur["method_source"] = seg[i + 1]; i += 1
        elif line == "功效判定指标" and i + 1 < len(seg):
            cur["metric"] = seg[i + 1]; i += 1
        elif line == "试验起止日期" and i + 1 < len(seg):
            cur["test_period"] = seg[i + 1]; i += 1
        elif line == "试验结果简述" and i + 1 < len(seg):
            cur["result_summary"] = seg[i + 1]; i += 1
        elif line == "评价机构" and i + 1 < len(seg) and seg[i + 1] != "地址":
            cur["institution"] = seg[i + 1]; i += 1
        i += 1
    if cur:
        claims.append(cur)
    return claims


def _parse_reg_info(lines: list[str]) -> dict:
    """解析「备案信息」段。"""
    # 「备案信息」在页面出现多次（导航标签 + 正文标题），正文段后面跟着「备案编号:」。
    start = None
    for idx, line in enumerate(lines):
        if line == "备案信息" and idx + 1 < len(lines) and lines[idx + 1].startswith("备案编号"):
            start = idx
            break
    if start is None:
        return {"registrant": None, "manufacturers": [], "filing_date": None}
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j] == "安全信息":
            end = j
            break
    seg = lines[start + 1:end]
    info = {"registrant": None, "manufacturers": [], "filing_date": None}
    for line in seg:
        m = re.match(r"^备案人[:：]\s*(.+)$", line)
        if m:
            info["registrant"] = m.group(1).strip()
        m = re.match(r"^备案日期[:：]\s*(.+)$", line)
        if m:
            info["filing_date"] = m.group(1).strip()
        m = re.match(r"^(?:生产企业[:：]\s*)?企业名称[:：]\s*(.+?)\s*企业地址[:：]\s*(.+)$", line)
        if m:
            info["manufacturers"].append({"name": m.group(1), "address": m.group(2)})
    return info


def parse_detail(raw_html: str, lines: list[str]) -> dict:
    """解析产品详情页。"""
    title_m = re.search(r"<title>(.*?)</title>", raw_html, re.S)
    title = title_m.group(1).strip() if title_m else ""
    nmpa_m = re.search(r"备案号[:：]\s*([^\s<]+)", title)
    # 头部字段（产品功效/英文名称 在文本行前部）
    header = _section(lines, "备案信息", ("备案信息",))  # 占位不用；头部用关键词定位
    data = {
        "name": re.sub(r"产品成分表.*$", "", title).strip(),
        "nmpa_id": nmpa_m.group(1) if nmpa_m else None,
        "efficacies": [],
        "ingredients": _parse_ingredient_table(raw_html),
        "claims": _parse_claims(lines),
        "registration": _parse_reg_info(lines),
    }
    for idx, line in enumerate(lines[:100]):
        if line == "产品功效：" and idx + 1 < len(lines):
            effs = []
            j = idx + 1
            while j < len(lines) and not lines[j].endswith("："):
                effs.append(lines[j]); j += 1
            data["efficacies"] = effs
            break
    return data


def _log_failure(brand: str, url: str, reason: str) -> None:
    """把采集失败的产品追加到 _failures.jsonl（一行一个 JSON）。"""
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    with (OUT_ROOT / "_failures.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"brand": brand, "url": url, "reason": reason},
                           ensure_ascii=False) + "\n")


def _fetch_search_links(page, brand: str, pages: int) -> list[tuple[str, str]]:
    """采集前 pages 页搜索结果（每页约 10 个），按详情页路径去重。"""
    from urllib.parse import quote
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for pg in range(1, pages + 1):
        page_links: list[tuple[str, str]] = []
        for attempt in range(3):  # 反爬偶发空结果，重试
            page.goto(f"{BASE}/datacenter/hzp_keys-{quote(brand)}-p{pg}.html", timeout=60000)
            time.sleep(6 + attempt * 4)
            page_links = parse_search(page.content())
            if page_links:
                break
            print(f"[{brand}] 第 {pg} 页第 {attempt + 1} 次搜索无结果，重试…")
        if not page_links:
            print(f"[{brand}] 第 {pg} 页无结果，停止翻页")
            break
        for path, name in page_links:
            if path not in seen:
                seen.add(path)
                links.append((path, name))
    return links


def collect_brand(page, brand: str, pages: int, limit: int) -> dict:
    """采集单个品牌：分页搜索 → 逐个详情页解析（失败重试）→ 落盘。返回计数。"""
    out_dir = OUT_ROOT / brand
    out_dir.mkdir(parents=True, exist_ok=True)

    links = _fetch_search_links(page, brand, pages)
    target = pages * 10 if limit == 0 else min(pages * 10, limit)
    todo = links[:target]
    print(f"[{brand}] 搜索命中 {len(links)} 个产品，本次采集 {len(todo)} 个")

    stats = {"hits": len(links), "new": 0, "skipped": 0, "failed": 0}
    for path, name in todo:
        pid = re.search(r"hzpdetails-(.+)\.html", path).group(1)
        out_file = out_dir / f"{pid}.json"
        if out_file.exists():  # 断点续采：已采集过的直接跳过
            stats["skipped"] += 1
            print(f"  跳过（已存在）: {name.strip()}")
            continue
        url = BASE + path
        data, raw, reason = None, "", ""
        delay = PAGE_DELAY
        for attempt in range(3):  # 首次 + 最多 2 次重试，每次多等 5 秒
            try:
                page.goto(url, timeout=60000)
                time.sleep(delay)
                raw = page.content()
                data = parse_detail(raw, text_lines(raw))
            except Exception as exc:  # 页面加载异常同样按失败处理并重试
                data, reason = None, f"页面加载异常: {exc!r}"
            else:
                if data["ingredients"] or data["claims"]:
                    break
                reason = "成分与宣称均为 0，疑似反爬拦截或解析失效"
            if attempt < 2:
                delay += 5
                print(f"  ⚠ {name.strip()} 第 {attempt + 1} 次为空/异常，{delay:.0f}s 后重试…")
        if data is None or (not data["ingredients"] and not data["claims"]):
            _log_failure(brand, url, reason)
            stats["failed"] += 1
            stats["consecutive_failures"] = stats.get("consecutive_failures", 0) + 1
            print(f"  ✗ {name.strip()} 重试后仍失败，已记入 _failures.jsonl")
            if stats["consecutive_failures"] >= 3:  # 连续失败=已被限流
                node = rotate_proxy()
                if node:
                    print(f"  🔄 已切换代理节点 → {node}，继续采集")
                    stats["consecutive_failures"] = 0
                    continue
                print(f"  ⛔ 连续 {stats['consecutive_failures']} 次失败且无法换节点，中止本品牌（下波再采）")
                break
            continue
        stats["consecutive_failures"] = 0
        # 原始 HTML 一并存档，解析器迭代后可离线重放，不必重新采集
        (out_dir / f"{pid}.html").write_text(raw, encoding="utf-8")
        data["source"] = {"site": "china.guidechem.com", "url": url,
                          "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                          "note": "镜像 NMPA 公示数据；成分表为拼音排序，非备案降序"}
        data["search_brand"] = brand
        out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        stats["new"] += 1
        print(f"  ✓ {data['name']} | 备案号 {data['nmpa_id']} | "
              f"成分 {len(data['ingredients'])} | 宣称 {len(data['claims'])}")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", help="搜索关键词（品牌名）")
    ap.add_argument("--brand-file", help="品牌清单文件，每行一个关键词，逐个品牌采集")
    ap.add_argument("--pages", type=int, default=1, help="每个品牌采集前几页搜索结果（每页 10 个）")
    ap.add_argument("--limit", type=int, default=5,
                    help="每个品牌最多采集几个产品；0 表示不限（采 pages×10 个）")
    args = ap.parse_args()

    brands = [args.brand] if args.brand else []
    if args.brand_file:
        brands += [l.strip() for l in Path(args.brand_file).read_text(encoding="utf-8").splitlines()
                   if l.strip()]
    if not brands:
        ap.error("--brand 与 --brand-file 至少给一个")

    with sync_playwright() as p:
        # 经本地代理出口采集（直连 IP 曾被目标站封禁；CFZ_PROXY=off 可禁用代理）
        proxy = None if os.environ.get("CFZ_PROXY", "").lower() == "off" else {"server": PROXY_SERVER}
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"],
                                    proxy=proxy)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 900}, locale="zh-CN")
        page = ctx.new_page()

        for brand in brands:
            try:
                stats = collect_brand(page, brand, args.pages, args.limit)
            except Exception as exc:  # 单品牌异常不中断整个任务
                print(f"[{brand}] 采集异常中断：{exc!r}")
                continue
            print(f"[{brand}] 汇总：命中 {stats['hits']} | 新采 {stats['new']} | "
                  f"跳过 {stats['skipped']} | 失败 {stats['failed']}")
        browser.close()


if __name__ == "__main__":
    main()
