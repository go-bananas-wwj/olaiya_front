"""NMPA 法规层证据 loader：功效宣称法规定义 + 安全技术规范表3 限用组分。

数据源（均为 seed JSON，来源链、版本与抽查核对说明见各 seed 的 source 字段）：
1. data/seed/efficacy_definitions.json —— 26 个功效宣称法定类别
   （2021 年第 49 号公告《化妆品分类规则和分类目录》附表 1 的功效定义
   + 2021 年第 50 号公告《化妆品功效宣称评价规范》附 1 的法定评价方法要求）。
2. data/seed/restricted_ingredients.json —— 《化妆品安全技术规范》（2015 年版）
   第二章表 3 化妆品限用组分 47 项（官方 PDF 抽取 + 人工校正 + 15 项抽查核对）。

入库决策（读 schema 与既有先例后定下，改动须重审）：
- 功效族定义**只入 26 条 regulation 证据，不建断言**：EfficacyAssertion.ingredient_id
  不可空，而功效族定义是类别层法规事实、不指向任何成分；挑「代表性成分」挂断言
  等于伪造成分断言（违反数据铁律 1）。定义对照留 seed 供 efficacy_canon 校准用。
- 表 3 限用条目是**成分层**法规事实，按既有先例（evidence id=5 苯氧乙醇/表 4）入库：
  * evidence 每「条目」一条（47 项中至少命中一个库内成分的才建，未命中族类条目
    不建死证据），excerpt 含适用范围/最大允许浓度/其他限制/标签警示原文；
    多物质条目（如苯甲酸及其钠盐）的多个命中成分共享同一条目证据；
  * 断言 efficacy 用 seed 人工裁定的 assertion 文本（「法定限用：…」风格，≤100 字），
    note 固定注明「法规限值，非功效起效浓度」并附条目序号；evidence_level 走
    app/services/evidence_level.py 统一规则（regulation 类型 → regulation 档）；
    efficacy_canonical **固定写「其他」**，不走 canonicalize 子串规则（断言文本可能
    含「非防腐用途/作防腐剂使用见表4」等字样，子串命中会把合规事实误归防腐族）；
  * legal_cap 只回填 seed 中裁定为「单一、无换算基准（非以酸计/以锶计等）、
    无多档分场景」的百分比上限（其余为 null 不回填）；已有值的成分行不覆盖，记冲突日志；
  * 成分匹配用 inci_cn_loader.InciResolver（IECIC 精确/派生/折叠形规则）；
    族类条目（「及其盐类/类/配合物」）seed 的 match_inci 为空，绝不猜测匹配。

幂等与迁移：evidence 按 title 去重；断言按 (ingredient_id, evidence_id) 定位
（一个条目对一个成分至多一条断言），seed 文本/措辞规则修订后重跑会把陈旧行的
efficacy/note/evidence_level/evidence_strength/efficacy_canonical 同步为现值
（计 assertions_updated），不产生新旧并存；legal_cap 已有值不覆盖。重复执行不增生。

运行：PYTHONPATH="backend:." .venv/bin/python data/loaders/regulation_loader.py [--dry-run]
"""

import argparse
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.services.efficacy_canon import OTHER as CANON_OTHER
from app.services.evidence_level import classify_evidence_level, default_strength
from data.loaders.inci_cn_loader import InciResolver
from data.loaders.inci_cn_loader import load_seed as load_inci_seed

EFFICACY_SEED = Path(__file__).resolve().parents[1] / "seed" / "efficacy_definitions.json"
RESTRICTED_SEED = Path(__file__).resolve().parents[1] / "seed" / "restricted_ingredients.json"

EVIDENCE_SOURCE_DEF = ("NMPA《化妆品分类规则和分类目录》（2021年第49号）"
                       "/《化妆品功效宣称评价规范》（2021年第50号）")
EVIDENCE_SOURCE_SPEC = "国家食品药品监督管理总局《化妆品安全技术规范》（2015年版）"
SPEC_YEAR = 2015
DEF_YEAR = 2021


