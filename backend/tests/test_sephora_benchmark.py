"""Sephora 基准工具测试：tokenize/矩阵构建/Top-K/代理指标/平替分析/端到端（skip-embed）。

用小合成数据集手算期望值；BGE-M3 编码不在测试中跑（主 venv 无 torch，skip-embed 路径）。
"""

import json
import math

import numpy as np
import pytest

from data.tools.sephora_benchmark import (
    build_vocab, dupe_analysis, evaluate, load_products, onehot_matrix,
    rank_decay_matrix, run, tfidf_matrix, tokenize, topk_cosine,
)

CSV_CONTENT = """Label,Brand,Name,Price,Rank,Ingredients,Combination,Dry,Normal,Oily,Sensitive
Moisturizer,A,Expensive Cream,100,4.5,"Water, Glycerin, Niacinamide",1,1,1,0,0
Moisturizer,B,Cheap Cream,20,4.0,"Water, Glycerin, Niacinamide, Fragrance",1,1,1,0,0
Cleanser,C,Some Cleanser,15,3.5,"Water, Sodium Laureth Sulfate",0,0,1,1,0
Moisturizer,D,Mid Cream,50,4.2,"Water, Glycerin, Fragrance",1,1,0,0,0
Serum,E,Fancy Serum,200,4.8,"Niacinamide, Water, Panthenol",1,0,1,0,1
"""


@pytest.fixture()
def products(tmp_path):
    csv_path = tmp_path / "cosmetics.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")
    return load_products(csv_path)


def test_tokenize():
    assert tokenize("Water, Glycerin ,Niacinamide,") == ["water", "glycerin", "niacinamide"]
    assert tokenize("") == []


def test_load_products(products):
    assert len(products) == 5
    p0 = products[0]
    assert p0["price"] == 100.0 and p0["label"] == "Moisturizer"
    assert p0["tokens"] == ["water", "glycerin", "niacinamide"]  # 位次保持
    assert p0["skin"] == (1, 1, 1, 0, 0)


def test_onehot_matrix(products):
    tokens_list = [p["tokens"] for p in products]
    vocab = build_vocab(tokens_list)
    mat = onehot_matrix(tokens_list, vocab)
    assert mat.shape == (5, len(vocab))
    # 产品 A 三个成分，归一化后各 1/sqrt(3)
    assert mat[0, vocab["water"]] == pytest.approx(1 / math.sqrt(3))
    # A vs B 余弦 = 3 共享 / (sqrt3 * sqrt4) ≈ 0.866
    assert float(mat[0] @ mat[1]) == pytest.approx(0.8660, abs=1e-3)


def test_tfidf_matrix(products):
    tokens_list = [p["tokens"] for p in products]
    vocab = build_vocab(tokens_list)
    mat = tfidf_matrix(tokens_list, vocab)
    # water 出现在全部 5 个产品 → idf = log(5/5) = 0 → 整列为 0
    assert mat[:, vocab["water"]].max() == 0.0
    # niacinamide df=3 → idf = log(5/3) > 0
    assert mat[0, vocab["niacinamide"]] > 0


def test_rank_decay_matrix(products):
    tokens_list = [p["tokens"] for p in products]
    vocab = build_vocab(tokens_list)
    mat = rank_decay_matrix(tokens_list, vocab)
    # 位次 0 权重 1，位次 1 权重 1/log2(3)，位次 2 权重 1/log2(4)=0.5
    w = [1.0, 1 / math.log2(3), 0.5]
    norm = math.sqrt(sum(x * x for x in w))
    assert mat[0, vocab["water"]] == pytest.approx(w[0] / norm)
    assert mat[0, vocab["glycerin"]] == pytest.approx(w[1] / norm)
    assert mat[0, vocab["niacinamide"]] == pytest.approx(w[2] / norm)
    # 位次敏感：E 中 niacinamide 排第 0 位，与 A（排第 2 位）权重不同 → 区分于 one-hot
    assert mat[4, vocab["niacinamide"]] > mat[0, vocab["niacinamide"]]


