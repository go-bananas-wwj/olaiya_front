"""相似检索 API 测试：索引缺失降级、正常返回结构。"""

import json

import faiss
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app, get_db
from app.models.ingredient import Ingredient
from app.models.product import Product
from app.services import similarity
from data.loaders.seed_loader import load_seed


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
def client(session):
    load_seed(session)
    # 种子 2 个产品，补 3 个凑够 5 个做相似检索
    for i in range(3):
        session.add(Product(name=f"测试产品{i}", brand="测试品牌"))
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def index_dir(tmp_path, monkeypatch):
    d = tmp_path / "faiss"
    monkeypatch.setattr(settings, "faiss_index_dir", str(d))
    similarity.reset_cache()
    yield d
    similarity.reset_cache()


def _product_ids(session) -> list[int]:
    return [p.id for p in session.query(Product).order_by(Product.id).all()]


def _ce_id(client) -> int:
    products = client.get("/api/products").json()
    return [p for p in products if "CE" in p["name"]][0]["id"]


def test_product_similar_missing_index_degrades(client, index_dir):
    r = client.get(f"/api/products/{_ce_id(client)}/similar")
    assert r.status_code == 200
    body = r.json()
    assert body["product_id"] == _ce_id(client)
    assert body["similar"] is None
    assert body["reason"]


def test_product_similar_ok(client, session, index_dir):
    ids = _product_ids(session)
    assert len(ids) == 5
    _write_index(index_dir, "products", ids, _toy_vectors(len(ids)))
    ce_id = _ce_id(client)
    assert ce_id == ids[0], "种子第一个产品即 CE，玩具向量以它为查询点"

    r = client.get(f"/api/products/{ce_id}/similar")
    assert r.status_code == 200
    body = r.json()
    assert body["product_id"] == ce_id
    similar = body["similar"]
    assert isinstance(similar, list)
    # 默认 k=5，但只有 4 个邻居；顺序按玩具向量构造的相似度降序
    assert [s["id"] for s in similar] == ids[1:]
    assert ce_id not in [s["id"] for s in similar]
    for s in similar:
        assert set(s.keys()) == {"id", "name", "brand", "score"}
    assert similar[0]["name"] and similar[0]["brand"]

    # k 参数生效
    r2 = client.get(f"/api/products/{ce_id}/similar", params={"k": 2})
    assert [s["id"] for s in r2.json()["similar"]] == ids[1:3]


def test_product_similar_not_found(client, index_dir):
    r = client.get("/api/products/999999/similar")
    assert r.status_code == 404


def test_ingredient_similar_missing_index_degrades(client, index_dir):
    ing = client.get("/api/ingredients", params={"q": "烟酰胺"}).json()[0]
    r = client.get(f"/api/ingredients/{ing['id']}/similar")
    assert r.status_code == 200
    body = r.json()
    assert body["ingredient_id"] == ing["id"]
    assert body["similar"] is None
    assert body["reason"]


def test_ingredient_similar_ok(client, session, index_dir):
    ids = [i.id for i in session.query(Ingredient).order_by(Ingredient.id).all()]
    assert len(ids) >= 6, "种子成分数量应足够取满默认 k=5"
    _write_index(index_dir, "ingredients", ids, _toy_vectors(len(ids)))
    target = ids[0]

    r = client.get(f"/api/ingredients/{target}/similar")
    assert r.status_code == 200
    body = r.json()
    assert body["ingredient_id"] == target
    similar = body["similar"]
    # 默认 k=5，按玩具向量相似度降序
    assert [s["id"] for s in similar] == ids[1:6]
    for s in similar:
        assert set(s.keys()) == {"id", "inci_name", "cn_name", "score"}
    assert similar[0]["inci_name"]


def test_ingredient_similar_not_found(client, index_dir):
    r = client.get("/api/ingredients/999999/similar")
    assert r.status_code == 404
