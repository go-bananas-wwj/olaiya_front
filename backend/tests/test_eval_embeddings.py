"""eval_embeddings 嵌入模型域内对比评测器测试：玩具索引 + 玩具库，不加载真实模型。

口径与 app.services.similar_levels 一致：
- L1 代理标签 = 成分集合 Jaccard Top-k（零交集不入选，(-score, id) 排序）
- L3 代理标签 = 功效指纹余弦 Top-k（排除「其他」维，排除后为空不参与）
- 指标 = 集合 Jaccard / 共有项 Spearman / Top-k 跨品牌占比 / 模型间 Top-k 一致度
"""

import json
import math
import os

import faiss
import numpy as np
import pytest

from data.tools.eval_embeddings import (
    cross_brand_ratio,
    evaluate,
    fingerprint_topk,
    jaccard_topk,
    load_index,
    normalize_brand,
    search_topk,
    select_queries,
    set_jaccard,
    spearman,
)

# ---------------------------------------------------------------- 纯函数


def test_set_jaccard():
    assert set_jaccard([1, 2, 3], [1, 2, 3]) == 1.0
    assert set_jaccard([1, 2], [2, 3]) == pytest.approx(1 / 3)
    assert set_jaccard([], []) == 0.0


def test_spearman():
    # 完全同序 → 1；完全逆序 → -1；共有项 <2 → None
    assert spearman([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)
    assert spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 2, 3], [1, 3, 2]) == pytest.approx(0.5)
    assert spearman([1, 2], [2, 9]) is None
    assert spearman([1], [1]) is None


def test_cross_brand_ratio():
    brands = {1: "A", 2: "B", 3: "A", 4: "C"}
    assert cross_brand_ratio([2, 3, 4], "A", brands) == pytest.approx(2 / 3)
    assert cross_brand_ratio([], "A", brands) == 0.0


def test_normalize_brand():
    """主名归一：取首个连续中文段；无中文取整串（去空白）。"""
    assert normalize_brand("理肤泉 La Roche-Posay") == "理肤泉"
    assert normalize_brand("理肤泉") == "理肤泉"
    assert normalize_brand("OLAY 玉兰油") == "玉兰油"
    assert normalize_brand("资生堂 Shiseido") == "资生堂"
    assert normalize_brand("SK-II") == "SK-II"          # 无中文取整串
    assert normalize_brand("CeraVe") == "CeraVe"
    assert normalize_brand("  薇诺娜 WINONA ") == "薇诺娜"
    assert normalize_brand("") == ""
    assert normalize_brand(None) == ""


def test_cross_brand_ratio_dual_name_variants_not_cross():
    """同族双名（理肤泉 / 理肤泉 La Roche-Posay）不互计跨品牌。"""
    brands = {1: "理肤泉", 2: "理肤泉 La Roche-Posay", 3: "科颜氏 Kiehl's", 4: "OLAY 玉兰油"}
    # 命中 2 = 同族双名（不计），3 = 真跨品牌（计），4 = 真跨品牌（计）
    assert cross_brand_ratio([2, 3, 4], "理肤泉 La Roche-Posay", brands) == pytest.approx(2 / 3)
    # 反向：查询为简写，命中为全名，同样不跨
    assert cross_brand_ratio([2], "理肤泉", brands) == 0.0
    # OLAY 玉兰油 vs 玉兰油 同族
    assert cross_brand_ratio([4], "玉兰油", brands) == 0.0


def test_jaccard_topk_matches_level1_rules():
    """L1 口径：shared/union，零交集不入选，(-score, id) 排序。"""
    sets = {
        1: {10, 11, 12},
        2: {10, 11, 12, 13},   # 3/4 = 0.75
        3: {10, 11},           # 2/4 = 0.5
        4: {99},               # 零交集，不入选
        5: {10, 11, 14},       # 2/4 = 0.5，与 3 并列按 id 升序
    }
    assert jaccard_topk(sets, 1, 5) == [2, 3, 5]
    assert jaccard_topk(sets, 1, 1) == [2]
    assert jaccard_topk(sets, 4, 5) == []  # 与谁都零交集


