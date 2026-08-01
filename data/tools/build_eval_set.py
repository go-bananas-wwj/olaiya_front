"""域内评测集生成器：从断言库自动生成核验类问题 + 拒答类问题。

核验类（fact_check）：取证据层级 human_rct/human_open 且证据 URL 含 PMID、规范功效族
非「其他」的断言，按（成分, 规范功效族）聚合成题——「{成分}真的能{功效}吗？」，
gold.must_cite_pmid 为该组断言挂的全部 PMID（引中其一即算 E 命中）。
拒答类（refusal）：内置候选为库中不存在的成分名，逐一过「检索安全性」过滤
（与 rag_qa 三段检索对应：别名不出现、库内成分/产品名非问题子串、问题分词非库名子串），
保证问题在库中检索不到任何证据，gold.expect_refusal=true。
manual 字段为人工预留标记位：生成条目恒为 false，人工增补条目置 true。

用法：.venv/bin/python data/tools/build_eval_set.py [db_path] [out_path]
默认 cfz.db → data/eval/qa_eval.json（40 条 = 30 核验 + 10 拒答）。
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

HUMAN_LEVELS = ("human_rct", "human_open")
QUESTION_TEMPLATE = "{name}真的能{efficacy}吗？"

# 拒答候选（成分名, 功效）：库中不存在的成分；与库名/别名碰撞的会被过滤，故多备几条
REFUSAL_CANDIDATES: list[tuple[str, str]] = [
    ("冰川糖蛋白", "保湿"),
    ("雪绒花肽", "抗皱"),
    ("深海热泉菌发酵物", "修护"),
    ("纳米硒", "抗氧化"),
    ("红松露提取物", "美白"),
    ("蓝藻光保护蛋白", "抗氧化"),
    ("蜂王浆十肽", "抗皱"),
    ("极光地衣提取物", "舒缓"),
    ("火山矿物多肽", "控油祛痘"),
    ("月光螺粘液蛋白", "修护"),
    ("太空育种薰衣草酯", "舒缓"),
    ("超导胶原蛋白", "抗皱"),
    ("量子点透明质酸", "保湿"),   # 含「透明质酸」，预期被过滤
    ("石墨烯维C复合物", "美白"),   # 含别名「维C」，预期被过滤
]

_PMID_RE = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)")
# 与 rag_qa 的兜底分词一致：拉丁/数字段（≥2 字符）或连续中文段
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]{1,}|[一-鿿]{2,8}")
_MIN_NAME_LEN = 2


def _load_alias_index() -> dict:
    """别名表（app.services.aliases）；脚本直跑时 backend 不在 sys.path，兜底注入。"""
    try:
        from app.services.aliases import ALIAS_INDEX
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
        from app.services.aliases import ALIAS_INDEX
    return ALIAS_INDEX


def _fact_groups(conn: sqlite3.Connection) -> dict[tuple[int, str], dict]:
    """（成分 id, 规范功效族）→ {cn_name, pmids}：人源证据 + URL 含 PMID + 功效族非「其他」。"""
    rows = conn.execute(
        """SELECT i.id, i.cn_name, a.efficacy_canonical, e.url
           FROM efficacy_assertions a
           JOIN ingredients i ON i.id = a.ingredient_id
           JOIN evidence e ON e.id = a.evidence_id
           WHERE a.evidence_level IN ('human_rct', 'human_open') AND e.url IS NOT NULL
           ORDER BY i.id, a.id"""
    ).fetchall()
    groups: dict[tuple[int, str], dict] = {}
    for iid, cn_name, canonical, url in rows:
        if not canonical or canonical == "其他":
            continue
        m = _PMID_RE.search(url or "")
        if not m:
            continue
        g = groups.setdefault((iid, canonical), {"cn_name": cn_name, "pmids": []})
        if m.group(1) not in g["pmids"]:
            g["pmids"].append(m.group(1))
    return groups


def _refusal_safe(question: str, names: list[str], aliases: list[str]) -> bool:
    """拒答问题不得被检索命中（与 rag_qa 三段检索一一对应）。

    1) 别名不出现在问题中；2) 库内成分/产品名（≥2 字符）不是问题子串；
    3) 问题分词（rag_qa 兜底段）不是任何库名的子串。
    """
    upper = question.upper()
    for alias in aliases:
        if alias.upper() in upper:
            return False
    for name in names:
        if len(name) >= _MIN_NAME_LEN and name.upper() in upper:
            return False
    for tok in _TOKEN_RE.findall(question):
        if len(tok) < _MIN_NAME_LEN:
            continue
        for name in names:
            if tok.upper() in name.upper():
                return False
    return True


def _db_names(conn: sqlite3.Connection) -> list[str]:
    """库内全部成分名（中文/INCI）与产品名：拒答过滤的对照集。"""
    names = [r[0] for r in conn.execute(
        "SELECT cn_name FROM ingredients WHERE cn_name IS NOT NULL")]
    names += [r[0] for r in conn.execute(
        "SELECT inci_name FROM ingredients WHERE inci_name IS NOT NULL")]
    try:  # 玩具库可能无 products 表
        names += [r[0] for r in conn.execute(
            "SELECT name FROM products WHERE name IS NOT NULL")]
    except sqlite3.OperationalError:
        pass
    return names


def build_items(conn: sqlite3.Connection, n_fact: int = 30, n_refusal: int = 10,
                refusal_candidates: list[tuple[str, str]] | None = None) -> list[dict]:
    """生成评测条目：n_fact 条核验 + n_refusal 条拒答，id 从 1 连续编号。"""
    items: list[dict] = []

    groups = _fact_groups(conn)
    for (iid, canonical), g in sorted(groups.items()):
        if len(items) >= n_fact:
            break
        items.append({
            "id": len(items) + 1,
            "question": QUESTION_TEMPLATE.format(name=g["cn_name"], efficacy=canonical),
            "gold": {
                "must_cite_pmid": g["pmids"],
                "expected_verdict_hint": "effective",
                "type": "fact_check",
            },
            "manual": False,
        })

    candidates = refusal_candidates if refusal_candidates is not None else REFUSAL_CANDIDATES
    names = _db_names(conn)
    aliases = list(_load_alias_index())
    kept = 0
    for name, efficacy in candidates:
        if kept >= n_refusal:
            break
        question = QUESTION_TEMPLATE.format(name=name, efficacy=efficacy)
        if not _refusal_safe(question, names, aliases):
            continue
        items.append({
            "id": len(items) + 1,
            "question": question,
            "gold": {
                "must_cite_pmid": [],
                "expect_refusal": True,
                "expected_verdict_hint": "refusal",
                "type": "refusal",
            },
            "manual": False,
        })
        kept += 1
    return items


def main(argv: list[str]) -> None:
    db_path = argv[1] if len(argv) > 1 else "cfz.db"
    out_path = argv[2] if len(argv) > 2 else "data/eval/qa_eval.json"
    conn = sqlite3.connect(db_path)
    try:
        items = build_items(conn)
    finally:
        conn.close()
    n_fact = sum(1 for it in items if it["gold"]["type"] == "fact_check")
    n_refusal = sum(1 for it in items if it["gold"]["type"] == "refusal")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成 {len(items)} 条（核验 {n_fact} + 拒答 {n_refusal}）→ {out_path}")


if __name__ == "__main__":
    main(sys.argv)
