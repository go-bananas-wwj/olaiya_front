"""盖德化工网化妆品数据库采集器（Playwright 无头浏览器）。

采集内容：品牌关键词搜索 → 产品详情页 → 备案号/备案信息/全成分表/功效宣称依据摘要。
注意：
- 盖德镜像 NMPA 公示数据，但成分表是拼音排序，不是备案降序（position 语义不可用，入库时置 NULL）。
- 礼貌采集：串行 + 固定延时，单 context 复用挑战 cookie。
运行：/tmp/pwenv/bin/python data/tools/collect_guidechem.py --brand 修丽可 --limit 5
输出：data/raw/guidechem/{关键词}/{详情页id}.json（原始解析结果，git 忽略）
"""

import argparse
import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "https://china.guidechem.com"
OUT_ROOT = Path(__file__).resolve().parents[1] / "raw" / "guidechem"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
PAGE_DELAY = 4.0  # 每页间隔秒数，礼貌采集


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True, help="搜索关键词（品牌名）")
    ap.add_argument("--limit", type=int, default=5, help="最多采集几个产品")
    args = ap.parse_args()

    out_dir = OUT_ROOT / args.brand
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 900}, locale="zh-CN")
        page = ctx.new_page()

        from urllib.parse import quote
        links = []
        for attempt in range(3):  # 反爬偶发空结果，重试
            page.goto(f"{BASE}/datacenter/hzp_keys-{quote(args.brand)}-p1.html", timeout=60000)
            time.sleep(6 + attempt * 4)
            links = parse_search(page.content())
            if links:
                break
            print(f"[{args.brand}] 第 {attempt + 1} 次搜索无结果，重试…")
        print(f"[{args.brand}] 搜索命中 {len(links)} 个产品，采集前 {args.limit} 个")

        for path, name in links[: args.limit]:
            pid = re.search(r"hzpdetails-(.+)\.html", path).group(1)
            out_file = out_dir / f"{pid}.json"
            if out_file.exists():
                print(f"  跳过（已存在）: {name.strip()}")
                continue
            page.goto(BASE + path, timeout=60000)
            time.sleep(PAGE_DELAY)
            raw = page.content()
            # 原始 HTML 一并存档，解析器迭代后可离线重放，不必重新采集
            (out_dir / f"{pid}.html").write_text(raw, encoding="utf-8")
            data = parse_detail(raw, text_lines(raw))
            data["source"] = {"site": "china.guidechem.com", "url": BASE + path,
                              "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                              "note": "镜像 NMPA 公示数据；成分表为拼音排序，非备案降序"}
            data["search_brand"] = args.brand
            out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  ✓ {data['name']} | 备案号 {data['nmpa_id']} | "
                  f"成分 {len(data['ingredients'])} | 宣称 {len(data['claims'])}")
        browser.close()


if __name__ == "__main__":
    main()
