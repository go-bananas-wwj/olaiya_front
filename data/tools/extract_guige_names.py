"""《化妆品原料技术规格》OCR 产物 → 原料条目「中文名+英文名」名对提取（保守通道）。

数据来源：data/raw/ocr/full.jsonl（每行 {"pdf","page","text","ocr_ms"}，本书 pdf 字段含「技术规格」）。
该书为日本官方原料规格译本，单栏排版，条目版式（抽样核订确认）：

    <编号>.<中文名>          例：3.硬脂酸辛酯
    <英文名>                 例：2-Ethyl hexyl Stearate   （长名可折行 1-2 行）
    （别名，……）            可选，括号行
    本品…… / 性状……         正文起始句

提取规则（高置信才收，拿不准一律 skip 并如实计数，绝不猜）：
1. 页首「化妆品技术在线 HzpOnline」水印行一律丢弃；
2. 标题行必须匹配 `^\\d{1,3}[.、．]<中文名>`：中文名含 ≥2 个 CJK 表意字、
   不含 =％%：:。；; 等正文特征字符、不以目录引导点（·/...）结尾；
3. 标题下一行必须是英文行（无 CJK、≥3 个拉丁字母）；英文名允许折行
   （后续英文行且非括号行则拼接，至多 2 行）；括号别名行跳过不存；
4. 英文名（及别名行）之后必须紧跟「本品/性状/参考」开头的正文起始句作确认，
   否则视为断头漏识/版式存疑，跳过并计 no_confirm；
5. 支持跨页标题（标题在页尾、英文名在下页页首）；重复扫描页按 (中文名, 英文名)
   去重，保留首页码，计 dup_removed。

输出：data/research/guige_name_pairs.json（source/stats/pairs 三段式）。
仅名对提取，不入库、不建断言。

库内匹配（可选）：--match 用 data/loaders/supplier_loader.py 的 Matcher
（INCI 精确/折叠形唯一/USAN 别名/中文名唯一+IECIC 反查，全程不猜）逐对匹配，
报告落 data/research/guige_name_match_report.json。

运行：
  .venv/bin/python data/tools/extract_guige_names.py                 # 只提取
  PYTHONPATH="backend:." .venv/bin/python data/tools/extract_guige_names.py --match
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JSONL = REPO_ROOT / "data" / "raw" / "ocr" / "full.jsonl"
DEFAULT_OUT = REPO_ROOT / "data" / "research" / "guige_name_pairs.json"
DEFAULT_REPORT = REPO_ROOT / "data" / "research" / "guige_name_match_report.json"
PDF_FILTER = "技术规格"

# 页首水印行（OCR 变体：化妆品技术在线 / 化妆品技在线 / HzpOnline / Hzponllae 等）
_WATERMARK = re.compile(r"Hzp|化妆品技术?在线|Hzponllae", re.I)
# 条目标题行：编号.中文名
_TITLE = re.compile(r"^\s*(\d{1,3})[.、．]\s*(\S.*)$")
_CJK = re.compile(r"[一-鿿]")
_CJK_PUNCT = re.compile(r"[、。，；：（）「」【】]")
# 中文名中不允许出现的正文特征字符
_BAD_IN_CN = re.compile(r"[=％%：:。；;]")
# 目录引导点结尾（如「山楂提取液...」「硬脂酸乙酯.···.」）
_TOC_LEADER = re.compile(r"[.·…‥]{2,}\s*$|[·…‥]\s*$")
# 正文起始句确认
_CONFIRM = re.compile(r"^(本品|性状|参考)")
# 英文行允许字符外的「其他字符」比例上限
_EN_ALLOWED = re.compile(r"[A-Za-z0-9\s\-.,()'’/°%&+·\[\]α-ωΑ-Ω]")

MAX_EN_CONT = 2   # 英文名最多再折 2 行
MAX_ALIAS = 3     # 括号别名行最多跳过 3 行


def strip_watermark(lines: list[str]) -> list[str]:
    """丢弃水印行与空行。"""
    return [ln.strip() for ln in lines if ln.strip() and not _WATERMARK.search(ln)]


def _cjk_count(s: str) -> int:
    return len(_CJK.findall(s))


def valid_cn_name(body: str) -> bool:
    """标题行中文名基本校验（不含正文特征字符、≥2 个 CJK 字）。"""
    body = body.strip()
    if not (2 <= len(body) <= 60):
        return False
    if _cjk_count(body) < 2:
        return False
    if _BAD_IN_CN.search(body):
        return False
    return True


def is_en_line(s: str) -> bool:
    """英文名行：无 CJK（含 CJK 标点）、≥3 个拉丁字母、允许字符占比 ≥0.9。"""
    s = s.strip()
    if len(s) < 4:
        return False
    if _CJK.search(s) or _CJK_PUNCT.search(s):
        return False
    if sum(c.isascii() and c.isalpha() for c in s) < 3:
        return False
    if "=" in s or "→" in s:
        return False
    allowed = len(_EN_ALLOWED.findall(s))
    return allowed / len(s) >= 0.9


def _is_paren_line(s: str) -> bool:
    s = s.strip()
    return bool(s) and s[0] in "(（[" and s[-1:] in ")）]"


def is_en_continuation(s: str) -> bool:
    """英文名折行的续行：是英文行且不是整行括号（整行括号视为别名行）。"""
    return is_en_line(s) and not _is_paren_line(s)


def extract_pairs(pages: list[tuple[int, str]]) -> tuple[list[dict], dict]:
    """从 (页码, OCR 文本) 序列提取名对。返回 (pairs, stats)。"""
    # 拍平为跨页行流（每行带页码），水印/空行已剔除
    stream: list[tuple[int, str]] = []
    for page, text in pages:
        for ln in strip_watermark(text.split("\n")):
            stream.append((page, ln))

    stats = {
        "pages": len(pages),
        "stream_lines": len(stream),
        "title_candidates": 0,
        "skipped": {
            "invalid_title_body": 0,  # 编号行但中文名不合规（正文编号条款等）
            "toc_like": 0,            # 目录条目（引导点结尾）
            "no_en_line": 0,          # 标题下一行不是英文行（断头漏识等）
            "no_confirm": 0,          # 英文名后无「本品/性状/参考」确认句
        },
        "en_wrapped": 0,              # 英文名折行拼接次数
        "dup_removed": 0,
    }
    pairs: list[dict] = []
    seen: set[tuple[str, str]] = set()

    i = 0
    while i < len(stream):
        page, line = stream[i]
        m = _TITLE.match(line)
        if not m:
            i += 1
            continue
        stats["title_candidates"] += 1
        body = m.group(2).strip()
        if _TOC_LEADER.search(body):
            stats["skipped"]["toc_like"] += 1
            i += 1
            continue
        if not valid_cn_name(body):
            stats["skipped"]["invalid_title_body"] += 1
            i += 1
            continue
        # 英文名行（允许折行）
        j = i + 1
        if j >= len(stream) or not is_en_line(stream[j][1]):
            stats["skipped"]["no_en_line"] += 1
            i += 1
            continue
        en_parts = [stream[j][1].strip()]
        j += 1
        while j < len(stream) and len(en_parts) <= MAX_EN_CONT and is_en_continuation(stream[j][1]):
            en_parts.append(stream[j][1].strip())
            stats["en_wrapped"] += 1
            j += 1
        # 括号别名行（跳过不存）
        n_alias = 0
        while j < len(stream) and n_alias < MAX_ALIAS and _is_paren_line(stream[j][1]):
            n_alias += 1
            j += 1
        # 正文起始句确认
        if j >= len(stream) or not _CONFIRM.match(stream[j][1]):
            stats["skipped"]["no_confirm"] += 1
            i += 1
            continue
        en_name = " ".join(" ".join(en_parts).split())
        key = (body, en_name)
        if key in seen:
            stats["dup_removed"] += 1
            i += 1
            continue
        seen.add(key)
        pairs.append({"cn_name": body, "en_name": en_name, "page": page})
        i += 1

    stats["pairs"] = len(pairs)
    return pairs, stats


def load_pages(jsonl_path: Path, pdf_filter: str = PDF_FILTER) -> list[tuple[int, str]]:
    pages = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if pdf_filter in r["pdf"]:
                pages.append((r["page"], r["text"]))
    pages.sort(key=lambda x: x[0])
    return pages


def run_match(pairs: list[dict], report_path: Path) -> dict:
    """用 supplier_loader 的 Matcher 做库内匹配（全程不猜，未命中如实记录）。"""
    from app.db import SessionLocal, init_db
    from app.models.ingredient import Ingredient
    from data.loaders.supplier_loader import Matcher

    init_db()
    session = SessionLocal()
    try:
        matcher = Matcher(session)
        matched, unmatched = [], []
        by_channel = {"en": 0, "cn": 0}
        for p in pairs:
            ing_id = matcher.match_en(p["en_name"])
            via = "en"
            if ing_id is None:
                ing_id = matcher.match_cn(p["cn_name"])
                via = "cn"
            if ing_id is None:
                unmatched.append(p)
                continue
            ing = session.get(Ingredient, ing_id)
            by_channel[via] += 1
            matched.append({**p, "ingredient_id": ing_id,
                            "inci_name": ing.inci_name, "db_cn_name": ing.cn_name,
                            "via": via})
        report = {
            "source": "data/research/guige_name_pairs.json（《化妆品原料技术规格》条目名对）",
            "matcher": "data/loaders/supplier_loader.py Matcher"
                       "（INCI 精确/折叠形唯一/USAN 别名/中文名唯一+IECIC 反查，全程不猜）",
            "stats": {
                "total": len(pairs),
                "matched": len(matched),
                "unmatched": len(unmatched),
                "match_rate": round(len(matched) / len(pairs), 4) if pairs else 0.0,
                "by_channel": by_channel,
            },
            "matched": matched,
            "unmatched": unmatched,
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report["stats"]
    finally:
        session.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--jsonl", type=Path, default=DEFAULT_JSONL)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--match", action="store_true", help="提取后对名对做库内匹配并出报告")
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = ap.parse_args()

    pages = load_pages(args.jsonl)
    pairs, stats = extract_pairs(pages)
    out = {
        "source": {
            "book": "化妆品原料技术规格（宋国艾、杨根源、张宝旭编，中国轻工业出版社，2000.7）",
            "file": "欧莱雅比赛/原料相关/化妆品原料技术规格.pdf",
            "nature": "日本官方原料规格译本；条目名对（中文名+英文名）用于成分匹配增强，"
                      "不入库、不建断言；原书自称收载 1721 种原料",
            "pages": len(pages),
            "ocr": "data/raw/ocr/full.jsonl（rapidocr PP-OCRv4，页首水印行已丢弃）",
        },
        "stats": stats,
        "pairs": pairs,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"pairs={stats['pairs']} title_candidates={stats['title_candidates']} "
          f"skipped={sum(stats['skipped'].values())} dup_removed={stats['dup_removed']}")
    print(f"written: {args.out}")

    if args.match:
        mstats = run_match(pairs, args.report)
        print(f"matched={mstats['matched']}/{mstats['total']} "
              f"({mstats['match_rate']:.1%}) by_channel={mstats['by_channel']}")
        print(f"written: {args.report}")


if __name__ == "__main__":
    main()
