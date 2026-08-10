"""阶段三 loader：CIR 安全评估（white_paper）+ SCCS 意见（regulation）+ 专利降级通道（patent）。

数据源：
1. data/research/batch-9-cir.verified.json —— CIR（美国化妆品原料评价委员会，行业
   自评机构）安全评估报告，采集/解析 data/tools/collect_cir.py，57 个浓度候选经
   人工逐条回读 PDF 原文核订（修正表 data/tools/review_cir_batch.py），
   机器核验 verify_evidence.py 全过。证据 type=white_paper（CIR 是行业自评，
   非监管文件）；断言 efficacy_canonical **固定「其他」**（安全评估非功效断言，
   防止「美白/防腐」等字样被子串规则误归功效族，对齐 regulation_loader 先例）。
2. data/seed/sccs_opinions.json —— 欧盟 SCCS 意见/科学建议，结论句逐条人工核订
   （来源链与核对说明见 seed source 字段）。证据 type=regulation（官方科学委员会，
   监管决策科学依据）；sccs_limit 统一回填该意见内最严上限（多场景结论取最严值，
   分场景上限保留在 scope/note）；「不安全」结论不回填。
3. data/research/batch-9-patent.verified.json —— 专利降级通道（数据铁律允许，
   措辞规范：note 固定含「专利申请人自述数据，未经同行评议」）；证据层级强制
   unknown（强度 0.2），即使 note 含「体外」等关键词也不走 classify 升级——
   申请人自述数据天然弱于同行评议，降级通道必须落最低档。

共同规则（对齐 regulation_loader 先例，改动须重审）：
- 证据按 title 去重；断言按 (ingredient_id, evidence_id) 定位，陈旧行原地同步
  efficacy/note/evidence_level/evidence_strength/efficacy_canonical，不增生；
- cir_conc_low/high、sccs_limit 只回填 NULL 行，已有值不覆盖、不同记冲突日志；
  例外：本 loader 三个数据源均为人工核订主数据，main 以 allow_correction=True
  调用——库里旧值与核订值不同时执行「核订修正」覆盖并记日志（旧值→新值）；
  函数默认 allow_correction=False 保持不覆盖铁律，库调用方需显式开启；
- sccs_limit 与既有 legal_cap 不一致时记日志（两列语义不同：SCCS 是欧盟评估上限、
  legal_cap 是中国法规上限，并存不互相覆盖；断言 note 已写明分场景口径）；
- 成分按 inci_name 大小写无关匹配，多行取 id 最小并记日志。

运行：PYTHONPATH="backend:." .venv/bin/python data/loaders/cir_sccs_loader.py [--dry-run]
"""

import argparse
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.services.efficacy_canon import OTHER as CANON_OTHER, canonicalize
from app.services.evidence_level import (
    UNKNOWN, classify_evidence_level, default_strength,
)

DATA = Path(__file__).resolve().parents[1]
CIR_BATCH = DATA / "research" / "batch-9-cir.verified.json"
CIR_RAW_BATCH = DATA / "research" / "batch-9-cir.json"  # 人工核订后的完整件（含仅浓度回填成分）
SCCS_SEED = DATA / "seed" / "sccs_opinions.json"
PATENT_BATCH = DATA / "research" / "batch-9-patent.verified.json"

CIR_NOTE = ("CIR（美国化妆品原料评价委员会）专家小组安全评估结论，"
            "为行业自评机构意见而非监管限值；浓度来自 PCPC 行业使用调查，"
            "非功效起效浓度")


def _find_ingredient(session: Session, inci: str, stats: dict) -> Ingredient | None:
    rows = (session.query(Ingredient)
            .filter(Ingredient.inci_name.ilike(inci))
            .order_by(Ingredient.id).all())
    if not rows:
        if inci not in stats["unmatched"]:
            stats["unmatched"].append(inci)
        return None
    if len(rows) > 1:
        stats["log"].append(f"多行命中 {inci!r}：取 id={rows[0].id}（其余 {[r.id for r in rows[1:]]}）")
    return rows[0]


def _get_evidence(session: Session, ev_spec: dict, stats: dict) -> Evidence:
    ev = session.query(Evidence).filter_by(title=ev_spec["title"]).one_or_none()
    if ev is not None:
        stats["evidence_existing"] += 1
        return ev
    ev = Evidence(type=EvidenceType(ev_spec["type"]), title=ev_spec["title"],
                  source=ev_spec.get("source"), year=ev_spec.get("year"),
                  url=ev_spec.get("url"), excerpt=(ev_spec.get("excerpt") or "")[:1900])
    session.add(ev)
    session.flush()
    stats["evidence_new"] += 1
    return ev


