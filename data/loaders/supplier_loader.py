"""供应商原料资料加载器：data/research/supplier_ingredients.json → 断言入库（降级通道）。

数据性质（铁律，措辞口径与专利降级通道同级保守）：
- 功效文本是**原料商产品资料宣称**，未经同行评议 —— evidence type=supplier，
  evidence_level 强制 unknown（不走 classify 升级），strength 取 unknown 默认 0.2；
- efficacy 措辞一律「原料商宣称：XX」；note 固定注明「原料商产品资料宣称，未经同行评议」，
  并附商品名/类别 sheet/生产商；复配原料（多组分）断言追加注明
  「复配宣称，功效指向复配整体而非单一成分」；
- 功效短语切分保守：只接受 2-8 字纯中文（允许·）短语，长散文片段不切不猜
  （计数 prose_skipped 如实记录）；「功效性活性成分」等 sheet 的类别列（美白/抗氧化…）
  是干净分类，作为短语候选并入；
- 中文名只用于匹配（铁律 6 不变）：inci_cn 精确命中 ingredients.cn_name 或
  IECIC 中文名唯一反查 → INCI，绝不拿供应商中文名入库当成分名。

成分匹配顺序（命中即停，全程不猜）：
1. inci_en 归一化（压空白+大写）精确命中 ingredients.inci_name
2. 折叠形（去非字母数字、CJK/数字保留）全库唯一命中（同 inci_cn_loader 口径）
3. USAN 别名表（data/seed/usan_inci_alias.json，同 CID 核验过的官方别名）
4. inci_cn 精确命中 ingredients.cn_name（唯一），或 IECIC 中文名唯一反查 INCI 后命中
多组分逐组分匹配，各自挂断言；全部未命中计入 unmatched 报告，不创建成分。
中文通道只在无英文组分（整行无拉丁字母）时触发——中英混排组分（如 `PEG-11甲醚 …`）
走英文通道必然不命中、中文通道不触发，是已知的召回损失（不猜优先于召回）。

幂等：evidence 按 title 去重（每 sheet 一条）、断言按 (ingredient_id, efficacy, evidence_id)；
重复执行不增生。匹配报告落 data/research/supplier_match_report.json。

运行：PYTHONPATH="backend:." .venv/bin/python data/loaders/supplier_loader.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.services.efficacy_canon import OTHER, canonicalize
from app.services.evidence_level import UNKNOWN, default_strength

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = REPO_ROOT / "data" / "research" / "supplier_ingredients.json"
DEFAULT_REPORT = REPO_ROOT / "data" / "research" / "supplier_match_report.json"
IECIC_MAP = REPO_ROOT / "data" / "seed" / "inci_cn_map.json"
USAN_ALIAS = REPO_ROOT / "data" / "seed" / "usan_inci_alias.json"

EVIDENCE_SOURCE = "原料商产品资料（供应商手册，欧莱雅比赛原料库 xls）"
NOTE_DISCLAIMER = "原料商产品资料宣称，未经同行评议"
BLEND_NOTE = "复配宣称，功效指向复配整体而非单一成分"

_WS = re.compile(r"\s+")
_COLLAPSE = re.compile(r"[^A-Z0-9一-鿿]+")  # 折叠形：去非字母数字（数字/CJK 保留，同 inci_cn_loader 口径）
# 功效短语：2-8 字、纯中文（允许·）。供应商功效关键词多为 2-6 字（美白/保湿/抗氧化）；
# 上限 8 覆盖「修复皮肤屏障」类，同时把「硅油可改善油脂的腻感」这类 10+ 字散文挡住
_PHRASE = re.compile(r"^[一-鿿·]{2,8}$")
_TEXT_SPLIT = re.compile(r"[、，,；;\n]")


def _norm_inci(name: str) -> str:
    return _WS.sub(" ", name.strip()).upper()


def _fold(name: str) -> str:
    return _COLLAPSE.sub("", _norm_inci(name))


def split_efficacy_phrases(rec: dict) -> tuple[list[str], int]:
    """功效文本 → 短语列表 + prose_skipped 计数。

    切分后只收 2-8 字纯中文短语；类别列（干净分类）并入候选；去重保持顺序。
    长散文片段不收（不硬切不猜），计数返回。
    """
    candidates: list[str] = []
    cat = rec.get("category", "").strip()
    # 类别列只收能归入功效族的值（「水包油」这类工艺类型会被 canonicalize 落「其他」，挡住）
    if cat and _PHRASE.match(cat) and canonicalize(cat) != OTHER:
        candidates.append(cat)
    skipped = 0
    for frag in _TEXT_SPLIT.split(rec.get("function_text", "")):
        frag = frag.strip()
        if not frag:
            continue
        if _PHRASE.match(frag):
            candidates.append(frag)
        else:
            skipped += 1
    seen: set[str] = set()
    phrases = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            phrases.append(c)
    return phrases, skipped


class Matcher:
    """成分匹配器：一次性建索引（INCI 精确/折叠形/USAN 别名/中文名/IECIC 反查）。"""

    def __init__(self, session: Session):
        self._by_inci: dict[str, int] = {}
        self._by_fold: dict[str, list[int]] = {}
        self._by_cn: dict[str, list[int]] = {}
        for ing in session.query(Ingredient).all():
            key = _norm_inci(ing.inci_name)
            self._by_inci[key] = ing.id
            self._by_fold.setdefault(_fold(ing.inci_name), []).append(ing.id)
            self._by_cn.setdefault(ing.cn_name.strip(), []).append(ing.id)
        # USAN 别名 → INCI（同 CID 核验过的官方别名，铁律 6 允许用于匹配）
        self._usan: dict[str, str] = {}
        if USAN_ALIAS.exists():
            data = json.loads(USAN_ALIAS.read_text(encoding="utf-8"))
            for section in ("alias", "alias_ceramide", "alias_common"):
                for alias, inci in data.get(section, {}).items():
                    self._usan[_norm_inci(alias)] = inci
        # IECIC 中文名 → INCI 反查（只收唯一映射；一对多中文名不猜）
        cn2inci: dict[str, list[str]] = {}
        if IECIC_MAP.exists():
            data = json.loads(IECIC_MAP.read_text(encoding="utf-8"))
            for inci, meta in data["map"].items():
                cn2inci.setdefault(meta["cn_name"].strip(), []).append(inci)
        self._cn2inci = {cn: incis[0] for cn, incis in cn2inci.items() if len(incis) == 1}

    def match_en(self, inci_en: str) -> int | None:
        """英文通道：精确 → 折叠唯一 → USAN 别名。"""
        key = _norm_inci(inci_en)
        if not key:
            return None
        if key in self._by_inci:
            return self._by_inci[key]
        hits = self._by_fold.get(_fold(key), [])
        if len(hits) == 1:
            return hits[0]
        target = self._usan.get(key)
        if target and _norm_inci(target) in self._by_inci:
            return self._by_inci[_norm_inci(target)]
        return None

    def match_cn(self, inci_cn: str) -> int | None:
        """中文通道（只用于匹配，不入库改名）：cn_name 唯一命中 / IECIC 反查唯一。"""
        key = inci_cn.strip()
        if not key:
            return None
        hits = self._by_cn.get(key, [])
        if len(hits) == 1:
            return hits[0]
        inci = self._cn2inci.get(key)
        if inci and _norm_inci(inci) in self._by_inci:
            return self._by_inci[_norm_inci(inci)]
        return None


def _get_or_create_evidence(session: Session, sheet: str, n_records: int,
                            stats: dict) -> Evidence:
    # title 不含行数：xls 更新/解析规则调整导致行数变化时幂等键不失效；
    # 条目数放 excerpt 供溯源（更新后 excerpt 会过时，以最新解析报告为准）
    title = f"原料商资料库·{sheet}"
    ev = session.query(Evidence).filter_by(title=title).one_or_none()
    if ev is None:
        ev = Evidence(
            type=EvidenceType.SUPPLIER, title=title, source=EVIDENCE_SOURCE,
            year=None, url=None,
            excerpt=(f"原料商（供应商）产品资料中的原料性能/功效描述（{sheet}类，"
                     f"首次入库 {n_records} 条目），为供应商产品宣称，"
                     "未经同行评议，不构成对皮肤功效的临床/实验实证。"))
        session.add(ev)
        session.flush()
        stats["evidence_new"] += 1
    return ev


def load_supplier(session: Session, data: dict, stats: dict | None = None) -> dict:
    """按解析 JSON 对库内成分批量生成供应商宣称断言。幂等，返回统计。"""
    if stats is None:
        stats = {}
    for k in ("records", "records_no_function", "components_matched",
              "components_unmatched", "assertions_new", "assertions_existing",
              "evidence_new", "prose_skipped"):
        stats.setdefault(k, 0)
    unmatched: list[dict] = []
    matcher = Matcher(session)
    evidences: dict[str, Evidence] = {}
    sheet_sizes = {name: st["rows"] for name, st in data["stats"]["by_sheet"].items()}
    # 同次运行内的已建键（autoflush=False，exists 查询看不到 pending 行，必须本地留痕）
    seen_keys: set[tuple[int, str, int]] = set()

    for rec in data["records"]:
        stats["records"] += 1
        phrases, skipped = split_efficacy_phrases(rec)
        stats["prose_skipped"] += skipped
        if not phrases:
            stats["records_no_function"] += 1
            continue
        sheet = rec["sheet"]
        if sheet not in evidences:
            evidences[sheet] = _get_or_create_evidence(
                session, sheet, sheet_sizes.get(sheet, 0), stats)
        ev = evidences[sheet]

        # 成分解析：英文组分逐个匹配；无英文组分时整行走中文通道
        targets: list[int] = []
        if rec["components"]:
            for comp in rec["components"]:
                iid = matcher.match_en(comp)
                if iid is not None:
                    if iid not in targets:
                        targets.append(iid)
                    stats["components_matched"] += 1
                else:
                    stats["components_unmatched"] += 1
                    unmatched.append({"product_name": rec["product_name"],
                                      "sheet": sheet, "component": comp})
        else:
            # 中文通道只在整行无英文组分时触发（components 为空）：
            # 中英混排单元格走英文通道（中文部分不命中，已知召回损失，不猜）
            for cand in (rec["inci_cn"], rec["inci_en"]):
                if not cand or not cand.strip():
                    continue
                iid = matcher.match_cn(cand)
                if iid is not None:
                    targets.append(iid)
                    stats["components_matched"] += 1
                    break
            else:
                stats["components_unmatched"] += 1
                unmatched.append({"product_name": rec["product_name"],
                                  "sheet": sheet,
                                  "component": rec["inci_cn"] or rec["inci_en"] or "(无 INCI)"})
        if not targets:
            continue

        is_blend = len(rec["components"]) > 1
        for iid in targets:
            for phrase in phrases:
                efficacy = f"原料商宣称：{phrase}"
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
                note = (f"{NOTE_DISCLAIMER}（商品名：{rec['product_name'] or '?'}；"
                        f"类别：{sheet}；生产商：{rec['producer'] or '?'}）")
                if is_blend:
                    note += f"；{BLEND_NOTE}"
                session.add(EfficacyAssertion(
                    ingredient_id=iid, efficacy=efficacy, evidence_id=ev.id,
                    note=note,
                    evidence_level=UNKNOWN,  # 供应商宣称：强制 unknown，不走 classify 升级
                    evidence_strength=default_strength(UNKNOWN),
                    efficacy_canonical=canonicalize(phrase)))
                seen_keys.add(key)
                stats["assertions_new"] += 1
    session.flush()
    stats["unmatched"] = unmatched
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
        stats = load_supplier(session, data)
        unmatched = stats.pop("unmatched")
        if args.dry_run:
            session.rollback()
            print("（dry-run，已回滚）")
        else:
            session.commit()
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(
            {"stats": stats, "unmatched": unmatched}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        for k, v in stats.items():
            print(f"  {k}: {v}")
        print(f"匹配报告 → {args.report}（unmatched {len(unmatched)} 条）")
    finally:
        session.close()


if __name__ == "__main__":
    main()
