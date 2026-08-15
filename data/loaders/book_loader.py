"""工具书记载加载器：data/research/shouce_book.json（《化妆品原料手册(新)》提取结果）→ 断言入库。

数据性质（铁律 11 工具书通道）：
- 整本书一条 Evidence，type=book；断言 efficacy 一律「工具书记载：XX」，
  note 固定含条目编号/页码/用途句 verbatim +「行业参考工具书记载，非原始研究证据」
  +「用途句为 OCR 原文未核订，可能含形近字/上下标丢失」；
- evidence_level 强制 unknown（不走 classify 升级），strength 0.3
  （介于原料商宣称 0.2 与机分层级之间；backfill_evidence_level.py 对 BOOK 跳过回填）；
- efficacy_canonical 用**清洗后的完整用途句**走 canonicalize（不是截断后的 efficacy）。

入库护栏（OCR 产物未经核订禁止直接入库，以下四道为已核订结论的代码化）：
1. entry_no 前缀归一化：首段「0X」→「X」（02-1-112→2-1-112，抽查核订证实）；
   其他畸形前缀（72-3/92-3/12-1/32-1 等疑似多读一位）**不猜**，entry_no 原样保留
   在 note，仅统计上报；
2. 用途句清洗：在表格碎片标记（JSCI / FAO/WHO / GB<数字> / 指标名称 / 连续 4 段以上
   大写拉丁碎片如 HCCOOHHCHHCHHCH3）处截断；剥离尾部混入的下一条目名/拉丁尾巴
   （末句句读后的残留含拉丁字母或为「（二）」式章节头）；清洗后不以句读
   （。；！？）结尾的整条跳过不入库并计数；含「×10」+数字疑似上标丢失的记
   suspect 统计但保留（note 已含免责）；
3. 名称窄白名单订正（只限 cn_name/alias 匹配候选，正文 verbatim 不动）：
   NAME_WHITELIST 中每一条均已用 pymupdf 渲染原书该页亲眼核对字形（页码见注释），
   核对不了的不进白名单；alias 在「国外相应商品名/染料索引号/组成/主要成分/性质/
   本品/制法」等标签词处截断（截空则 alias 弃用，仅影响匹配不影响入库）；
4. cn_name 含 ≥4 连拉丁字母的：拉丁部分剥离（仅作 en 匹配候选），剥不出干净中文名
   （不足 2 个 CJK 字）则整条跳过并计数。

匹配顺序（命中即停，全程不猜）：cn_name（订正后）→ alias 各候选 → cn 剥出的拉丁
候选 → en_name，走 supplier_loader.Matcher 四通道（INCI 精确/折叠形/USAN 别名/中文
名+IECIC 反查）。未命中如实记 match report，不创建成分。

幂等：evidence 按 title 去重（整书一条）、断言按 (ingredient_id, efficacy, evidence_id)；
重复执行不增生。同 ingredients 多条目各自成断言（efficacy 文本不同即不同断言）。

运行：PYTHONPATH="backend:." .venv/bin/python data/loaders/book_loader.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion
from app.services.efficacy_canon import canonicalize
from app.services.evidence_level import UNKNOWN
from data.loaders.supplier_loader import Matcher

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = REPO_ROOT / "data" / "research" / "shouce_book.json"
DEFAULT_REPORT = REPO_ROOT / "data" / "research" / "shouce_book_match_report.json"

EVIDENCE_TITLE = "化妆品原料手册(新)"
EVIDENCE_SOURCE = "《化妆品原料手册(新)》（行业参考工具书，扫描版 OCR 提取可信字段）"
NOTE_DISCLAIMER = "行业参考工具书记载，非原始研究证据"
NOTE_OCR_DISCLAIMER = "用途句为 OCR 原文未核订，可能含形近字/上下标丢失"
EFFICACY_PREFIX = "工具书记载："
BOOK_STRENGTH = 0.3  # 铁律 11：工具书记载固定强度，介于原料商宣称 0.2 与机分层级之间

_EFFICACY_MAX = 100  # EfficacyAssertion.efficacy 是 String(100)
_END_PUNC = re.compile(r"[。；！？]")
# 护栏 2a：表格碎片标记（OCR 把质量指标表/文献表混排进用途句，表格数据一律不抽）
_TABLE_MARKER = re.compile(r"JSCI|FAO/WHO|GB\s*\d|指标名称")
# 护栏 2a 续：连续 4 段以上大写拉丁碎片（化学式残片如 HCCOOHHCHHCHHCH3；
# 4 段起步避免误伤 RHODICARE 这类 3 段以内商品名）
_LATIN_FRAG = re.compile(r"(?<![A-Za-z0-9])(?:[A-Z]{2,3}\d?){4,}(?![a-z])")
# 护栏 2b：末句句读后的残留尾巴 —— 含拉丁字母（下一条目名+英文名混入）或章节头（（二）…）
_TAIL_HEADER = re.compile(r"^[（(][一二三四五六七八九十0-9]+[)）]")
# 护栏 2c：「×10」+数字疑似上标丢失（10⁻⁶ → 10-6），记 suspect 但保留
_SUPERSCRIPT_SUSPECT = re.compile(r"×10\s*[-–—]?\s*\d")

# 护栏 1：首段「0X」→「X」
_ZERO_PREFIX = re.compile(r"^0(\d)-")

# 护栏 3：alias 标签词截断（别名后混入的「组成/性质/本品…」栏目内容不是别名）
_ALIAS_LABELS = ("国外相应商品名", "染料索引号", "组成", "主要成分", "性质", "本品", "制法")
_ALIAS_SPLIT = re.compile(r"[；;]")

# 护栏 4：cn_name 内 ≥4 连拉丁字母
_CN_LATIN = re.compile(r"[A-Za-z]{4,}")
_LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z0-9\s;：:()（）.\-~]*")
_CJK = re.compile(r"[一-鿿]")

# 护栏 3：名称窄白名单（只用于匹配候选订正，正文 verbatim 不动）。
# 每一条均已 pymupdf 渲染原书对应页（d[page-1].get_pixmap(dpi=200)）亲眼核对字形：
#   按叶油→桉叶油         p150 条目 2-2-002「桉叶油 Eucalyptus oil」（木字旁清晰）；
#                         p170 条目 2-2-061「柠檬桉叶油 Citriodora oil」（同字，一条规则覆盖）
#   对苯：：酚→对苯二酚   p357 条目 2-7-004「对苯二酚 Hydroquinone」（二被 OCR 成两点）
#   聚乙：醇→聚乙二醇     p303 条目 2-5-007「聚乙二醇 Polyethylene glycol」（同上）
#   二」基羟基甲苯→二丁基羟基甲苯  p298 条目 2-4-025「二丁基羟基甲苯 Dibutylhydroxytoluene」
#   廿油→甘油             p46 条目 1-1-081 别名「甘油三硬脂酸酯」、p131 条目 2-1-088
#                         标题「月桂酸甘油酯聚氧乙烯(78)醚」（甘字中横清晰）
#   廿草→甘草             p307 条目 2-6-006 别名「甘草甜素；甘草皂苷」、
#                         p328 条目 2-6-039 别名「β甘草亭酸」
#   麻油→蓖麻油           p8 条目 1-1-003「蓖麻油 Castor oil」别名「蓖麻籽油」
#                         （OCR 丢「蓖」；仅限 en_name 含 Castor 的条目，芝麻油义项不动）
NAME_WHITELIST: tuple[tuple[str, str], ...] = (
    ("按叶油", "桉叶油"),
    ("对苯：：酚", "对苯二酚"),
    ("聚乙：醇", "聚乙二醇"),
    ("二」基羟基甲苯", "二丁基羟基甲苯"),
    ("廿油", "甘油"),
    ("廿草", "甘草"),
)
_NAME_WHITELIST_CASTOR: tuple[tuple[str, str], ...] = (
    ("麻油", "蓖麻油"),
    ("麻籽油", "蓖麻籽油"),
)


def normalize_entry_no(entry_no: str) -> tuple[str, bool]:
    """护栏 1：首段「0X」→「X」。返回 (entry_no, 是否归一化)。其他畸形前缀不猜。"""
    m = _ZERO_PREFIX.match(entry_no)
    if m:
        return entry_no[1:], True
    return entry_no, False


def clean_purpose(purpose: str) -> tuple[str | None, dict]:
    """护栏 2：用途句清洗。返回 (清洗后用途句或 None=整条跳过, 命中标记)。"""
    flags = {"table_truncated": False, "tail_stripped": False,
             "superscript_suspect": False}
    text = purpose.strip()
    if _SUPERSCRIPT_SUSPECT.search(text):
        flags["superscript_suspect"] = True
    # 2a：表格碎片标记处截断（取最早的标记点）
    cut = min((m.start() for m in
               (_TABLE_MARKER.search(text), _LATIN_FRAG.search(text)) if m),
              default=None)
    if cut is not None:
        flags["table_truncated"] = True
        text = text[:cut].strip()
    # 2b：末句句读后的尾巴（下一条目名/拉丁残留/章节头）剥离
    ends = [m.end() for m in _END_PUNC.finditer(text)]
    if ends:
        tail = text[ends[-1]:]
        if tail and (re.search(r"[A-Za-z]", tail) or _TAIL_HEADER.match(tail)):
            flags["tail_stripped"] = True
            text = text[:ends[-1]]
    # 2c：清洗后不以句读结尾 → 句子残缺（表格塌缩/断头漏识），整条跳过不猜
    if not text or not _END_PUNC.search(text[-1]):
        return None, flags
    return text, flags


def apply_name_whitelist(name: str, en_name: str, stats: dict) -> str:
    """护栏 3：窄白名单订正（只作用于匹配候选字符串）。"""
    if not name:
        return name
    out = name
    for old, new in NAME_WHITELIST:
        if old in out:
            out = out.replace(old, new)
            stats["whitelist_applied"] += 1
    if "castor" in (en_name or "").lower():
        for old, new in _NAME_WHITELIST_CASTOR:
            if old in out:
                out = out.replace(old, new)
                stats["whitelist_applied"] += 1
    return out


def split_alias_candidates(alias: str | None) -> list[str]:
    """护栏 3 续：alias 在标签词处截断、按；;切候选、丢空/单字（截空则 alias 弃用）。"""
    if not alias:
        return []
    cut = min((i for lb in _ALIAS_LABELS if (i := alias.find(lb)) >= 0),
              default=len(alias))
    out: list[str] = []
    for cand in _ALIAS_SPLIT.split(alias[:cut]):
        cand = cand.strip(" 　，,、。；;：:")
        if len(cand) >= 2:  # 单字候选无匹配价值（如「本」），丢弃
            out.append(cand)
    return out


def strip_cn_latin(cn_name: str) -> tuple[str | None, str | None]:
    """护栏 4：cn_name 含 ≥4 连拉丁字母 → 剥离拉丁（返回 en 候选），
    剥不出干净中文名（<2 个 CJK 字）返回 (None, None) 由调用方整条跳过。"""
    if not _CN_LATIN.search(cn_name or ""):
        return cn_name, None
    latin = None
    m = _LATIN_RUN.search(cn_name)
    if m:
        latin = m.group().strip(" ;；:：.。-~") or None
    clean = _LATIN_RUN.sub("", cn_name).strip(" ;；:：.。-~（）()")
    if len(_CJK.findall(clean)) < 2:
        return None, latin
    return clean, latin


def _truncate_efficacy(purpose: str) -> str:
    """efficacy = 「工具书记载：」+用途句，超 String(100) 截断并以「…」标记。"""
    full = EFFICACY_PREFIX + purpose
    if len(full) <= _EFFICACY_MAX:
        return full
    return full[:_EFFICACY_MAX - 1] + "…"


def _get_or_create_evidence(session: Session, n_records: int, stats: dict) -> Evidence:
    # title 不含条目数：解析规则调整导致条目数变化时幂等键不失效
    ev = session.query(Evidence).filter_by(title=EVIDENCE_TITLE).one_or_none()
    if ev is None:
        ev = Evidence(
            type=EvidenceType.BOOK, title=EVIDENCE_TITLE, source=EVIDENCE_SOURCE,
            year=None, url=None,
            excerpt=(f"《化妆品原料手册(新)》（扫描版 OCR 双栏重排后提取，"
                     f"首次入库 {n_records} 条目）中各原料条目的用途叙述句。"
                     "行业参考工具书记载，非原始研究证据；用途句为 OCR 原文未核订，"
                     "可能含形近字/上下标丢失。"))
        session.add(ev)
        session.flush()
        stats["evidence_new"] += 1
    return ev


def load_book(session: Session, data: dict, stats: dict | None = None) -> dict:
    """按提取 JSON 对库内成分批量生成工具书记载断言。幂等，返回统计。"""
    if stats is None:
        stats = {}
    for k in ("records", "skipped_no_purpose", "skipped_no_endpunc",
              "skipped_cn_latin", "table_truncated", "tail_stripped",
              "superscript_suspect", "entry_no_normalized", "whitelist_applied",
              "cn_latin_stripped", "matched_cn", "matched_alias", "matched_en",
              "matched", "assertions_new", "assertions_existing", "evidence_new"):
        stats.setdefault(k, 0)
    unmatched: list[dict] = []
    odd_entry_nos: list[dict] = []
    matcher = Matcher(session)
    ev: Evidence | None = None
    # 同次运行内的已建键（autoflush=False，exists 查询看不到 pending 行，必须本地留痕）
    seen_keys: set[tuple[int, str, int]] = set()

    for rec in data["records"]:
        stats["records"] += 1
        purpose_raw = (rec.get("purpose") or "").strip()
        if not purpose_raw:
            stats["skipped_no_purpose"] += 1
            continue

        # 护栏 1：entry_no 前缀归一化；其他畸形前缀不猜，原样保留在 note 并上报
        entry_no, normalized = normalize_entry_no(rec["entry_no"])
        if normalized:
            stats["entry_no_normalized"] += 1
        elif not re.match(r"^[12]-\d+-\d+$", entry_no):
            odd_entry_nos.append({"entry_no": entry_no, "cn_name": rec.get("cn_name"),
                                  "page": rec.get("page")})

        # 护栏 2：用途句清洗；清洗后不以句读结尾整条跳过
        purpose, flags = clean_purpose(purpose_raw)
        for k, v in flags.items():
            if v:
                stats[k] += 1
        if purpose is None:
            stats["skipped_no_endpunc"] += 1
            continue

        # 护栏 4：cn_name 拉丁剥离
        cn_name, cn_latin = strip_cn_latin(rec.get("cn_name") or "")
        if cn_latin is not None:
            stats["cn_latin_stripped"] += 1
        if cn_name is None:
            stats["skipped_cn_latin"] += 1
            continue

        # 护栏 3：alias 截断切候选 + 窄白名单订正（只影响匹配候选）
        en_name = (rec.get("en_name") or "").strip()
        cn_cand = apply_name_whitelist(cn_name, en_name, stats)
        alias_cands = [apply_name_whitelist(a, en_name, stats)
                       for a in split_alias_candidates(rec.get("alias"))]

        # 匹配：cn → alias 各候选 → cn 剥出的拉丁候选 → en_name（命中即停，不猜）
        iid = matcher.match_cn(cn_cand)
        if iid is not None:
            stats["matched_cn"] += 1
        else:
            for cand in alias_cands:
                iid = (matcher.match_en(cand) if not _CJK.search(cand)
                       else matcher.match_cn(cand))
                if iid is not None:
                    stats["matched_alias"] += 1
                    break
            if iid is None:
                for cand in ([cn_latin] if cn_latin else []) + ([en_name] if en_name else []):
                    iid = matcher.match_en(cand)
                    if iid is not None:
                        stats["matched_en"] += 1
                        break
        if iid is None:
            unmatched.append({"entry_no": entry_no, "cn_name": rec.get("cn_name"),
                              "en_name": en_name, "page": rec.get("page")})
            continue
        stats["matched"] += 1

        if ev is None:
            ev = _get_or_create_evidence(session, len(data["records"]), stats)

        efficacy = _truncate_efficacy(purpose)
        key = (iid, efficacy, ev.id)
        if key in seen_keys:
            stats["assertions_existing"] += 1
            continue
        exists = (session.query(EfficacyAssertion)
                  .filter_by(ingredient_id=iid, efficacy=efficacy,
                             evidence_id=ev.id)
                  .one_or_none())
        if exists is not None:
            stats["assertions_existing"] += 1
            seen_keys.add(key)
            continue
        note = (f"条目编号：{entry_no}；页码：{rec.get('page')}；"
                f"用途原文（verbatim）：{purpose_raw}；"
                f"{NOTE_DISCLAIMER}；{NOTE_OCR_DISCLAIMER}")
        session.add(EfficacyAssertion(
            ingredient_id=iid, efficacy=efficacy, evidence_id=ev.id,
            note=note,
            evidence_level=UNKNOWN,  # 工具书记载：强制 unknown，不走 classify 升级
            evidence_strength=BOOK_STRENGTH,
            efficacy_canonical=canonicalize(purpose)))  # 完整用途句，非截断后
        seen_keys.add(key)
        stats["assertions_new"] += 1
    session.flush()
    stats["unmatched"] = unmatched
    stats["odd_entry_nos"] = odd_entry_nos
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", default=str(DEFAULT_INPUT))
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    ap.add_argument("--dry-run", action="store_true", help="只统计不写库（回滚）")
    args = ap.parse_args()

    init_db()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    session = SessionLocal()
    try:
        stats = load_book(session, data)
        unmatched = stats.pop("unmatched")
        odd_entry_nos = stats.pop("odd_entry_nos")
        if args.dry_run:
            session.rollback()
            print("（dry-run，已回滚）")
        else:
            session.commit()
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(
            {"stats": stats, "odd_entry_nos": odd_entry_nos,
             "unmatched": unmatched}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        for k, v in stats.items():
            print(f"  {k}: {v}")
        print(f"匹配报告 → {args.report}（unmatched {len(unmatched)} 条，"
              f"畸形前缀 {len(odd_entry_nos)} 条）")
    finally:
        session.close()


if __name__ == "__main__":
    main()