def _upsert_assertion(session: Session, ing: Ingredient, ev: Evidence,
                      efficacy: str, note: str, level: str,
                      canonical: str, stats: dict) -> None:
    strength = default_strength(level)
    existing = (session.query(EfficacyAssertion)
                .filter_by(ingredient_id=ing.id, evidence_id=ev.id)
                .one_or_none())
    if existing is not None:
        dirty = False
        for field, value in (("efficacy", efficacy), ("note", note),
                             ("evidence_level", level), ("evidence_strength", strength),
                             ("efficacy_canonical", canonical)):
            if getattr(existing, field) != value:
                stats["log"].append(
                    f"断言同步 #{existing.id} {field}: "
                    f"{str(getattr(existing, field))[:40]!r} -> {str(value)[:40]!r}")
                setattr(existing, field, value)
                dirty = True
        stats["assertions_updated" if dirty else "assertions_existing"] += 1
        return
    session.add(EfficacyAssertion(
        ingredient_id=ing.id, efficacy=efficacy, evidence_id=ev.id,
        note=note, evidence_level=level, evidence_strength=strength,
        efficacy_canonical=canonical))
    stats["assertions_new"] += 1


def _backfill(ing: Ingredient, field: str, value, stats: dict,
              allow_correction: bool = False, clear_none: bool = False) -> None:
    """只回填 NULL 行；已有值不同记冲突日志，不覆盖。
    allow_correction=True（人工核订主数据同步）时执行核订修正覆盖并记日志。
    clear_none=True 且 allow_correction=True 时，核订数据显式 null 表示
    「经核对无报告浓度」，清掉已有旧值并记核订修正日志。"""
    cur = getattr(ing, field)
    if value is None:
        if clear_none and allow_correction and cur is not None:
            setattr(ing, field, None)
            stats[f"{field}_corrected"] += 1
            stats["log"].append(
                f"核订修正 {field} #{ing.id} {ing.inci_name!r}：旧值 {cur} → 新值 None")
        return
    if cur is None:
        setattr(ing, field, value)
        stats[f"{field}_set"] += 1
        stats["log"].append(f"{field} #{ing.id} {ing.inci_name!r} = {value}")
    elif cur != value:
        if allow_correction:
            setattr(ing, field, value)
            stats[f"{field}_corrected"] += 1
            stats["log"].append(
                f"核订修正 {field} #{ing.id} {ing.inci_name!r}：旧值 {cur} → 新值 {value}")
        else:
            stats[f"{field}_conflict"] += 1
            stats["log"].append(
                f"{field} 冲突不覆盖 #{ing.id} {ing.inci_name!r}：现有 {cur}，新 {value}")


def _stats() -> dict:
    return {"evidence_new": 0, "evidence_existing": 0,
            "assertions_new": 0, "assertions_existing": 0, "assertions_updated": 0,
            "cir_conc_low_set": 0, "cir_conc_low_conflict": 0, "cir_conc_low_corrected": 0,
            "cir_conc_high_set": 0, "cir_conc_high_conflict": 0, "cir_conc_high_corrected": 0,
            "sccs_limit_set": 0, "sccs_limit_conflict": 0, "sccs_limit_corrected": 0,
            "unmatched": [], "log": []}


def load_cir(session: Session, batch: dict, conc_batch: dict | None = None,
             allow_correction: bool = False) -> dict:
    """CIR batch → white_paper 证据 + 安全评估断言（canonical 固定「其他」）
    + cir_conc_low/high 回填。幂等。

    batch 为 verify_evidence.py 通过件（只保留有断言的成分）；
    conc_batch 为人工核订后的完整 batch（160 成分，含 23 个仅浓度回填、
    无断言的成分）——verify 输出会丢掉无断言成分，浓度回填须从完整件取。
    allow_correction=True 时 cir_conc 已有值与核订值不同执行核订修正覆盖；
    核订数据显式 null 表示经核对无报告浓度，清掉已有旧值（clear_none）。"""
    stats = _stats()
    conc_map = {i["inci_name"]: i for i in (conc_batch or batch)["ingredients"]}
    for inci, item in conc_map.items():
        ing = _find_ingredient(session, inci, stats)
        if ing is None:
            continue
        _backfill(ing, "cir_conc_low", item.get("cir_conc_low"), stats,
                  allow_correction=allow_correction, clear_none=True)
        _backfill(ing, "cir_conc_high", item.get("cir_conc_high"), stats,
                  allow_correction=allow_correction, clear_none=True)
    for item in batch["ingredients"]:
        ing = _find_ingredient(session, item["inci_name"], stats)
        if ing is None:
            continue
        for a in item["assertions"]:
            ev = _get_evidence(session, a["evidence"], stats)
            note = a.get("note") or CIR_NOTE
            level = classify_evidence_level(note, ev)  # white_paper 无信号 → unknown
            _upsert_assertion(session, ing, ev, a["efficacy"], note,
                              level, CANON_OTHER, stats)
    session.flush()
    return stats