def load_efficacy_definitions(session: Session, seed: dict) -> dict:
    """26 个功效宣称法定类别 → 每类 1 条 regulation 证据（不建断言，决策见模块 docstring）。"""
    stats = {"evidence_new": 0, "evidence_existing": 0}
    url49 = seed["source"]["official_url_49"]
    for cat in seed["categories"]:
        title = f"化妆品功效宣称法定类别「{cat['name']}」：法规定义与评价要求"
        ev = session.query(Evidence).filter_by(title=title).one_or_none()
        if ev is not None:
            stats["evidence_existing"] += 1
            continue
        excerpt = (f"功效定义（2021年第49号公告附表1，序号{cat['code']}）：{cat['definition']}。"
                   f"法定评价要求（2021年第50号公告附1及相关条款）：{cat['eval_note']}。")
        session.add(Evidence(
            type=EvidenceType.REGULATION, title=title, source=EVIDENCE_SOURCE_DEF,
            year=DEF_YEAR, url=url49, excerpt=excerpt[:1900]))
        stats["evidence_new"] += 1
    session.flush()
    return stats


def _spec_evidence_title(entry: dict) -> str:
    short = entry["cn_name"].split("；")[0].split("，")[0][:60]
    return f"化妆品安全技术规范（2015年版）表3 化妆品限用组分 第{entry['no']}项 {short}"


def _spec_excerpt(entry: dict) -> str:
    parts = [f"《化妆品安全技术规范》（2015年版）表3 化妆品限用组分第{entry['no']}项："
             f"{entry['cn_name']}（INCI：{entry['inci_name'] or '族类条目'}）。"]
    if entry["scope"]:
        parts.append(f"适用及(或)使用范围：{entry['scope']}。")
    if entry["max_conc"]:
        parts.append(f"化妆品使用时的最大允许浓度：{entry['max_conc']}。")
    if entry["other_limits"]:
        parts.append(f"其他限制和要求：{entry['other_limits']}。")
    if entry["label_warning"]:
        parts.append(f"标签上必须标印的使用条件和注意事项：{entry['label_warning']}。")
    return "".join(parts)[:1900]


def _find_ingredient(session: Session, resolver: InciResolver, candidate: str,
                     stats: dict) -> Ingredient | None:
    """候选 INCI → IECIC 规范键 → 库内成分行（大小写无关，多行取 id 最小并记日志）。"""
    key = resolver.resolve(candidate) or candidate.strip().upper()
    rows = (session.query(Ingredient)
            .filter(Ingredient.inci_name.ilike(key))
            .order_by(Ingredient.id).all())
    if not rows:
        return None
    if len(rows) > 1:
        stats["log"].append(f"多行命中 {key!r}：取 id={rows[0].id}（其余 {[r.id for r in rows[1:]]}）")
    return rows[0]


