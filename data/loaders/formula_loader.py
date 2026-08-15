"""配方实践典型用量加载器：data/research/formula_typical_dose.json → ingredients 典型用量列。

数据性质（铁律口径）：**配方实践典型用量**（19 个剂型的配方实例聚合），
非官方限值、非功效起效浓度 —— 落 ingredients.typical_use_low/high
（配方实例中的最小低值/最大高值），只作展示参考，绝不回填 legal_cap/cir/sccs 等
官方口径列；已有值不覆盖（skip 计数，核订走 allow_correction 另议）。

匹配：复用 supplier_loader.Matcher 的中文通道（cn_name 唯一命中 / IECIC 反查唯一，
折叠形同口径）；配方表 INCI 名多为中文 IECIC 名；未命中如实计 unmatched 报告，不猜。

幂等：值相同原地不动（unchanged 计数），重复执行无变化。
运行：PYTHONPATH="backend:." .venv/bin/python data/loaders/formula_loader.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models.ingredient import Ingredient
from data.loaders.supplier_loader import Matcher

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = REPO_ROOT / "data" / "research" / "formula_typical_dose.json"
DEFAULT_REPORT = REPO_ROOT / "data" / "research" / "formula_match_report.json"


def aggregate_by_ingredient(records: list[dict]) -> dict[str, dict]:
    """按成分名聚合：low=各实例 pct_low 最小值，high=各实例 pct_high 最大值。"""
    agg: dict[str, dict] = {}
    for r in records:
        slot = agg.setdefault(r["inci_name"], {"low": r["pct_low"],
                                               "high": r["pct_high"],
                                               "formulations": set()})
        slot["low"] = min(slot["low"], r["pct_low"])
        slot["high"] = max(slot["high"], r["pct_high"])
        slot["formulations"].add(r["formulation"])
    return agg


def load_formula_dose(session: Session, data: dict,
                      stats: dict | None = None) -> dict:
    """聚合典型用量并回填 typical_use_low/high。幂等，返回统计。"""
    if stats is None:
        stats = {}
    for k in ("ingredients_matched", "ingredients_unmatched",
              "updated", "unchanged", "skipped_existing"):
        stats.setdefault(k, 0)
    unmatched: list[str] = []
    matcher = Matcher(session)

    for name, agg in aggregate_by_ingredient(data["records"]).items():
        iid = matcher.match_cn(name)
        if iid is None:
            stats["ingredients_unmatched"] += 1
            unmatched.append(name)
            continue
        stats["ingredients_matched"] += 1
        ing = session.get(Ingredient, iid)
        if ing.typical_use_low is not None or ing.typical_use_high is not None:
            if (ing.typical_use_low == agg["low"]
                    and ing.typical_use_high == agg["high"]):
                stats["unchanged"] += 1
            else:
                stats["skipped_existing"] += 1  # 已有值不覆盖（铁律口径）
            continue
        ing.typical_use_low = agg["low"]
        ing.typical_use_high = agg["high"]
        stats["updated"] += 1
    session.flush()
    stats["unmatched"] = sorted(unmatched)
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
        stats = load_formula_dose(session, data)
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