def load_sccs(session: Session, seed: dict, allow_correction: bool = False) -> dict:
    """SCCS seed → regulation 证据 + 安全评估断言（canonical 固定「其他」）
    + sccs_limit 回填（默认不覆盖；allow_correction=True 时核订修正覆盖；
    与 legal_cap 不一致记日志）。幂等。"""
    stats = _stats()
    for entry in seed["entries"]:
        ing = _find_ingredient(session, entry["inci_name"], stats)
        if ing is None:
            continue
        _backfill(ing, "sccs_limit", entry.get("sccs_limit"), stats,
                  allow_correction=allow_correction)
        if entry.get("sccs_limit") is not None and ing.legal_cap is not None \
                and ing.legal_cap != entry["sccs_limit"]:
            stats["log"].append(
                f"sccs_limit 与 legal_cap 口径差异 #{ing.id} {ing.inci_name!r}："
                f"legal_cap={ing.legal_cap}（中国法规），sccs_limit={entry['sccs_limit']}（SCCS）")
        ev_spec = {"type": "regulation",
                   "title": f"SCCS 意见 {entry['opinion_no']}：{entry['title']}",
                   "source": "European Commission SCCS",
                   "year": int(entry["adopted"][:4]) if entry.get("adopted") else None,
                   "url": entry["url"],
                   "excerpt": (f"SCCS 意见 {entry['opinion_no']}（{entry['adopted']} 通过）："
                               f"{entry['excerpt']} 适用范围：{entry['scope']}。"
                               f"{entry['note']}")}
        ev = _get_evidence(session, ev_spec, stats)
        note = (f"SCCS（欧盟消费者安全科学委员会）安全评估意见，非功效起效浓度。"
                f"{entry['note']}")
        level = classify_evidence_level(note, ev)  # regulation 类型 → regulation 档
        _upsert_assertion(session, ing, ev, entry["assertion"], note,
                          level, CANON_OTHER, stats)
    session.flush()
    return stats


def load_patent(session: Session, batch: dict) -> dict:
    """专利 batch → patent 证据 + 降级断言（层级强制 unknown/0.2，canonical 走规则）。幂等。"""
    stats = _stats()
    for item in batch["ingredients"]:
        ing = _find_ingredient(session, item["inci_name"], stats)
        if ing is None:
            continue
        for a in item["assertions"]:
            ev = _get_evidence(session, a["evidence"], stats)
            note = a.get("note") or ""
            # 降级通道：专利申请人自述数据，层级强制 unknown（不走 classify 升级）
            _upsert_assertion(session, ing, ev, a["efficacy"], note,
                              UNKNOWN, canonicalize(a["efficacy"]), stats)
    session.flush()
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cir-batch", default=str(CIR_BATCH))
    ap.add_argument("--cir-raw-batch", default=str(CIR_RAW_BATCH))
    ap.add_argument("--sccs-seed", default=str(SCCS_SEED))
    ap.add_argument("--patent-batch", default=str(PATENT_BATCH))
    ap.add_argument("--dry-run", action="store_true", help="只统计不落库（事务回滚）")
    args = ap.parse_args()

    init_db()
    cir = json.loads(Path(args.cir_batch).read_text(encoding="utf-8"))
    cir_raw = json.loads(Path(args.cir_raw_batch).read_text(encoding="utf-8"))
    sccs = json.loads(Path(args.sccs_seed).read_text(encoding="utf-8"))
    patent = json.loads(Path(args.patent_batch).read_text(encoding="utf-8"))
    with SessionLocal() as s:
        # 三个人工核订数据源为主数据：开启核订修正模式，库内旧值原地同步为核订值
        st_cir = load_cir(s, cir, conc_batch=cir_raw, allow_correction=True)
        st_sccs = load_sccs(s, sccs, allow_correction=True)
        st_pat = load_patent(s, patent)
        if args.dry_run:
            s.rollback()
            print("DRY-RUN：已回滚，未落库")
        else:
            s.commit()
    for name, st in (("CIR", st_cir), ("SCCS", st_sccs), ("专利", st_pat)):
        print(f"{name}：证据新增={st['evidence_new']} 已存在={st['evidence_existing']} "
              f"断言新增={st['assertions_new']} 已存在={st['assertions_existing']} "
              f"陈旧同步={st['assertions_updated']} "
              f"cir_conc回填={st['cir_conc_low_set'] + st['cir_conc_high_set']} "
              f"sccs_limit回填={st['sccs_limit_set']} "
              f"核订修正={st['cir_conc_low_corrected'] + st['cir_conc_high_corrected'] + st['sccs_limit_corrected']} "
              f"冲突不覆盖="
              f"{st['cir_conc_low_conflict'] + st['cir_conc_high_conflict'] + st['sccs_limit_conflict']}")
        if st["unmatched"]:
            print(f"  未命中成分（{len(st['unmatched'])}）：" + "、".join(st["unmatched"][:20]))
        for line in st["log"]:
            print(" ", line)


if __name__ == "__main__":
    main()