def test_topk_cosine_excludes_self(products):
    tokens_list = [p["tokens"] for p in products]
    mat = onehot_matrix(tokens_list, build_vocab(tokens_list))
    idx, scores = topk_cosine(mat, k=2)
    assert idx.shape == (5, 2)
    for i in range(5):
        assert i not in idx[i]
    assert idx[0, 0] == 1  # A 的最近邻是 B（余弦 0.866）
    assert scores[0, 0] == pytest.approx(0.8660, abs=1e-3)


def test_evaluate_metrics(products):
    tokens_list = [p["tokens"] for p in products]
    mat = onehot_matrix(tokens_list, build_vocab(tokens_list))
    idx, scores = topk_cosine(mat, k=2)
    m = evaluate(products, idx, scores)
    assert 0 <= m["same_label_rate"] <= 1
    assert 0 <= m["skin_jaccard"] <= 1
    assert m["sim_p10"] <= m["sim_p50"] <= m["sim_p90"]


def test_topk_cosine_rejects_k_ge_n(products):
    tokens_list = [p["tokens"] for p in products]
    mat = onehot_matrix(tokens_list, build_vocab(tokens_list))
    with pytest.raises(ValueError, match="自排除失效"):
        topk_cosine(mat, k=5)  # k ≥ N 时对角 -inf 会被选进邻居，直接报错


def test_dupe_analysis_exclude_same_brand():
    """同品牌容量装（正装→Mini）是平凡平替：跨品牌口径应排除它。"""
    prods = [
        {"label": "S", "brand": "Lux", "name": "正装", "price": 200.0, "rank": 4.0,
         "tokens": ["a", "b"], "skin": (1,)},
        {"label": "S", "brand": "Lux", "name": "Mini 装", "price": 100.0, "rank": 4.0,
         "tokens": ["a", "b"], "skin": (1,)},
        {"label": "S", "brand": "Other", "name": "他牌替代", "price": 80.0, "rank": 4.0,
         "tokens": ["a", "c"], "skin": (1,)},
    ]
    idx = np.array([[1, 2, 0], [0, 2, 1], [0, 1, 2]])
    d_all = dupe_analysis(prods, idx, n_examples=1)
    # 含同品牌口径：正装的最优平替是同配方 Mini 装（Jaccard 1.0）
    assert d_all["examples"][0]["dupes_in_topk"][0]["brand"] == "Lux"
    assert d_all["dupe_found_rate"] == 0.5  # 高价半区 = 正装+Mini（≥中位数100），仅正装找到
    d_x = dupe_analysis(prods, idx, n_examples=1, exclude_same_brand=True)
    # 跨品牌口径：Mini 被排除，他牌 Jaccard 1/3 < 0.5 → 找不到
    assert d_x["dupe_found_rate"] == 0.0
    assert d_x["examples"][0]["dupes_in_topk"] == []


def test_dupe_analysis(products):
    tokens_list = [p["tokens"] for p in products]
    mat = onehot_matrix(tokens_list, build_vocab(tokens_list))
    idx, _ = topk_cosine(mat, k=4)
    d = dupe_analysis(products, idx)
    # 高价半区 = 价格 ≥ 中位数 50 → A(100)/D(50)/E(200)，三者都有更便宜的高重合平替
    assert d["premium_count"] == 3
    assert d["dupe_found_rate"] == 1.0
    # A→B 省 0.8，D→B 省 0.6，E→A 省 0.5 → 均值 0.6333
    assert d["mean_saving_ratio"] == pytest.approx((0.8 + 0.6 + 0.5) / 3, abs=1e-3)
    assert len(d["examples"]) == 5
    richest = d["examples"][0]
    assert richest["target"]["name"] == "Fancy Serum"  # 最贵


def test_run_end_to_end_skip_embed(products, tmp_path):
    csv_path = tmp_path / "cosmetics.csv"
    out_path = tmp_path / "report.json"
    report = run(csv_path, out_path, skip_embed=True, k=2)
    assert set(report["methods"]) == {"onehot", "tfidf", "rank_decay"}
    assert report["dataset"]["products"] == 5
    saved = json.loads(out_path.read_text(encoding="utf-8"))
    assert saved["methods"]["onehot"]["dupe"]["dupe_found_rate"] == 1.0
    assert "dupe_xbrand" in saved["methods"]["onehot"]  # 跨品牌口径并列给出
    assert saved["environment"]["embed_device"] is None  # skip-embed
    assert saved["metrics_note"]  # 代理指标如实注明
