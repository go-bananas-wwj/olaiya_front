"""build_eval_set 生成器结构测试：玩具 sqlite 库，不依赖开发库 cfz.db。

覆盖：40 条构成（30 核验 + 10 拒答）、gold 结构（must_cite_pmid /
expected_verdict_hint / type / expect_refusal）、manual 标记位、
证据层级与 PMID 过滤、同成分同功效族的 PMID 合并、拒答候选与库名/别名碰撞过滤。
"""

import sqlite3

import pytest

from data.tools.build_eval_set import build_items


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(
        """
        CREATE TABLE ingredients (id INTEGER PRIMARY KEY, inci_name TEXT, cn_name TEXT);
        CREATE TABLE evidence (id INTEGER PRIMARY KEY, type TEXT, title TEXT, url TEXT);
        CREATE TABLE efficacy_assertions (
            id INTEGER PRIMARY KEY, ingredient_id INT, efficacy TEXT, evidence_id INT,
            evidence_level TEXT, efficacy_canonical TEXT);
        """
    )
    yield c
    c.close()


def _add_fact(conn, iid, name, pmid, canonical="美白", level="human_rct", url=None):
    conn.execute("INSERT INTO ingredients VALUES (?, ?, ?)", (iid, f"INCI{iid}", name))
    conn.execute("INSERT INTO evidence VALUES (?, 'paper', 't', ?)",
                 (iid, url or f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"))
    conn.execute(
        "INSERT INTO efficacy_assertions VALUES (?, ?, ?, ?, ?, ?)",
        (iid, iid, f"{canonical}功效", iid, level, canonical))


def _fill_facts(conn, n=35):
    for i in range(1, n + 1):
        _add_fact(conn, i, f"成分{i:02d}", pmid=str(10000000 + i))


def test_build_40_items_with_type_distribution(conn):
    _fill_facts(conn, 35)
    items = build_items(conn, n_fact=30, n_refusal=10)
    assert len(items) == 40
    facts = [it for it in items if it["gold"]["type"] == "fact_check"]
    refusals = [it for it in items if it["gold"]["type"] == "refusal"]
    assert len(facts) == 30
    assert len(refusals) == 10
    assert [it["id"] for it in items] == list(range(1, 41))


def test_fact_item_structure(conn):
    _fill_facts(conn, 3)
    items = build_items(conn, n_fact=2, n_refusal=0)
    it = items[0]
    assert it["question"] == "成分01真的能美白吗？"
    assert it["gold"]["must_cite_pmid"] == ["10000001"]
    assert it["gold"]["expected_verdict_hint"] == "effective"
    assert it["gold"]["type"] == "fact_check"
    assert it["manual"] is False


def test_refusal_items_expect_refusal_and_no_pmid(conn):
    _fill_facts(conn, 3)
    items = build_items(conn, n_fact=1, n_refusal=3)
    refusals = [it for it in items if it["gold"]["type"] == "refusal"]
    assert len(refusals) == 3
    for it in refusals:
        assert it["gold"]["expect_refusal"] is True
        assert it["gold"]["must_cite_pmid"] == []
        assert it["manual"] is False


def test_only_human_evidence_with_pmid_and_canonical_selected(conn):
    _add_fact(conn, 1, "成分A", pmid="11111111")                              # 合格
    _add_fact(conn, 2, "成分B", pmid="22222222", level="in_vitro")            # 层级不符
    _add_fact(conn, 3, "成分C", pmid="33333333",
              url="https://example.com/no-pmid")                              # URL 无 PMID
    _add_fact(conn, 4, "成分D", pmid="44444444", canonical="其他")            # 规范族为其他
    items = build_items(conn, n_fact=10, n_refusal=0)
    assert [it["question"] for it in items] == ["成分A真的能美白吗？"]


def test_same_ingredient_canonical_groups_pmids(conn):
    conn.execute("INSERT INTO ingredients VALUES (1, 'INCI1', '成分甲')")
    for i, pmid in enumerate(["11111111", "22222222"], start=1):
        conn.execute("INSERT INTO evidence VALUES (?, 'paper', 't', ?)",
                     (i, f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"))
        conn.execute(
            "INSERT INTO efficacy_assertions VALUES (?, 1, '美白功效', ?, 'human_open', '美白')",
            (i, i))
    items = build_items(conn, n_fact=5, n_refusal=0)
    assert len(items) == 1
    assert items[0]["gold"]["must_cite_pmid"] == ["11111111", "22222222"]


def test_refusal_candidates_colliding_with_db_or_alias_are_filtered(conn):
    _fill_facts(conn, 3)  # 库内已有 成分01/02/03
    candidates = [
        ("成分01", "美白"),        # 与库内成分名碰撞 → 过滤
        ("超活VC因子", "美白"),     # 含别名 VC → 过滤
        ("冰川糖蛋白", "保湿"),
        ("雪绒花肽", "抗皱"),
    ]
    items = build_items(conn, n_fact=0, n_refusal=5, refusal_candidates=candidates)
    questions = [it["question"] for it in items]
    assert questions == ["冰川糖蛋白真的能保湿吗？", "雪绒花肽真的能抗皱吗？"]
