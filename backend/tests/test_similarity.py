"""相似检索服务测试：玩具索引（5 个假产品向量）验证顺序/结构/降级。"""

import json

import faiss
import numpy as np
import pytest

from app.config import settings
from app.services import similarity


def _toy_vectors(n: int, dim: int = 8) -> np.ndarray:
    """构造 n 个归一化向量：与第 0 个的余弦相似度随下标严格递减。"""
    out = []
    for i in range(n):
        v = np.zeros(dim, dtype="float32")
        v[0] = 1.0 - i * 0.1
        v[1] = i * 0.1
        out.append(v / np.linalg.norm(v))
    return np.stack(out)


def _write_index(dir_path, kind: str, ids: list[int], vectors: np.ndarray) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    faiss.write_index(index, str(dir_path / f"{kind}.faiss"))
    (dir_path / f"{kind}.json").write_text(
        json.dumps({"ids": ids}, ensure_ascii=False), encoding="utf-8"
    )


@pytest.fixture()
def index_dir(tmp_path, monkeypatch):
    """把索引目录指到临时目录，并在用例前后清缓存。"""
    d = tmp_path / "faiss"
    monkeypatch.setattr(settings, "faiss_index_dir", str(d))
    similarity.reset_cache()
    yield d
    similarity.reset_cache()


IDS = [101, 102, 103, 104, 105]


def test_search_products_order_and_structure(index_dir):
    _write_index(index_dir, "products", IDS, _toy_vectors(5))
    hits = similarity.search_products(101, k=3)
    assert hits is not None
    # 排除自身后按相似度降序：102 最近，其后 103、104
    assert [h["product_id"] for h in hits] == [102, 103, 104]
    for h in hits:
        assert set(h.keys()) == {"product_id", "score"}
        assert isinstance(h["score"], float)
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True)
    assert all(0 < s <= 1.0 for s in scores)


def test_search_products_k_exceeds_index_size(index_dir):
    _write_index(index_dir, "products", IDS, _toy_vectors(5))
    hits = similarity.search_products(101, k=10)
    assert len(hits) == 4  # 5 个向量排除自身


def test_search_products_missing_index_returns_none(index_dir):
    # 索引目录不存在 → 优雅降级 None，不抛异常
    assert similarity.search_products(101, k=3) is None


def test_search_products_only_one_kind_present(index_dir):
    # 只建了 ingredients 索引时，products 检索降级为 None
    _write_index(index_dir, "ingredients", IDS, _toy_vectors(5))
    assert similarity.search_products(101, k=3) is None
    assert similarity.search_ingredients(101, k=3) is not None


def test_search_products_id_not_in_index_returns_empty(index_dir):
    _write_index(index_dir, "products", IDS, _toy_vectors(5))
    assert similarity.search_products(999, k=3) == []


def test_search_ingredients_order_and_structure(index_dir):
    _write_index(index_dir, "ingredients", IDS, _toy_vectors(5))
    hits = similarity.search_ingredients(105, k=2)
    assert hits is not None
    # 与 105 最近的是 104，其次 103
    assert [h["ingredient_id"] for h in hits] == [104, 103]
    assert set(hits[0].keys()) == {"ingredient_id", "score"}


def test_search_ingredients_missing_index_returns_none(index_dir):
    assert similarity.search_ingredients(101, k=3) is None