def load_restricted(session: Session, seed: dict,
                    resolver: InciResolver | None = None) -> dict:
    """表 3 限用组分 → regulation 证据 + 法定限用断言 + legal_cap 回填。幂等。"""
    if resolver is None:
        resolver = InciResolver(load_inci_seed()["map"])
    stats = {"entries": len(seed["entries"]), "entries_matched": 0,
             "evidence_new": 0, "evidence_existing": 0,
             "assertions_new": 0, "assertions_existing": 0, "assertions_updated": 0,
             "legal_cap_set": 0, "legal_cap_conflict": 0,
             "unmatched_candidates": [], "log": []}
    spec_url = seed["source"]["official_url"]

    for entry in seed["entries"]:
        # —— 成分匹配：match_inci 为空的族类条目不猜；候选去重（同物多名只断一次） ——
        ingredients: list[Ingredient] = []
        for cand in entry["match_inci"]:
            ing = _find_ingredient(session, resolver, cand, stats)
            if ing is None:
                stats["unmatched_candidates"].append(f"第{entry['no']}项 {cand}")
            elif ing.id not in {i.id for i in ingredients}:
                ingredients.append(ing)
        if not ingredients:
            continue
        stats["entries_matched"] += 1

        title = _spec_evidence_title(entry)
        ev = session.query(Evidence).filter_by(title=title).one_or_none()
        if ev is None:
            ev = Evidence(type=EvidenceType.REGULATION, title=title,
                          source=EVIDENCE_SOURCE_SPEC, year=SPEC_YEAR,
                          url=spec_url, excerpt=_spec_excerpt(entry))
            session.add(ev)
            session.flush()
            stats["evidence_new"] += 1
        else:
            stats["evidence_existing"] += 1

        for ing in ingredients:
            # —— legal_cap 回填：已有值不覆盖，记冲突日志 ——
            if entry["legal_cap"] is not None:
                if ing.legal_cap is None:
                    ing.legal_cap = entry["legal_cap"]
                    stats["legal_cap_set"] += 1
                    stats["log"].append(
                        f"legal_cap #{ing.id} {ing.inci_name!r} = {entry['legal_cap']}"
                        f"（表3 第{entry['no']}项）")
                elif ing.legal_cap != entry["legal_cap"]:
                    stats["legal_cap_conflict"] += 1
                    stats["log"].append(
                        f"legal_cap 冲突不覆盖 #{ing.id} {ing.inci_name!r}："
                        f"现有 {ing.legal_cap}，表3 第{entry['no']}项为 {entry['legal_cap']}")
            # —— 法定限用断言：按 (ingredient_id, evidence_id) 定位，陈旧行同步现值 ——
            efficacy = entry["assertion"]
            if not efficacy:
                continue
            note = (f"法规限值，非功效起效浓度（《化妆品安全技术规范》2015年版 "
                    f"表3 化妆品限用组分第{entry['no']}项）")
            level = classify_evidence_level(note, ev)
            strength = default_strength(level)
            existing = (session.query(EfficacyAssertion)
                        .filter_by(ingredient_id=ing.id, evidence_id=ev.id)
                        .one_or_none())
            if existing is not None:
                dirty = False
                for field, value in (("efficacy", efficacy), ("note", note),
                                     ("evidence_level", level), ("evidence_strength", strength),
                                     ("efficacy_canonical", CANON_OTHER)):
                    if getattr(existing, field) != value:
                        stats["log"].append(
                            f"断言同步 #{existing.id} {field}: "
                            f"{str(getattr(existing, field))[:40]!r} -> {str(value)[:40]!r}")
                        setattr(existing, field, value)
                        dirty = True
                if dirty:
                    stats["assertions_updated"] += 1
                else:
                    stats["assertions_existing"] += 1
                continue
            session.add(EfficacyAssertion(
                ingredient_id=ing.id, efficacy=efficacy, evidence_id=ev.id,
                note=note, evidence_level=level, evidence_strength=strength,
                efficacy_canonical=CANON_OTHER))
            stats["assertions_new"] += 1
    session.flush()
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--efficacy-seed", default=str(EFFICACY_SEED))
    ap.add_argument("--restricted-seed", default=str(RESTRICTED_SEED))
    ap.add_argument("--dry-run", action="store_true", help="只统计不落库（事务回滚）")
    args = ap.parse_args()

    init_db()
    eff_seed = json.loads(Path(args.efficacy_seed).read_text(encoding="utf-8"))
    res_seed = json.loads(Path(args.restricted_seed).read_text(encoding="utf-8"))
    with SessionLocal() as s:
        st1 = load_efficacy_definitions(s, eff_seed)
        st2 = load_restricted(s, res_seed)
        if args.dry_run:
            s.rollback()
            print("DRY-RUN：已回滚，未落库")
        else:
            s.commit()
    print(f"功效族定义证据：新增={st1['evidence_new']} 已存在={st1['evidence_existing']}"
          f"（共 {len(eff_seed['categories'])} 类，不建断言）")
    print(f"表3 限用：命中条目={st2['entries_matched']}/{st2['entries']} "
          f"证据新增={st2['evidence_new']} 已存在={st2['evidence_existing']} "
          f"断言新增={st2['assertions_new']} 已存在={st2['assertions_existing']} "
          f"陈旧同步={st2['assertions_updated']} "
          f"legal_cap回填={st2['legal_cap_set']} 冲突不覆盖={st2['legal_cap_conflict']}")
    if st2["unmatched_candidates"]:
        print(f"未命中候选（{len(st2['unmatched_candidates'])}）："
          + "、".join(st2["unmatched_candidates"]))
    for line in st2["log"]:
        print(" ", line)


if __name__ == "__main__":
    main()
