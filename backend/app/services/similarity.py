"""相似检索：BGE-M3 嵌入 + Faiss IndexFlatIP（索引由 data/tools/build_embeddings.py 构建）。

- 索引 + id 映射（同名 .json）懒加载并缓存；测试可改 settings.faiss_index_dir 后调 reset_cache()
- 索引文件缺失（或未装 faiss-cpu）时返回 None 优雅降级，主流程不受影响；
  实体不在索引中返回 []（区分「功能不可用」与「该实体无相似结果」）
- 向量为 L2 归一化的 1024 维，IndexFlatIP 得分即余弦相似度
"""

import json
from pathlib import Path

from ..config import settings

_REPO_ROOT = Path(__file__).resolve().parents[3]

# kind("products"/"ingredients") -> (index, ids) | None（None = 降级）
_cache: dict[str, tuple | None] = {}


def _index_dir() -> Path:
    p = Path(settings.faiss_index_dir)
    return p if p.is_absolute() else _REPO_ROOT / p


def _load(kind: str) -> tuple | None:
    if kind in _cache:
        return _cache[kind]
    entry = None
    try:
        import faiss  # 延迟导入：未装 faiss-cpu 时其余 API 不受影响
    except ImportError:
        _cache[kind] = None
        return None
    index_path = _index_dir() / f"{kind}.faiss"
    meta_path = _index_dir() / f"{kind}.json"
    if index_path.exists() and meta_path.exists():
        index = faiss.read_index(str(index_path))
        ids = json.loads(meta_path.read_text(encoding="utf-8"))["ids"]
        entry = (index, ids)
    _cache[kind] = entry
    return entry


def _search(kind: str, entity_id: int, k: int, id_key: str) -> list[dict] | None:
    loaded = _load(kind)
    if loaded is None:
        return None
    index, ids = loaded
    if entity_id not in ids:
        return []
    row = ids.index(entity_id)
    vec = index.reconstruct(row).reshape(1, -1)  # IndexFlat 支持按行号取向量
    scores, rows = index.search(vec, k + 1)  # +1 为排除自身留位
    hits = []
    for score, r in zip(scores[0], rows[0]):
        if r < 0 or ids[r] == entity_id:  # r<0 = 结果不足 k+1 的填充位
            continue
        hits.append({id_key: ids[r], "score": float(score)})
        if len(hits) >= k:
            break
    return hits


def search_products(product_id: int, k: int = 5) -> list[dict] | None:
    """与 product_id 成分表最相似的产品 Top-k：[{product_id, score}]，索引缺失返回 None。"""
    return _search("products", product_id, k, "product_id")


def search_ingredients(ingredient_id: int, k: int = 5) -> list[dict] | None:
    """与 ingredient_id 证据文本最相似的成分 Top-k：[{ingredient_id, score}]，索引缺失返回 None。"""
    return _search("ingredients", ingredient_id, k, "ingredient_id")


def reset_cache() -> None:
    """清空索引缓存（测试改索引目录后调用）。"""
    _cache.clear()