def test_fingerprint_topk_matches_level3_rules():
    """L3 口径：排除「其他」维；排除后为空的候选/目标不参与；余弦降序。"""
    fps = {
        1: {"美白": 1.0, "保湿": 0.0},
        2: {"美白": 2.0},                    # 与 1 余弦 = 1.0
        3: {"美白": 1.0, "抗皱": 1.0},       # 与 1 余弦 = 1/√2
        4: {"其他": 5.0},                    # 排除「其他」后为空，不参与
        5: {"抗皱": 1.0},                    # 无共有维，不参与
    }
    assert fingerprint_topk(fps, 1, 5) == [2, 3]
    # 目标排除「其他」后为空 → 整体无信号
    assert fingerprint_topk(fps, 4, 5) == []


# ---------------------------------------------------------------- 索引读写


def _write_index(dir_path, dim, id_vecs, model="toy"):
    """id_vecs: {id: vector}，自动 L2 归一化写入 IndexFlatIP + 同名 .json。"""
    dir_path.mkdir(parents=True, exist_ok=True)
    ids = sorted(id_vecs)
    index = faiss.IndexFlatIP(dim)
    mat = np.array([id_vecs[i] for i in ids], dtype="float32")
    faiss.normalize_L2(mat)
    index.add(mat)
    faiss.write_index(index, str(dir_path / "products.faiss"))
    (dir_path / "products.json").write_text(
        json.dumps({"model": model, "dim": dim, "ids": ids}), encoding="utf-8")
    return dir_path


def test_load_and_search_topk(tmp_path):
    d = _write_index(tmp_path / "idx", 4, {
        1: [1, 0, 0, 0],
        2: [0.9, 0.1, 0, 0],   # 与 1 最像
        3: [0, 1, 0, 0],
    })
    index, ids = load_index(d)
    hits = search_topk(index, ids, 1, k=2)
    assert [h[0] for h in hits] == [2, 3]  # 排除自身；余弦排序
    assert hits[0][1] > hits[1][1]
    assert search_topk(index, ids, 999, k=2) == []  # 不在索引中


def test_search_topk_pool_filters_and_backfills(tmp_path):
    """pool 限定候选池：池外 id 不出现；保持原检索排序；Top-k 在过滤后补足。"""
    d = _write_index(tmp_path / "idx", 4, {
        1: [1, 0, 0, 0],
        2: [0.9, 0.1, 0, 0],   # 排名 1，但在池外
        3: [0.8, 0.2, 0, 0],   # 排名 2，池内
        4: [0.7, 0.3, 0, 0],   # 排名 3，池内——需越过 k 深搜才能补到
    })
    index, ids = load_index(d)
    assert [h[0] for h in search_topk(index, ids, 1, k=2)] == [2, 3]  # 不限池基线
    hits = search_topk(index, ids, 1, k=2, pool={1, 3, 4})
    assert [h[0] for h in hits] == [3, 4]  # 2 被滤掉，4 按原序补足
    # 池内候选不足 k 时如实变短
    assert [h[0] for h in search_topk(index, ids, 1, k=5, pool={1, 3})] == [3]


# ---------------------------------------------------------------- 查询集选择


def _toy_db(path, product_ingredients):
    import sqlite3
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, brand TEXT)")
    conn.execute(
        "CREATE TABLE product_ingredients "
        "(id INTEGER PRIMARY KEY, product_id INT, ingredient_id INT)")
    for pid, n_ing in product_ingredients.items():
        conn.execute("INSERT INTO products VALUES (?, ?, ?)", (pid, f"P{pid}", f"牌{pid}"))
        for j in range(n_ing):
            conn.execute("INSERT INTO product_ingredients VALUES (?, ?, ?)",
                         (pid * 100 + j, pid, j + 1))
    conn.commit()
    conn.close()
    return path


def test_select_queries_intersection_and_min_ingredients(tmp_path):
    db = _toy_db(tmp_path / "t.db", {1: 12, 2: 10, 3: 5, 4: 20})
    # 共有 id（1,2,4 都在两个索引；3 缺一个索引）且成分数 ≥10 → [1, 2]
    qs = select_queries(db, [{1, 2, 3}, {1, 2, 4}], min_ingredients=10)
    assert qs == [1, 2]


# ---------------------------------------------------------------- 端到端


