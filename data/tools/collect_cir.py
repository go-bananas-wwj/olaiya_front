"""CIR 安全评估报告采集器：cir-reports.cir-safety.org（Power Pages 门户，无需登录）。

通道（均实测匿名可用）：
1. GET https://cir-reports.cir-safety.org/FetchCIRReports/ （分页，pagingcookie）
   → 全部「成分使用名 → CIR 成分 GUID → 报告名」索引；
2. GET https://api.personalcarecouncil.org/_api/crm/cirIngredientStatusReport?id=<成分GUID>
   → 该成分的报告行（含附件 GUID、IJT 引文、年份）；
3. GET https://api.personalcarecouncil.org/_api/crm/attachments/<附件GUID>
   → {"detail": {"fileName", "mimeType", "contentBase64"}}，base64 即报告 PDF。

解析（pdfplumber）：
- 安全结论：CONCLUSION 段「safe in cosmetics in the present practices of use and
  concentration」/「safe when formulated to be non-irritating」/「insufficient data」；
- 使用浓度：Cosmetic Use 正文（PCPC 行业调查）+「highest maximum reported
  concentrations of use were …」汇总句 + 「Conc of Use」文本表（IJT 部分增刊的
  表格是矢量轮廓，无法抽取时退回正文提取）；
- 提取文本一律原句摘录（仅压缩空白），拿不准的值宁可缺省（数据铁律：禁止猜测）。

礼貌与熔断：默认 ≥4s/请求；429/5xx 冷却 60s，连续 3 次失败即熔断中止（已抓内容不丢，
状态/PDF 均增量落盘可断点续跑）。

用法：
  /tmp/pdfenv/bin/python data/tools/collect_cir.py [--top 200] [--delay 4] \
      [--index-only] [--parse-only] [--limit N]
输出：
  data/raw/cir/index.json           FetchCIRReports 全量索引
  data/raw/cir/status/<guid>.json   每成分 status API 原始响应
  data/raw/cir/pdf/<附件guid>.pdf   报告 PDF（解析后可删，data/raw/ git 忽略）
  data/raw/cir/extraction.json      解析原始结果（审计用）
  data/research/batch-9-cir.json    入库前研究产出（过 verify_evidence.py 后由 loader 入库）
"""

import argparse
import base64
import html
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "cir"
PDF_DIR = RAW / "pdf"
STATUS_DIR = RAW / "status"
INDEX_PATH = RAW / "index.json"
EXTRACTION_PATH = RAW / "extraction.json"
OUT_PATH = ROOT / "data" / "research" / "batch-9-cir.json"
DB_PATH = ROOT / "cfz.db"

INDEX_URL = "https://cir-reports.cir-safety.org/FetchCIRReports/"
STATUS_URL = "https://api.personalcarecouncil.org/_api/crm/cirIngredientStatusReport"
ATTACH_URL = "https://api.personalcarecouncil.org/_api/crm/attachments"
ATTACH_VIEW = "https://cir-reports.cir-safety.org/view-attachment?id="

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
      "Accept": "application/json"}

_fails = 0


def fetch(url: str, delay: float, binary: bool = False, retries: int = 2) -> bytes:
    """带礼貌延时与熔断的 GET。429/5xx 冷却 60s；连续 3 次失败抛 CircuitOpen。"""
    global _fails
    time.sleep(delay)
    last_err = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers=UA)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            _fails = 0
            return data
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (429, 500, 502, 503, 504):
                print(f"  限流/服务错误 {e.code}，冷却 60s 后重试（{attempt + 1}/{retries}）", flush=True)
                time.sleep(60)
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            time.sleep(20)
    _fails += 1
    if _fails >= 3:
        raise RuntimeError(f"熔断：连续 {_fails} 次请求失败，中止（最后错误 {last_err}）")
    raise RuntimeError(f"请求失败：{url}：{last_err}")


# ---------------------------------------------------------------- 成分名规范化

def norm(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (name or "").upper())


def flex(phrase: str) -> re.Pattern:
    """允许任意空白（含 PDF 抽取丢空格/连字符换行）的逐字符正则。"""
    parts = [r"\s*" if c == " " else re.escape(c) for c in phrase]
    return re.compile(r"[-\s]*".join(parts), re.I)


# ---------------------------------------------------------------- 1. 索引

