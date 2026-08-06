"""build_embeddings 脚本逻辑测试：mock 编码器（不真跑 BGE-M3）。"""

import json
import sqlite3

import faiss
import numpy as np
import pytest

from data.tools.build_embeddings import build, ingredient_texts, product_texts


@pytest.fixture()
def db_path(tmp_path):
    """最小 schema 的玩具库：2 产品（其一无成分）、3 成分（其一含断言）。"""
    path = tmp_path / "toy.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, brand TEXT);
        CREATE TABLE ingredients (id INTEGER PRIMARY KEY, inci_name TEXT, cn_name TEXT);
        CREATE TABLE product_ingredients (
            id INTEGER PRIMARY KEY, product_id INT, ingredient_id INT, position INT);
        CREATE TABLE efficacy_assertions (
            id INTEGER PRIMARY KEY, ingredient_id INT, efficacy TEXT, evidence_level TEXT);
        """
    )
    # 故意乱序插入，验证输出按 id 升序
    conn.execute("INSERT INTO products VALUES (2, 'B精华', '品牌B')")
    conn.execute("INSERT INTO products VALUES (1, 'A精华', '品牌A')")
    conn.execute("INSERT INTO ingredients VALUES (1, 'NIACINAMIDE', '烟酰胺')")
    conn.execute("INSERT INTO ingredients VALUES (2, 'WATER', '水')")
    conn.execute("INSERT INTO ingredients VALUES (3, 'ASCORBIC ACID', '抗坏血酸')")
    # 产品 1：位次 1 水、位次 2 烟酰胺、NULL 位次抗坏血酸（排最后）
    conn.execute("INSERT INTO product_ingredients VALUES (1, 1, 3, NULL)")
    conn.execute("INSERT INTO product_ingredients VALUES (2, 1, 2, 1)")
    conn.execute("INSERT INTO product_ingredients VALUES (3, 1, 1, 2)")
    # 烟酰胺：两条断言 + 一条完全重复的（应去重）；evidence_level 为空落 unknown
    conn.execute("INSERT INTO efficacy_assertions VALUES (1, 1, '美白', 'human_rct')")
    conn.execute("INSERT INTO efficacy_assertions VALUES (2, 1, '保湿', NULL)")
    conn.execute("INSERT INTO efficacy_assertions VALUES (3, 1, '美白', 'human_rct')")
    conn.commit()
    conn.close()
    return path


class _FakeEncoder:
    """确定性假编码器：第 i 条文本 → 8 维 one-hot（已归一化）。"""

    def __init__(self):
        self.batches: list[list[str]] = []

    def encode(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        self.batches.append(list(texts))
        return np.stack([np.eye(8, dtype="float32")[i % 8] for i in range(len(texts))])


def test_product_texts(db_path):
    assert product_texts(db_path) == [
        (1, "一款化妆品的成分表：水、烟酰胺、抗坏血酸"),
        (2, "B精华（品牌B）"),  # 无成分表的产品只编码名称+品牌
    ]


def test_ingredient_texts(db_path):
    assert ingredient_texts(db_path) == [
        (1, "烟酰胺（NIACINAMIDE）：美白（human_rct）；保湿（unknown）"),
        (2, "水（WATER）"),
        (3, "抗坏血酸（ASCORBIC ACID）"),
    ]


def test_build_writes_indexes_and_metadata(db_path, tmp_path):
    out_dir = tmp_path / "faiss"
    encoder = _FakeEncoder()
    build(db_path, out_dir, encoder)

    for kind, ids in (("products", [1, 2]), ("ingredients", [1, 2, 3])):
        index = faiss.read_index(str(out_dir / f"{kind}.faiss"))
        assert index.ntotal == len(ids)
        assert index.d == 8
        meta = json.loads((out_dir / f"{kind}.json").read_text(encoding="utf-8"))
        assert meta["ids"] == ids
        assert meta["model"] == "bge-m3"
        assert meta["dim"] == 8

    # 编码器收到的文本与 text 构造函数一致（产品 2 条 + 成分 3 条）
    assert encoder.batches[0] == [t for _, t in product_texts(db_path)]
    assert encoder.batches[1] == [t for _, t in ingredient_texts(db_path)]

    # 向量按 id 序写入：第 0 行即 id=1 的 one-hot
    index = faiss.read_index(str(out_dir / "ingredients.faiss"))
    np.testing.assert_array_equal(index.reconstruct(0), np.eye(8, dtype="float32")[0])


def test_build_is_idempotent(db_path, tmp_path):
    out_dir = tmp_path / "faiss"
    build(db_path, out_dir, _FakeEncoder())
    first = {p.name: p.read_bytes() for p in sorted(out_dir.iterdir())}
    build(db_path, out_dir, _FakeEncoder())
    second = {p.name: p.read_bytes() for p in sorted(out_dir.iterdir())}
    assert first == second, "同库同向量重跑必须得到完全一致的索引产物"


class _NamedFakeEncoder(_FakeEncoder):
    """带 name 的假编码器：meta 的 model 字段应如实写编码器名。"""

    name = "qwen3-embedding-0.6b"


def test_build_writes_actual_model_name(db_path, tmp_path):
    out_dir = tmp_path / "faiss-qwen3"
    build(db_path, out_dir, _NamedFakeEncoder())
    for kind in ("products", "ingredients"):
        meta = json.loads((out_dir / f"{kind}.json").read_text(encoding="utf-8"))
        assert meta["model"] == "qwen3-embedding-0.6b"


def test_resolve_encoder_auto_detects_qwen3():
    from data.tools.build_embeddings import resolve_encoder

    assert resolve_encoder("data/models/embedding/qwen3-embedding-0.6b", None) == "qwen3"
    assert resolve_encoder("data/models/embedding/bge-m3", None) == "bge-m3"
    # 显式指定优先于路径猜测
    assert resolve_encoder("data/models/embedding/bge-m3", "qwen3") == "qwen3"


def test_resolve_encoder_ambiguous_name_raises():
    from data.tools.build_embeddings import resolve_encoder

    with pytest.raises(ValueError, match="--encoder"):
        resolve_encoder("data/models/embedding/qwen3-vs-bge-m3", None)


def test_encoder_max_length_defaults():
    """BGE-M3 保持 512 不变；Qwen3 用 1024（实测产品文本最长 589 token）。"""
    from data.tools.build_embeddings import (
        MAX_LENGTH,
        BGEM3Encoder,
        Qwen3EmbeddingEncoder,
    )

    assert BGEM3Encoder.max_length == MAX_LENGTH == 512
    assert Qwen3EmbeddingEncoder.max_length == 1024


def test_default_out_dir_per_encoder():
    from data.tools.build_embeddings import DEFAULT_OUT_DIR, default_out_dir

    assert default_out_dir("bge-m3") == DEFAULT_OUT_DIR  # BGE-M3 默认路径不变
    assert default_out_dir("qwen3") == DEFAULT_OUT_DIR / "qwen3-0.6b"


def test_last_token_pool_picks_last_non_pad():
    """last_token_pool 双分支：左 pad 取末尾位，右 pad 用 sum-1 定位。

    依赖 torch，主 venv 会 importorskip 跳过；真跑请用：
        .venv-llm/bin/python -m pytest backend/tests/test_build_embeddings.py
    """
    torch = pytest.importorskip("torch")
    from data.tools.build_embeddings import last_token_pool

    hidden = torch.arange(2 * 4 * 3, dtype=torch.float32).reshape(2, 4, 3)
    # 左 pad：mask[:, -1] 全 1 → 取每个样本末尾位（位置 3），与 pad 个数无关
    mask = torch.tensor([[1, 1, 1, 1], [0, 0, 1, 1]])
    pooled = last_token_pool(hidden, mask)
    assert pooled.shape == (2, 3)
    torch.testing.assert_close(pooled[0], hidden[0, 3])
    torch.testing.assert_close(pooled[1], hidden[1, 3])
    # 右 pad：sum-1 定位最后一个 1
    mask2 = torch.tensor([[1, 1, 0, 0], [1, 0, 0, 0]])
    pooled2 = last_token_pool(hidden, mask2)
    torch.testing.assert_close(pooled2[0], hidden[0, 1])
    torch.testing.assert_close(pooled2[1], hidden[1, 0])
