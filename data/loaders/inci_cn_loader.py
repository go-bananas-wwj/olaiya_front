"""INCI 成分名中文化 + 噪声清洗 loader。

数据源：data/seed/inci_cn_map.json（IECIC 2021 官方目录提取，含 source 与抽查核对说明；
由 data/tools/extract_iecic_pdf.py + data/tools/build_inci_cn_map.py 产出，禁止 LLM 机翻）。

清洗规则（normalize_inci）：
- 去空括号 `[]` 后缀、去 `<N%` 浓度尾巴、去 `->` 尾巴、去尾部 `*`/`^` 标记；
- 反斜杠多语名（英\\拉丁\\法，如 `WATER\\AQUA\\EAU`）与含 EXTRAIT 的斜杠/无分隔双语名
  取英文 INCI 段；弯引号归直引号；首尾空白与内部多余空格归一；
- `[NANO]` 是有效纳米标识，保留不动；普通斜杠共聚物名（CAPRYLIC/CAPRIC ...）不动。

合并规则：清洗后与库内其他成分行撞名（大小写无关）时合并——product_ingredients 与
efficacy_assertions 的 ingredient_id 改指保留行（优先保留本名已是规范名的行，否则 id 最小者），
(product_id, ingredient_id) 已存在的链接跳过并删除多余链接，随后删除重复成分行。全部写 merge_log。

回填规则：用规范化 inci_name 查映射表，命中且现 cn_name 不含中文才更新；已有中文名
（手工核实种子）不覆盖；未命中保持原样，绝不猜测翻译。合并时 dup 有中文名而 keeper
没有则转移给 keeper。收尾清理：无中文的占位 cn_name 对齐清洗后的 inci_name；
含中文的 cn_name 只去 */^ 与空 [] 尾巴（保守，干净手工名不动）。

运行：PYTHONPATH="backend:." .venv/bin/python data/loaders/inci_cn_loader.py [--seed 路径] [--dry-run]
"""

import argparse
import json
import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.models.product import ProductIngredient

SEED_PATH = Path(__file__).resolve().parents[1] / "seed" / "inci_cn_map.json"

_WS = re.compile(r"\s+")
_CN = re.compile(r"[一-鿿]")
_EMPTY_BRACKET = re.compile(r"\s*\[\s*\]\s*$")
_CONC_TAIL = re.compile(r"\s*<\s*\d+(?:\.\d+)?\s*%\s*$")
_ARROW_TAIL = re.compile(r"\s*->.*$")
_STAR_TAIL = re.compile(r"[\s*^]*[*^]+$")  # 尾部 */^ 标记（如 NIACINAMIDE*、XXX^**）
_EXTRAIT_TAIL = re.compile(r"\s+EXTRAIT\s+.*$", re.IGNORECASE)


def normalize_inci(name: str) -> str:
    """INCI 名规范化：去噪声尾巴、多语名取英文段、空白归一。规则见模块 docstring。"""
    s = (name or "").replace("’", "'").replace("‘", "'")
    if "\\" in s or ("EXTRAIT" in s.upper() and "/" in s):
        # 英\拉丁\法 多语拼接（或 EXTRAIT 斜杠双语）：取第一个不含 EXTRAIT 的段
        segs = [seg.strip() for seg in re.split(r"[\\/]+", s) if seg.strip()]
        latin = [seg for seg in segs if "EXTRAIT" not in seg.upper()]
        s = latin[0] if latin else (segs[0] if segs else "")
    s = _EXTRAIT_TAIL.sub("", s)  # 无分隔符的法文尾巴（YEAST EXTRACT FAEX EXTRAIT DE LEVURE）
    s = _EMPTY_BRACKET.sub("", s)
    s = _CONC_TAIL.sub("", s)
    s = _ARROW_TAIL.sub("", s)
    s = _STAR_TAIL.sub("", s)
    return _WS.sub(" ", s).strip()