def fetch_index(delay: float) -> list[dict]:
    results: list[dict] = []
    for extra in ("", "&part2=true"):
        url = INDEX_URL + ("?part2=true" if extra else "")
        cookie = None
        page = 1
        while True:
            # 门户前端 JS 是把 pagingcookie 原样（HTML 实体形式）拼进 URL 的，
            # 浏览器只会把空格等非法字符百分号编码；全量 quote 反而会 500。
            u = url if page == 1 else (
                f"{INDEX_URL}?page={page}{extra}&pagingcookie="
                f"{urllib.parse.quote(cookie, safe='&;=')}")
            data = json.loads(fetch(u, delay))
            results.extend(data.get("results", []))
            print(f"  索引 {extra or 'part1'} 第{page}页：累计 {len(results)} 条", flush=True)
            if not data.get("morerecords"):
                break
            cookie = data["pagingcookie"]  # 保持 HTML 实体原样（服务端按实体形式解析）
            page += 1
    RAW.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return results


# ---------------------------------------------------------------- 2. 目标成分

def db_targets(top: int) -> list[dict]:
    """库内按产品关联数 top N 的正式成分（inci_name 为英文的）。"""
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    rows = con.execute(
        """SELECT i.id, i.inci_name, i.cn_name, count(pi.id) c
           FROM ingredients i JOIN product_ingredients pi ON pi.ingredient_id = i.id
           WHERE i.inci_name GLOB '*[A-Za-z]*'
           GROUP BY i.id ORDER BY c DESC LIMIT ?""", (top,)).fetchall()
    con.close()
    return [{"id": r[0], "inci_name": r[1], "cn_name": r[2], "n_products": r[3]}
            for r in rows]


def match_targets(targets: list[dict], index: list[dict]) -> tuple[list[dict], list[str]]:
    """目标成分 → CIR 成分 GUID（按规范化名精确匹配，同名取 ingredientname 侧）。"""
    by_cir_name: dict[str, dict] = {}
    by_used_name: dict[str, dict] = {}
    for rec in index:
        cir_key = norm(rec.get("pcpc_ciringredientname", ""))
        used_key = norm(rec.get("pcpc_ingredientname", ""))
        if cir_key and cir_key not in by_cir_name:
            by_cir_name[cir_key] = rec
        if used_key and used_key not in by_used_name:
            by_used_name[used_key] = rec
    matched, unmatched = [], []
    for t in targets:
        key = norm(t["inci_name"])
        rec = by_cir_name.get(key) or by_used_name.get(key)
        if rec:
            matched.append({**t, "cir_guid": rec["pcpc_ingredientid"],
                            "cir_name": rec.get("pcpc_ciringredientname"),
                            "cir_report_name": rec.get("pcpc_cirreportname")})
        else:
            unmatched.append(t["inci_name"])
    return matched, unmatched


# ---------------------------------------------------------------- 3. 报告定位

def fetch_status(matched: list[dict], delay: float, limit: int | None) -> list[dict]:
    """逐成分拉 status 报告行；增量落盘，断点续跑。"""
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    todo = matched[:limit] if limit else matched
    for i, m in enumerate(todo):
        cache = STATUS_DIR / f"{m['cir_guid']}.json"
        if cache.exists():
            payload = json.loads(cache.read_text(encoding="utf-8"))
        else:
            payload = json.loads(fetch(f"{STATUS_URL}?id={m['cir_guid']}", delay))
            cache.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        rows = (payload.get("report") or {}).get("rows") or []
        # 取正式发布的报告附件行；多个取日期最新
        pubs = [r for r in rows if r.get("statusSource") == "attachment"
                and r.get("statusUrl") and "Published" in (r.get("statusLabel") or "")]
        if not pubs:
            pubs = [r for r in rows if r.get("statusSource") == "attachment"
                    and r.get("statusUrl")]
        best = None
        if pubs:
            best = sorted(pubs, key=lambda r: r.get("statusDate") or "")[-1]
        att = None
        if best:
            mm = re.search(r"id=([0-9a-f-]{36})", best["statusUrl"])
            att = mm.group(1) if mm else None
        out.append({**m, "status_rows": len(rows),
                    "attachment_id": att,
                    "citation": best.get("dateOrReference") if best else None,
                    "status_date": best.get("statusDate") if best else None,
                    "cir_report_id": best.get("cirReportId") if best else None})
        if i % 20 == 0:
            print(f"  status {i + 1}/{len(todo)}", flush=True)
    return out


# ---------------------------------------------------------------- 4. PDF 下载