@pytest.fixture()
def e2e_env(tmp_path, session):
    """5 产品玩具库（真 schema）+ 两个手工向量索引，检索结果可预知。

    成分集合：P1={1,2,3}，P2={1,2,3,4}（最像 P1，跨品牌），P3={5,6,7}（不像，同品牌）。
    索引 a 的向量按成分重叠构造（Top-1 应为 P2）；索引 b 故意让 P3/P5 最像 P1
    （名称/系列主导的失败模式玩具版）→ 跨品牌指标应区分两模型。
    """
    from app.models.evidence import Evidence, EvidenceType
    from app.models.ingredient import EfficacyAssertion, Ingredient
    from app.models.product import Product, ProductIngredient

    for i in range(1, 9):
        session.add(Ingredient(id=i, inci_name=f"INCI{i}", cn_name=f"成分{i}"))
    session.add(Evidence(id=1, type=EvidenceType.PAPER, title="t", source="s"))
    # 成分 1/2 有美白断言（指纹信号），成分 3 只有「其他」族
    session.add(EfficacyAssertion(
        id=1, ingredient_id=1, efficacy="美白", evidence_id=1,
        evidence_level="human_rct", evidence_strength=0.9, efficacy_canonical="美白"))
    session.add(EfficacyAssertion(
        id=2, ingredient_id=2, efficacy="美白", evidence_id=1,
        evidence_level="human_rct", evidence_strength=0.5, efficacy_canonical="美白"))
    session.add(EfficacyAssertion(
        id=3, ingredient_id=3, efficacy="其他杂项", evidence_id=1,
        evidence_level="unknown", evidence_strength=0.1, efficacy_canonical="其他"))
    sets = {1: [1, 2, 3], 2: [1, 2, 3, 4], 3: [5, 6, 7], 4: [1, 2, 5], 5: [5, 6, 8]}
    brands = {1: "品牌甲", 2: "品牌乙", 3: "品牌甲", 4: "品牌丙", 5: "品牌丁"}
    for pid, ings in sets.items():
        session.add(Product(id=pid, name=f"产品{pid}", brand=brands[pid]))
        for pos, iid in enumerate(ings, start=1):
            session.add(ProductIngredient(
                product_id=pid, ingredient_id=iid, position=pos))
    session.commit()
    db_path = os.environ["CFZ_DATABASE_URL"].replace("sqlite:///", "")

    # 索引 a：向量 = 成分 one-hot（P1 的 Top-1 = P2，唯一余弦最高）
    dim = 8
    vecs_a = {pid: [1.0 if (i + 1) in ings else 0.0 for i in range(dim)]
              for pid, ings in sets.items()}
    dir_a = _write_index(tmp_path / "a", dim, vecs_a, model="toy-a")
    # 索引 b：P3/P5 与 P1 同向（同品牌/无关产品屠榜），P2/P4 正交
    vecs_b = {1: [1, 0, 0, 0, 0, 0, 0, 0], 2: [0, 1, 0, 0, 0, 0, 0, 0],
              3: [0.99, 0.01, 0, 0, 0, 0, 0, 0], 4: [0, 0, 1, 0, 0, 0, 0, 0],
              5: [0.98, 0.02, 0, 0, 0, 0, 0, 0]}
    dir_b = _write_index(tmp_path / "b", dim, vecs_b, model="toy-b")
    return db_path, {"a": dir_a, "b": dir_b}


def test_evaluate_end_to_end(e2e_env):
    db_path, indexes = e2e_env
    report = evaluate(db_path, indexes, k=2, ks=(2,), min_ingredients=3)

    assert report["config"]["n_queries"] == 5
    assert set(report["models"]) == {"a", "b"}
    per_query = {q["product_id"]: q for q in report["per_query"]}
    # 模型 a：P1 的 Top-1 是 P2（跨品牌）；模型 b：P1 的 Top-2 是 P3/P5（代理标签外）
    assert per_query[1]["models"]["a"]["topk"][0] == 2
    assert per_query[1]["models"]["b"]["topk"] == [3, 5]
    m_a = per_query[1]["models"]["a"]["metrics"]["2"]
    m_b = per_query[1]["models"]["b"]["metrics"]["2"]
    assert m_a["cross_brand_ratio"] == 1.0
    # b 的 Top-2 = P3(同品牌) + P5(跨品牌但成分无关)：跨品牌 0.5 但 L1/L3 全不中——
    # 跨品牌只是必要条件的体检，质量还要结合代理标签重合度看
    assert m_b["cross_brand_ratio"] == 0.5
    # L1 代理：P1 的 Jaccard Top-2 = [P2(3/4), P4(2/4)]；a 全中，b 全不中
    assert m_a["l1_jaccard"] == 1.0
    assert m_b["l1_jaccard"] == 0.0
    # L3 代理：指纹仅 P1/P2/P4 有「美白」维（P3/P5 无）；a 的 Top-2 全有信号
    assert m_a["l3_jaccard"] == 1.0
    # 汇总结构：每模型每 k 各指标 mean/median + 跨品牌分布
    summ_a = report["models"]["a"]["summary"]["2"]
    for key in ("l1_jaccard", "l1_spearman", "l3_jaccard", "l3_spearman"):
        assert set(summ_a[key]) == {"mean", "median", "n"}
    assert set(summ_a["cross_brand_ratio"]) >= {"mean", "median", "n", "share_ge_0_8"}
    # 模型间一致度 + 差异案例
    assert "a|b" in report["agreement"]["2"]
    assert report["cases"], "应自动选出模型差异最大的案例"
    case = next(c for c in report["cases"] if c["product_id"] == 1)
    assert set(case["top5"]) == {"a", "b"}
    assert case["top5"]["a"][0]["id"] == 2
    # 索引覆盖信息（供「旧索引 id 不一致」场景判断）
    assert report["indexes"]["a"]["n_ids"] == 5


