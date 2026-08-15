"""化妆品原料手册(新) 条目切分与用途断言提取（在 reorder_shouce.py 产物上运行）。

用法：
    .venv/bin/python data/tools/extract_shouce_book.py \
        --inp /tmp/shouce_reordered.jsonl --out /tmp/shouce_book.json [--pages 150,211,300]

数据铁律约束（本工具只抽可信字段，绝不猜）：
- 只抽：条目编号、中文名、英文名、别名、用途叙述句（verbatim 清洗：仅去空白，不改正文错字）、页码。
- 表格限值/化学式/结构式一律不抽（OCR 已知缺陷：≤/≥ 误识、下标丢失、结构式乱码）。
- 拿不准的条目整体跳过并按原因计数（stats.skipped），未命中不猜。
- 条目编号连续性在 stats.number_gaps 如实报告（仅在连续页面上有意义；抽样页运行会呈现跨页断号）。

条目结构：编号行（独立行或粘在中文名/英文名同行行尾，模式 \\d{1,2}-\\d{1,2}-\\d{3}）
标题区向上回溯取中文名/英文名；正文按字段关键字（别名/性质/制法/结构式/质量指标/用途/毒性/
贮运/生产单位等）切，「用途」句从其关键字行起到下一个字段关键字止。
条目跨页：输入按页码顺序流式拼接，条目状态跨页延续；章节标题（第X节/一、…）为条目边界。

输出三段式（同 formula_typical_dose.json）：source / stats / records。
source.nature 固定注明「行业参考工具书记载，非原始研究证据」。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# 条目编号：独立成行或粘在标题行行尾（如「艾蒿油Absinthe oil2-2-001」）。
# 注意用贪婪 head：名称自带数字后缀（吐温-20/斯盘-80）与编号粘连时（「吐温-20Tween 202-1-066」），
# 懒惰匹配会把名称尾数并进编号（no=02-1-066、en 名被截成 Tween 2）；贪婪取最末合法编号起点可避免。
ENTRY_NO_RE = re.compile(r"^(?P<head>.*)(?P<no>\d{1,2}-\d{1,2}-\d{3})$")
SECTION_RE = re.compile(r"^第[0-9一二三四五六七八九十百]+[章节编]")
SUBSECTION_RE = re.compile(r"^[一二三四五六七八九十]+、")
CJK_RE = re.compile(r"[一-鿿]")
SENTENCE_RE = re.compile(r"[。；]")

# 字段标签（含 OCR 形近字变体「则运」=贮运）；作为正文切分与字段捕获的终止关键字
FIELD_KEYWORDS = (
    "别名", "性质", "性状", "制法", "结构式", "分子式", "分子量", "质量指标",
    "用途", "毒性", "生产单位", "工艺流程",
    "包装及贮运", "贮运及保管", "包装及则运", "则运及保管", "贮运", "则运", "包装",
)
STOP_EXTRA = ("注：", "注:")

CN_NAME_MAX_LEN = 25
HEADER_WINDOW = 5  # 编号行向上回溯取标题区的最大行数

NATURE = "行业参考工具书记载，非原始研究证据"


def _starts_field(text: str) -> bool:
    if SECTION_RE.match(text) or SUBSECTION_RE.match(text):
        return True
    return text.startswith(FIELD_KEYWORDS) or text.startswith(STOP_EXTRA)


def _is_latin(text: str) -> bool:
    """无 CJK 且含 ≥2 个拉丁字母 → 视为英文名候选行。"""
    return not CJK_RE.search(text) and sum(c.isalpha() for c in text) >= 2


def _split_cn_en(frag: str) -> tuple[str, str]:
    """拆「中文名English name」粘连行。仅当拉丁尾段像完整英文名（≥2 字母且长度≥4）
    才拆，防止「维生素B5」这类中文名被误切。"""
    m = re.search(r"[A-Za-z][A-Za-z0-9 .''()-]{2,}$", frag)
    if m and sum(c.isalpha() for c in m.group(0)) >= 2 and CJK_RE.search(frag[: m.start()]):
        return frag[: m.start()], m.group(0).strip()
    return frag, ""


def _clean_cn(cn: str) -> str:
    """去掉中文名行尾粘连的 ASCII 垃圾（如「…甜菜碱1-」），不改字符本体。

    注意保留名称自身的数字后缀（吐温-20 / 维生素B5）：只剥尾随标点，
    以及「数字+连字符」的残缺片段（条目编号折行残留，如「甜菜碱1-」→「甜菜碱」）。
    """
    if not CJK_RE.search(cn):
        return cn
    cn = re.sub(r"[\s,.，]+$", "", cn)
    return re.sub(r"\d*[-–]$", "", cn)


def _valid_cn(cn: str) -> bool:
    if not cn or not CJK_RE.search(cn) or len(cn) > CN_NAME_MAX_LEN:
        return False
    if SENTENCE_RE.search(cn):
        return False
    if SECTION_RE.match(cn) or SUBSECTION_RE.match(cn):
        return False
    return not cn.startswith(FIELD_KEYWORDS)


def parse_header(window_texts: list[str], head: str) -> tuple[str, str] | None:
    """从编号行所在区域回溯标题：head（编号行内编号前的粘连文本）最近，先于 window 末几行。

    规则：自近及远扫描，拉丁片段收进英文名，首个含 CJK 的片段拆出中文名；
    最近的 CJK 片段不是合法名称（含句读/是字段标签/超长）→ 返回 None（不猜）。
    """
    frags = ([head.strip()] if head.strip() else [])
    frags += [t for t in reversed(window_texts[-HEADER_WINDOW:])]
    en_rev: list[str] = []  # 近→远收集，最后反转拼接
    for frag in frags:
        if CJK_RE.search(frag):
            cn, en_tail = _split_cn_en(frag)
            cn = _clean_cn(cn)
            if not _valid_cn(cn):
                return None
            if en_tail:
                en_rev.append(en_tail)
            en = " ".join(reversed(en_rev)).strip()
            return cn, en
        if _is_latin(frag):
            en_rev.append(frag.strip())
        # 既非 CJK 又非拉丁的垃圾碎片：跳过不猜
    return None


def capture_field(body_texts: list[str], keyword: str) -> str | None:
    """从正文中捕获字段：关键字行（可粘连内容）起，到下一个字段关键字/章节标题止。
    verbatim 清洗：仅去首尾空白与关键字后残留的冒号，不改正文。"""
    for i, text in enumerate(body_texts):
        if text.startswith(keyword):
            parts = [text[len(keyword):]]
            for nxt in body_texts[i + 1:]:
                if _starts_field(nxt):
                    break
                parts.append(nxt)
            joined = "".join(parts).strip().lstrip("：:").strip()
            return joined or None
    return None


def number_gaps(entry_nos: list[str]) -> list[dict]:
    """同前缀（如 2-2）内编号后缀连续性检查，缺失如实报告。"""
    by_prefix: dict[str, set[int]] = defaultdict(set)
    for no in entry_nos:
        parts = no.split("-")
        by_prefix["-".join(parts[:-1])].add(int(parts[-1]))
    gaps = []
    for prefix, suffixes in sorted(by_prefix.items()):
        lo, hi = min(suffixes), max(suffixes)
        missing = sorted(set(range(lo, hi + 1)) - suffixes)
        if missing:
            gaps.append({"prefix": prefix, "missing": [f"{prefix}-{m:03d}" for m in missing]})
    return gaps


def extract(records_pages: list[dict]) -> dict:
    """对重排后的页记录流做条目切分与字段提取。"""
    records: list[dict] = []
    skipped: dict[str, int] = defaultdict(int)
    seen_nos: set[str] = set()
    stats_extra: dict[str, int] = defaultdict(int)

    current: dict | None = None  # {no, page, head, window, body, closed_by}
    pre_buf: list[str] = []      # 首个条目编号之前的孤儿行（跨页续文/前言）
    prev_page: int | None = None

    def finalize(entry: dict) -> None:
        hdr = parse_header(entry["window"], entry["head"])
        if hdr is None:
            skipped["no_cn_name"] += 1
            return
        cn_name, en_name = hdr
        purpose = capture_field([r for r in entry["body"]], "用途")
        if not purpose:
            skipped["no_purpose"] += 1
            return
        if entry["no"] in seen_nos:
            skipped["duplicate_no"] += 1
            return
        seen_nos.add(entry["no"])
        rec_out = {
            "entry_no": entry["no"],
            "cn_name": cn_name,
            "en_name": en_name,
            "alias": capture_field(entry["body"], "别名"),
            "purpose": purpose,
            "page": entry["page"],
        }
        # 被页码断档/输入末尾截断关闭的条目正文可能不完整，如实标注（全量连续跑不会出现）
        if entry.get("closed_by") in ("page_gap", "eof"):
            rec_out["truncated"] = True
            stats_extra["truncated_records"] += 1
        records.append(rec_out)

    for rec in records_pages:
        # 页码断档：未闭合条目不得吞并跳页后的他人正文，先关闭再处理新页
        if prev_page is not None and rec["page"] > prev_page + 1:
            if current is not None:
                current["closed_by"] = "page_gap"
                finalize(current)
                current = None
            pre_buf = []
        prev_page = rec["page"]
        for ln in rec.get("lines") or []:
            text = (ln.get("text") or "").strip()
            if not text:
                continue
            m = ENTRY_NO_RE.match(text)
            if m:
                window = (current["body"] if current else pre_buf)[-HEADER_WINDOW:]
                if current:
                    finalize(current)
                current = {
                    "no": m.group("no"),
                    "page": rec["page"],
                    "head": m.group("head"),
                    "window": window,
                    "body": [],
                }
                pre_buf = []
            elif SECTION_RE.match(text) or SUBSECTION_RE.match(text):
                stats_extra["section_headers"] += 1
                if current:
                    finalize(current)
                    current = None
                pre_buf = []
            elif current is not None:
                current["body"].append(text)
            else:
                pre_buf.append(text)
                stats_extra["orphan_rows"] += 1
    if current:
        current["closed_by"] = "eof"
        finalize(current)

    return {
        "records": records,
        "stats": {
            "total_records": len(records),
            "skipped": dict(sorted(skipped.items())),
            "orphan_rows": stats_extra["orphan_rows"],
            "section_headers": stats_extra["section_headers"],
            "truncated_records": stats_extra["truncated_records"],
            "pages": [r["page"] for r in records_pages],
            "number_gaps": number_gaps([r["entry_no"] for r in records]),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="化妆品原料手册(新) 条目切分与用途提取")
    ap.add_argument("--inp", required=True, help="reorder_shouce.py 产物 JSONL")
    ap.add_argument("--out", required=True)
    ap.add_argument("--pages", default="", help="只处理指定页，如 150,211,300；缺省全部")
    args = ap.parse_args()

    page_filter = {int(p) for p in args.pages.split(",") if p.strip()} or None
    pages: list[dict] = []
    pdf_name = ""
    with open(args.inp, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if page_filter and rec["page"] not in page_filter:
                continue
            pdf_name = pdf_name or rec.get("pdf", "")
            pages.append(rec)
    pages.sort(key=lambda r: r["page"])

    result = extract(pages)
    out = {
        "source": {
            "file": pdf_name,
            "nature": NATURE,
            "ocr_source": "data/raw/ocr/shouce_boxed.jsonl（经 reorder_shouce.py 双栏重排）",
            "fields": "仅可信字段：编号/中文名/英文名/别名/用途叙述句（verbatim，OCR 错字未核订）；表格限值/化学式/结构式不抽",
        },
        "stats": result["stats"],
        "records": result["records"],
    }
    Path(args.out).write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"extract: {result['stats']['total_records']} records, "
          f"skipped={result['stats']['skipped']} -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