def download_pdfs(statused: list[dict], delay: float) -> dict[str, Path]:
    """按附件 GUID 去重下载，返回 附件GUID → 本地路径。"""
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for s in statused:
        att = s.get("attachment_id")
        if not att:
            continue
        p = PDF_DIR / f"{att}.pdf"
        if p.exists() and p.stat().st_size > 1000:
            paths[att] = p
            continue
        payload = json.loads(fetch(f"{ATTACH_URL}/{att}", delay))
        detail = payload.get("detail") or {}
        pdf = base64.b64decode(detail.get("contentBase64") or b"")
        if not pdf.startswith(b"%PDF"):
            print(f"  ⚠ 附件 {att} 非 PDF（{detail.get('fileName')}），跳过", flush=True)
            continue
        p.write_bytes(pdf)
        paths[att] = p
        print(f"  下载 {detail.get('fileName')} {len(pdf) // 1024}KB", flush=True)
    return paths


# ---------------------------------------------------------------- 5. PDF 解析

SAFE_FLEX = flex("safe in cosmetics in the present practices of use and concentration")
QUAL_FLEX = flex("safe when formulated to be non-irritating")
INSUF_RE = re.compile(r"insufficient", re.I)



def _cosmetic_use_region(text: str) -> str | None:
    """截取 Cosmetic Use 区域：起点取 VCRP 或「Cosmetic Use」行标题（前留 2500 字符
    覆盖引言段），终点取「Non-Cosmetic」行标题。标记都找不到则返回 None
    （宁缺勿猜，不做浓度提取）。"""
    starts = []
    m = re.search(r"VCRP", text)
    if m:
        starts.append(m.start())
    m = re.search(r"(?im)^\s*Cosmetic\s+Use\s*$", text)
    if m:
        starts.append(m.start())
    if not starts:
        return None
    start = max(0, min(starts) - 2500)
    m2 = re.search(r"(?im)^\s*Non[- ]Cosmetic(\s+Uses?)?\s*$", text)
    if m2 and m2.start() > start:
        return text[start:m2.start()]
    return text[start:start + 30000]


def _page_text(page) -> str:
    """按词心 x 坐标分列的双栏抽取：整词归入左/右流（不切割单词），
    整宽版式（摘要/表格页，栏带墨水量高）退化为普通单栏抽取。"""
    words = page.extract_words()
    if len(words) < 40:
        return page.extract_text() or ""
    # 栏分割点：在 [0.35W, 0.65W] 内按 1pt 精度累计字符墨迹，找最长无墨空档
    # （gutter），不能直接用页中线——右栏起点可能在中线左侧（如 IJT 右栏
    # 始于 ~0.487W，gutter 只有 ~10pt）
    lo, hi = int(page.width * 0.35), int(page.width * 0.65)
    ink = [0] * (hi - lo + 1)
    for c in page.chars:
        a, b = max(lo, int(c["x0"])), min(hi, int(c["x1"]) + 1)
        for x in range(a, b):
            ink[x - lo] += 1
    best_run, cur_run, cur_start, best_start = 0, 0, 0, 0
    for i, n in enumerate(ink):
        if n == 0:
            if cur_run == 0:
                cur_start = i
            cur_run += 1
            if cur_run > best_run:
                best_run, best_start = cur_run, cur_start
        else:
            cur_run = 0
    if best_run < 8:
        return page.extract_text() or ""  # 找不到 gutter：整宽版式
    split = lo + best_start + best_run / 2
    # 整宽行检测：有单词跨越分割点 ±6pt 的行（整宽摘要/标题行中间必有词
    # 骑跨分割线；双栏行的 gutter 在分割线处，无词骑跨）。≥4 行即按单栏抽取，
    # 否则整宽摘要会被栏带拦腰截断（IJT 首页摘要就是整宽）。
    from collections import defaultdict
    row_map: dict[int, list] = defaultdict(list)
    for w in words:
        row_map[round(w["top"] / 3)].append(w)
    wide_rows = sum(
        1 for key in row_map
        if any(w["x0"] < split - 6 and w["x1"] > split + 6 for w in row_map[key]))
    if wide_rows >= 4:
        return page.extract_text() or ""  # 整宽版式：直接抽

    def render(stream: list) -> str:
        rows: dict[int, list] = defaultdict(list)
        for w in stream:
            rows[round(w["top"] / 3)].append(w)
        return "\n".join(" ".join(x["text"] for x in sorted(rows[k], key=lambda v: v["x0"]))
                         for k in sorted(rows))

    left = [w for w in words if (w["x0"] + w["x1"]) / 2 < split]
    right = [w for w in words if (w["x0"] + w["x1"]) / 2 >= split]
    return render(left) + "\n" + render(right)