def test_evaluate_missing_l3_signal_skips(e2e_env):
    """P3 无任何功效断言（指纹为空）：L3 指标应为 None 而非 0 分。"""
    db_path, indexes = e2e_env
    report = evaluate(db_path, indexes, k=2, ks=(2,), min_ingredients=3)
    per_query = {q["product_id"]: q for q in report["per_query"]}
    assert per_query[3]["models"]["a"]["metrics"]["2"]["l3_jaccard"] is None


def test_evaluate_pred_restricted_to_common_pool(e2e_env, tmp_path):
    """两索引 id 集合不同：id 更多一侧的 Top-k 不得含池外 id（公平性口径）。

    索引 c 比索引 a 多一个池外产品 9（DB 中也不存在），且 9 的向量与 P1 最像；
    不限池时它会霸占 P1 的 Top-1 且物理上不可能命中 gold。
    """
    db_path, indexes = e2e_env
    vecs_c = {1: [1, 0, 0, 0, 0, 0, 0, 0], 9: [0.99, 0.01, 0, 0, 0, 0, 0, 0],
              3: [0.5, 0.5, 0, 0, 0, 0, 0, 0], 2: [0, 1, 0, 0, 0, 0, 0, 0],
              4: [0, 0, 1, 0, 0, 0, 0, 0], 5: [0, 0, 0, 1, 0, 0, 0, 0]}
    dir_c = _write_index(tmp_path / "c", 8, vecs_c, model="toy-c")
    report = evaluate(db_path, {"a": indexes["a"], "c": dir_c},
                      k=2, ks=(2,), min_ingredients=3)
    assert report["coverage"]["common_index_ids"] == 5  # 9 不在共有池
    per_query = {q["product_id"]: q for q in report["per_query"]}
    topk_c = per_query[1]["models"]["c"]["topk"]
    assert 9 not in topk_c          # 池外 id 被过滤
    assert topk_c[0] == 3           # 池内按原检索排序补足
    for q in report["per_query"]:   # 全查询无池外 id 泄漏
        assert 9 not in q["models"]["c"]["topk"]


def test_select_queries_counts_distinct_ingredients(tmp_path):
    """成分数口径为 COUNT(DISTINCT ingredient_id)：重复关联行不凑数。"""
    import sqlite3
    path = tmp_path / "dup.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, brand TEXT)")
    conn.execute(
        "CREATE TABLE product_ingredients "
        "(id INTEGER PRIMARY KEY, product_id INT, ingredient_id INT)")
    conn.execute("INSERT INTO products VALUES (1, 'P1', '牌')")
    conn.execute("INSERT INTO products VALUES (2, 'P2', '牌')")
    # 产品 1：12 行关联但只有 6 个不同成分；产品 2：11 行 11 个不同成分
    for j in range(12):
        conn.execute("INSERT INTO product_ingredients VALUES (?, 1, ?)", (j + 1, j % 6 + 1))
    for j in range(11):
        conn.execute("INSERT INTO product_ingredients VALUES (?, 2, ?)", (100 + j, j + 1))
    conn.commit()
    conn.close()
    assert select_queries(path, [{1, 2}], min_ingredients=10) == [2]