def load_seed(path: Path = SEED_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _merge_into(session: Session, keeper: Ingredient, dup: Ingredient, stats: dict) -> None:
    """把 dup 的全部关联改指 keeper 后删除 dup。冲突的 (product_id, ingredient_id) 链接直接删除。
    守卫：dup 有中文名而 keeper 没有时，先把 dup 的中文名转移给 keeper（不丢手工核实名）。"""
    if not _CN.search(keeper.cn_name or "") and _CN.search(dup.cn_name or ""):
        stats["merge_log"].append(
            f"cn-transfer #{dup.id} {dup.cn_name!r} -> #{keeper.id}（原 {keeper.cn_name!r}）")
        keeper.cn_name = dup.cn_name
    existing = {l.product_id for l in
                session.query(ProductIngredient).filter_by(ingredient_id=keeper.id)}
    for link in session.query(ProductIngredient).filter_by(ingredient_id=dup.id).all():
        if link.product_id in existing:
            session.delete(link)  # 保留行已有同产品链接，删多余链接
        else:
            link.ingredient_id = keeper.id
            existing.add(link.product_id)
    for assertion in session.query(EfficacyAssertion).filter_by(ingredient_id=dup.id).all():
        assertion.ingredient_id = keeper.id
    stats["merge_log"].append(
        f"merge #{dup.id} {dup.inci_name!r} -> #{keeper.id} {keeper.inci_name!r}")
    session.delete(dup)
    session.flush()
    stats["merged"] += 1


def run_cleanup(session: Session, seed: dict | None = None,
                seed_path: Path = SEED_PATH) -> dict:
    """清洗 + 合并 + 回填 cn_name，返回统计。幂等。"""
    if seed is None:
        seed = load_seed(seed_path)
    mapping = seed["map"]  # 键已由 build_inci_cn_map.norm_inci 规范化
    stats: dict = {"renamed": 0, "merged": 0, "backfilled": 0, "already_cn": 0,
                   "cn_synced": 0, "cn_tail_cleaned": 0,
                   "unmapped": 0, "unmapped_names": set(), "merge_log": []}

    # —— 阶段一：规范化 inci_name，撞名合并 ——
    groups: dict[str, list[Ingredient]] = {}
    for row in session.query(Ingredient).order_by(Ingredient.id).all():
        groups.setdefault(normalize_inci(row.inci_name).upper(), []).append(row)
    for key, grp in groups.items():
        cleaned = normalize_inci(grp[0].inci_name)
        keeper = next((r for r in grp if r.inci_name.upper() == key), grp[0])
        for row in grp:
            if row is not keeper:
                _merge_into(session, keeper, row, stats)
        if keeper.inci_name != cleaned:
            stats["merge_log"].append(f"rename #{keeper.id} {keeper.inci_name!r} -> {cleaned!r}")
            keeper.inci_name = cleaned
            stats["renamed"] += 1
    session.flush()

    # —— 阶段二：命中映射才回填 cn_name；已有中文名不覆盖；未命中保持原样 ——
    for row in session.query(Ingredient).all():
        entry = mapping.get(normalize_inci(row.inci_name).upper())
        has_cn = bool(_CN.search(row.cn_name or ""))
        if entry is None:
            if not has_cn:
                stats["unmapped"] += 1
                stats["unmapped_names"].add(row.inci_name)
            continue
        if has_cn:
            stats["already_cn"] += 1
            continue
        if row.cn_name != entry["cn_name"]:  # 官名与现值相同（如 CI 着色剂官名即编号）不计回填
            row.cn_name = entry["cn_name"]
            stats["backfilled"] += 1
    session.flush()

    # —— 阶段三：cn_name 脏尾巴清理 ——
    # 无中文的 cn_name 是占位值（约定见 incidecoder_loader），一律对齐清洗后的 inci_name，
    # 修掉改名后残留的旧脏名（*/^/[]/EXTRAIT 尾巴）；含中文的 cn 只去 */^ 与空 [] 尾巴
    # （保守，不动主体文字），干净的手工中文名不受影响。
    for row in session.query(Ingredient).all():
        cn = row.cn_name or ""
        if _CN.search(cn):
            cleaned_cn = _STAR_TAIL.sub("", _EMPTY_BRACKET.sub("", cn)).strip()
            if cleaned_cn != cn:
                stats["merge_log"].append(f"cn-tail #{row.id} {cn!r} -> {cleaned_cn!r}")
                row.cn_name = cleaned_cn
                stats["cn_tail_cleaned"] += 1
        elif cn != row.inci_name:
            stats["merge_log"].append(f"cn-sync #{row.id} {cn!r} -> {row.inci_name!r}")
            row.cn_name = row.inci_name
            stats["cn_synced"] += 1
    session.flush()
    return stats


def coverage_report(session: Session, map_keys: set[str] | None = None) -> dict:
    """中文化覆盖率：按成分行数 + 按 product_ingredients 关联加权。
    map_keys 传入时，官名即编号的 CI 着色剂（命中映射但无汉字）也算已覆盖，不进未映射清单。"""
    rows = session.query(Ingredient).all()

    def covered(r: Ingredient) -> bool:
        if _CN.search(r.cn_name or ""):
            return True
        return bool(map_keys) and normalize_inci(r.inci_name).upper() in map_keys

    with_cn = sum(1 for r in rows if covered(r))
    links = session.query(ProductIngredient).all()
    cn_ids = {r.id for r in rows if covered(r)}
    links_cn = sum(1 for l in links if l.ingredient_id in cn_ids)
    # top 未映射（按产品覆盖数）
    counts: dict[int, int] = {}
    for l in links:
        counts[l.ingredient_id] = counts.get(l.ingredient_id, 0) + 1
    unmapped = [(counts.get(r.id, 0), r.inci_name) for r in rows if not covered(r)]
    unmapped.sort(reverse=True)
    return {"ingredients": len(rows), "with_cn": with_cn,
            "links": len(links), "links_cn": links_cn, "top_unmapped": unmapped[:30]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", default=str(SEED_PATH), help="映射 seed 路径")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = parser.parse_args()

    init_db()
    seed = load_seed(Path(args.seed))
    with SessionLocal() as s:
        stats = run_cleanup(s, seed=seed)
        rep = coverage_report(s, map_keys=set(seed["map"]))
        if args.dry_run:
            s.rollback()
        else:
            s.commit()
    print(f"清洗改名={stats['renamed']} 合并删除={stats['merged']} "
          f"回填中文名={stats['backfilled']} 已有中文跳过={stats['already_cn']} "
          f"cn对齐={stats['cn_synced']} cn去尾={stats['cn_tail_cleaned']} "
          f"未映射={stats['unmapped']}{'（dry-run 已回滚）' if args.dry_run else ''}")
    for line in stats["merge_log"]:
        print(" ", line)
    pct = rep["with_cn"] / max(rep["ingredients"], 1) * 100
    wpct = rep["links_cn"] / max(rep["links"], 1) * 100
    print(f"覆盖率：成分 {rep['with_cn']}/{rep['ingredients']}（{pct:.1f}%），"
          f"按关联加权 {rep['links_cn']}/{rep['links']}（{wpct:.1f}%）")
    print("top 30 未映射成分（按产品覆盖数）：")
    for cnt, name in rep["top_unmapped"]:
        print(f"  {cnt:>5}  {name}")


if __name__ == "__main__":
    main()