def _pdf_text(path: Path) -> tuple[str, list[str]]:
    import pdfplumber
    pages_text: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for p in pdf.pages:
            pages_text.append(_page_text(p))
    full = "\n".join(pages_text)
    full = re.sub(r"[ \t]+", " ", full)
    return full, pages_text


def extract_conclusion(text: str, ingredient_names: list[str]) -> dict | None:
    """从全文找结论段；返回 {kind, excerpt, insufficient: [被判数据不足的成分]}。

    kind 只认明确措辞：safe（现行使用方式和浓度下安全）/ safe_qualified
    （配方无刺激性前提下安全）/ insufficient（数据不足，含部分成分安全、
    部分不足的情况——不足名单进 insufficient，其余成分仍按 safe）。
    """
    m = SAFE_FLEX.search(text)
    if m:
        kind = "safe"
    else:
        m = QUAL_FLEX.search(text)
        if m:
            kind = "safe_qualified"
        else:
            mi = INSUF_RE.search(text)
            if not mi:
                return None
            kind = "insufficient"
            m = mi
    start = max(0, m.start() - 400)
    end = min(len(text), m.end() + 400)
    excerpt = re.sub(r"\s+", " ", text[start:end]).strip()
    # 「数据不足」成分名单：insufficient 字样到句末（.）之间的目标成分名，
    # 避免扫到 Keywords 里的全成分列表
    insufficient: list[str] = []
    for mi in INSUF_RE.finditer(text):
        end = text.find(".", mi.end())
        window = text[max(0, mi.start() - 80):(end + 1 if 0 < end - mi.end() < 500
                                                else mi.end() + 500)]
        for name in ingredient_names:
            if name not in insufficient and flex(name).search(window):
                insufficient.append(name)
    return {"kind": kind, "excerpt": excerpt, "insufficient": insufficient}


_DOSE_RE = re.compile(r"dose|mmol|/kg|administered|plasma|urin", re.I)


def extract_conc_for_name(region: str, name: str) -> dict | None:
    """在 Cosmetic Use 区域找该成分的「up to X%」表述；取最大/最小，摘录原句。

    只收使用浓度语境：「% of (the administered) dose」类毒理剂量表述剔除。
    """
    pat = flex(name)
    hits = []
    for m in pat.finditer(region):
        window = region[m.end():m.end() + 220]
        pre = region[max(0, m.start() - 120):m.end()]
        for pm in re.finditer(r"up\s*to\s*(\.\d+|\d+(?:\.\d+)?)\s*%", window):
            tail = window[pm.end():pm.end() + 20]
            ctx = pre + window[:pm.end() + 20]
            if re.match(r"\s*of", tail, re.I) or _DOSE_RE.search(ctx):
                continue
            hits.append((float(pm.group(1)), m.start()))
    if not hits:
        return None
    vals = [h[0] for h in hits]
    # 摘录最大值所在的句子
    best_pos = max(hits, key=lambda h: h[0])[1]
    start = max(0, region.rfind(".", 0, best_pos) + 1)
    end = region.find(".", best_pos)
    sentence = re.sub(r"\s+", " ", region[start:(end + 1 if end > 0 else best_pos + 250)]).strip()
    return {"low": min(vals), "high": max(vals), "sentence": sentence[:600]}


def extract_paren_concs(region: str, names_norm: dict[str, str]) -> dict[str, dict]:
    """解析「Name (x% in <品类>)」括号表述（行业使用调查的标准写法，
    局部连续、不受双栏交错影响）。names_norm: 规范名 → 原名。"""
    out: dict[str, dict] = {}
    for pm in re.finditer(r"([A-Za-z0-9][A-Za-z0-9 ,\-'/()]{0,60}?)\s*"
                          r"\(\.?(\d+(?:\.\d+)?)\s*%\s*in\s*([^)]{1,80})\)", region):
        raw_name, val, cat = pm.group(1).strip(" ,.;:"), float(pm.group(2)), pm.group(3)
        key = norm(raw_name)
        for want_norm, want_raw in names_norm.items():
            if key == want_norm or (len(want_norm) >= 4 and key.endswith(want_norm)):
                cur = out.get(want_raw)
                if cur is None or val > cur["high"]:
                    span = re.sub(r"\s+", " ", pm.group(0)).strip()
                    out[want_raw] = {"high": val, "low": val,
                                     "sentence": f"原文：…{span}…（使用浓度调查，品类：{cat.strip()}）"}
    return out


def parse_report(path: Path, ingredient_names: list[str]) -> dict:
    """解析一份报告：结论（含逐成分数据不足名单）+ 每个目标成分的使用浓度。

    浓度在全文范围提取（标题定位在双栏抽取文本里不可靠）；毒理剂量语境
    由 extract_conc_for_name 的 dose/%of 过滤剔除，使用浓度语境天然
    是「up to X% in <品类>」「Name (X% in <品类>)」写法。
    """
    text, _pages = _pdf_text(path)
    concl = extract_conclusion(text, ingredient_names)
    region = _cosmetic_use_region(text)
    if region is None:
        return {"conclusion": concl, "concentrations": {}}
    names_norm = {norm(n): n for n in ingredient_names}
    summary = extract_paren_concs(region, names_norm)
    per_ing: dict[str, dict] = {}
    for name in ingredient_names:
        got = extract_conc_for_name(region, name)
        summ = summary.get(name)
        if got is None and summ is None:
            continue
        if got is None:
            per_ing[name] = {**summ, "method": "paren-conc"}
        elif summ is not None and summ["high"] > got["high"]:
            per_ing[name] = {"low": got["low"], "high": summ["high"],
                             "sentence": f"{got['sentence']} || {summ['sentence']}"[:600],
                             "method": "prose+summary"}
        else:
            per_ing[name] = {**got, "method": "prose-up-to"}
    return {"conclusion": concl, "concentrations": per_ing}


# ---------------------------------------------------------------- 6. 组装产出

def build_batch(statused: list[dict], parsed: dict[str, dict]) -> dict:
    """组装 batch-9-cir.json（verify_evidence.py 输入格式，附加 cir_conc_* 字段）。"""
    by_att: dict[str, list[dict]] = {}
    for s in statused:
        if s.get("attachment_id"):
            by_att.setdefault(s["attachment_id"], []).append(s)

    ingredients_out = []
    for att, members in by_att.items():
        pr = parsed.get(att) or {}
        concl = pr.get("conclusion") or {}
        concs = pr.get("concentrations") or {}
        first = members[0]
        citation = first.get("citation") or ""
        year = None
        if first.get("status_date"):
            year = int(first["status_date"][:4])
        report_name = first.get("cir_report_name") or "CIR Safety Assessment"
        title = f"{report_name}（{citation}）" if citation else report_name
        # 证据摘录：结论原句 + 各成分浓度原句（共享一条报告级证据）
        excerpt_parts = [concl.get("excerpt", "")]
        for m in members:
            c = concs.get(m["cir_name"]) or concs.get(m["inci_name"]) or {}
            if c.get("sentence"):
                excerpt_parts.append(c["sentence"])
        excerpt = " … ".join(p for p in excerpt_parts if p)[:1900]
        evidence = {
            "type": "white_paper",
            "title": title[:480],
            "source": "Cosmetic Ingredient Review",
            "year": year,
            "url": f"{ATTACH_VIEW}{att}",
            "excerpt": excerpt,
        }
        kind = concl.get("kind")
        insufficient = set(concl.get("insufficient") or [])
        for m in members:
            c = concs.get(m["cir_name"]) or concs.get(m["inci_name"])
            item = {
                "cn_name": m["cn_name"],
                "inci_name": m["inci_name"],
                "cas_no": None,
                "cir_conc_low": c["low"] if c else None,
                "cir_conc_high": c["high"] if c else None,
                "assertions": [],
            }
            # 报告级结论为 safe 但该成分被判数据不足 → 不出断言（措辞保守）
            is_insufficient = kind == "insufficient" or (
                m["cir_name"] in insufficient or m["inci_name"] in insufficient)
            if kind in ("safe", "safe_qualified") and not is_insufficient:
                conc_txt = ""
                if c:
                    # 与 review_cir_batch._conc_txt 同口径：定点格式化 + 非安全限值标注
                    fmt = lambda v: f"{v:.10f}".rstrip("0").rstrip(".")  # noqa: E731
                    if c["low"] == c["high"]:
                        conc_txt = f"；行业调查最大使用浓度 {fmt(c['high'])}%，非安全限值"
                    else:
                        conc_txt = (f"；行业调查使用浓度区间 {fmt(c['low'])}%"
                                    f"-{fmt(c['high'])}%，非安全限值")
                qualifier = "、配方无刺激性前提下" if kind == "safe_qualified" else ""
                efficacy = (f"安全评估：现行使用方式和浓度下{qualifier}安全"
                            f"（CIR 评估{conc_txt}）")
                note = ("CIR（美国化妆品原料评价委员会）专家小组安全评估结论，"
                        "为行业自评机构意见而非监管限值；浓度来自 PCPC 行业使用调查，"
                        "非功效起效浓度")
                item["assertions"].append({
                    "efficacy": efficacy, "evidence": evidence,
                    "effective_conc_low": None, "effective_conc_high": None,
                    "note": note})
            ingredients_out.append(item)
    return {"ingredients": ingredients_out}


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--top", type=int, default=200, help="库内高频成分取前 N")
    ap.add_argument("--delay", type=float, default=4.0, help="请求间隔秒数（≥4）")
    ap.add_argument("--limit", type=int, default=None, help="只处理前 N 个命中（调试）")
    ap.add_argument("--index-only", action="store_true")
    ap.add_argument("--parse-only", action="store_true", help="跳过网络，仅解析已下载 PDF")
    args = ap.parse_args()

    if not INDEX_PATH.exists():
        print("抓取 FetchCIRReports 全量索引…", flush=True)
        index = fetch_index(args.delay)
    else:
        index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    print(f"索引 {len(index)} 条", flush=True)
    if args.index_only:
        return

    targets = db_targets(args.top)
    matched, unmatched = match_targets(targets, index)
    print(f"目标 top{args.top}：命中 CIR {len(matched)}，未命中 {len(unmatched)}", flush=True)
    print("未命中：" + "、".join(unmatched), flush=True)

    if args.parse_only:
        STATUS_DIR.mkdir(parents=True, exist_ok=True)
        statused = []
        for m in matched:
            cache = STATUS_DIR / f"{m['cir_guid']}.json"
            if not cache.exists():
                continue
            payload = json.loads(cache.read_text(encoding="utf-8"))
            rows = (payload.get("report") or {}).get("rows") or []
            pubs = [r for r in rows if r.get("statusSource") == "attachment"
                    and r.get("statusUrl")]
            best = sorted(pubs, key=lambda r: r.get("statusDate") or "")[-1] if pubs else None
            att = None
            if best:
                mm = re.search(r"id=([0-9a-f-]{36})", best["statusUrl"])
                att = mm.group(1) if mm else None
            statused.append({**m, "attachment_id": att,
                             "citation": best.get("dateOrReference") if best else None,
                             "status_date": best.get("statusDate") if best else None})
        paths = {p.stem: p for p in PDF_DIR.glob("*.pdf")} if PDF_DIR.exists() else {}
    else:
        print("抓取 status 报告行…", flush=True)
        statused = fetch_status(matched, args.delay, args.limit)
        print("下载报告 PDF…", flush=True)
        paths = download_pdfs(statused, args.delay)

    # 解析：同一附件覆盖的多个成分一起传入
    by_att: dict[str, list[dict]] = {}
    for s in statused:
        if s.get("attachment_id"):
            by_att.setdefault(s["attachment_id"], []).append(s)
    parsed: dict[str, dict] = {}
    for att, members in by_att.items():
        p = paths.get(att)
        if not p or not Path(p).exists():
            continue
        names = []
        for m in members:
            for n in (m["cir_name"], m["inci_name"]):
                if n and n not in names:
                    names.append(n)
        try:
            parsed[att] = parse_report(Path(p), names)
        except Exception as e:
            print(f"  ⚠ 解析失败 {att}: {e}", flush=True)
    RAW.mkdir(parents=True, exist_ok=True)
    EXTRACTION_PATH.write_text(json.dumps(parsed, ensure_ascii=False, indent=1),
                               encoding="utf-8")
    n_conc = sum(len(v.get("concentrations") or {}) for v in parsed.values())
    n_concl = sum(1 for v in parsed.values() if v.get("conclusion"))
    print(f"解析完成：报告 {len(parsed)} 份，结论命中 {n_concl}，浓度命中 {n_conc} 成分次",
          flush=True)

    batch = build_batch(statused, parsed)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
    n_assert = sum(len(i["assertions"]) for i in batch["ingredients"])
    n_conc_items = sum(1 for i in batch["ingredients"] if i.get("cir_conc_high") is not None)
    print(f"产出 {OUT_PATH}：成分 {len(batch['ingredients'])}，断言 {n_assert}，"
          f"浓度回填候选 {n_conc_items}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
