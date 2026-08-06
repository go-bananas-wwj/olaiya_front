"""成分/产品文本嵌入 → Faiss 索引构建（向量层第一步，编码器可插拔）。

支持编码器（--encoder 显式指定；缺省时按 --model 目录名自动识别，见 resolve_encoder）：
- bge-m3（默认）：AutoModel + CLS pooling + L2 归一化，1024 维，max_length 512；
  产物写 data/models/embedding/faiss/（运行时 similarity.py 消费的默认目录）
- qwen3：Qwen3-Embedding（因果 LM 基座，AutoModel），last-token pooling
  （官方双分支做法：左 padding 取 [:, -1]，右 padding 用 attention_mask sum-1
  定位最后一个非 pad token，见 last_token_pool）+ L2 归一化，max_length 1024；
  0.6B 输出 1024 维；产物写 data/models/embedding/faiss/qwen3-0.6b/
  物品-物品对称相似，不加 instruction 前缀

编码对象（从 cfz.db 读）：
- 产品成分表文本："一款化妆品的成分表：成分1、成分2、…"（每个产品一条，
  成分按位次升序，NULL 位次排最后；无成分表的产品只编码名称+品牌；
  **不含产品名/品牌**——避免名称 token 主导嵌入导致 Top-K 全是同品牌）
- 成分证据文本："成分中文名（INCI）：功效断言1（证据层级）；功效断言2…"
  （有断言的成分一条，相同 功效+层级 去重，层级为空落 unknown；无断言的只用名称+INCI）

产物（data/models/embedding/faiss/，训练产物不进 git）：
- products.faiss / ingredients.faiss：IndexFlatIP，L2 归一化 1024 维，得分即余弦相似度
- 同名 .json：{"model", "dim", "ids"} —— 行号 → 实体 id 映射

幂等：每次全量重建并覆盖，同一库 + 同一模型 + 同一软硬件环境下产物字节级一致
（文本按 id 升序、IndexFlatIP 无随机性；BGE-M3 走 CPU 推理确定，Qwen3 走 NPU bf16，
同机同卡两次重建实测字节级一致；跨设备/精度不保证逐 bit 相同）。

运行（.venv-llm；BGE-M3 CPU 即可，Qwen3 建议 NPU，见 AGENTS.md 环境变量）：
    cd /root/workspace/olaiya && TORCH_DEVICE_BACKEND_AUTOLOAD=0 \\
      .venv-llm/bin/python data/tools/build_embeddings.py
    # Qwen3-Embedding-0.6B 上 NPU（卡 2）：
    cd /root/workspace/olaiya && ASCEND_RT_VISIBLE_DEVICES=2 \\
      .venv-llm/bin/python data/tools/build_embeddings.py --encoder qwen3 \\
      --model data/models/embedding/qwen3-embedding-0.6b
（torch_npu 自动加载在本机会因 libstdc++ 版本报错，纯 CPU 跑需关掉后端自动加载）
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "cfz.db"
DEFAULT_MODEL = REPO_ROOT / "data" / "models" / "embedding" / "bge-m3"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "models" / "embedding" / "faiss"

MODEL_NAME = "bge-m3"
QWEN3_MODEL_NAME = "qwen3-embedding-0.6b"
BATCH_SIZE = 32
MAX_LENGTH = 512  # BGE-M3 稠密检索标准截断长度（Qwen3 编码器用自身 max_length=1024）


def product_texts(db_path: str | Path) -> list[tuple[int, str]]:
    """(product_id, 成分表文本)，按 product_id 升序 —— 行号即 id 映射，必须确定。"""
    conn = sqlite3.connect(str(db_path))
    try:
        products = conn.execute(
            "SELECT id, name, brand FROM products ORDER BY id"
        ).fetchall()
        links = conn.execute(
            """
            SELECT pi.product_id, i.cn_name
            FROM product_ingredients pi JOIN ingredients i ON i.id = pi.ingredient_id
            ORDER BY pi.product_id, COALESCE(pi.position, 999999), pi.id
            """
        ).fetchall()
    finally:
        conn.close()
    by_product: dict[int, list[str]] = {}
    for pid, cn_name in links:
        by_product.setdefault(pid, []).append(cn_name)
    out = []
    for pid, name, brand in products:
        names = by_product.get(pid)
        if names:
            # 只编码成分表，不含产品名/品牌——否则名称 token 主导嵌入，
            # Top-K 必为同品牌（成分重叠为 0 也相似），真平替需要跨品牌信号
            out.append((pid, f"一款化妆品的成分表：{'、'.join(names)}"))
        else:
            out.append((pid, f"{name}（{brand}）"))
    return out


def ingredient_texts(db_path: str | Path) -> list[tuple[int, str]]:
    """(ingredient_id, 证据文本)，按 ingredient_id 升序。"""
    conn = sqlite3.connect(str(db_path))
    try:
        ingredients = conn.execute(
            "SELECT id, cn_name, inci_name FROM ingredients ORDER BY id"
        ).fetchall()
        assertions = conn.execute(
            """
            SELECT ingredient_id, efficacy, evidence_level
            FROM efficacy_assertions ORDER BY ingredient_id, id
            """
        ).fetchall()
    finally:
        conn.close()
    by_ingredient: dict[int, list[tuple[str, str]]] = {}
    for iid, efficacy, level in assertions:
        pair = (efficacy, level or "unknown")
        seen = by_ingredient.setdefault(iid, [])
        if pair not in seen:  # 相同 功效+层级 的重复断言不产生重复文本
            seen.append(pair)
    out = []
    for iid, cn_name, inci_name in ingredients:
        head = f"{cn_name}（{inci_name}）"
        claims = by_ingredient.get(iid)
        if claims:
            body = "；".join(f"{eff}（{lvl}）" for eff, lvl in claims)
            out.append((iid, f"{head}：{body}"))
        else:
            out.append((iid, head))
    return out


class BGEM3Encoder:
    """BGE-M3 稠密编码器：CLS pooling + L2 归一化（1024 维）。

    torch/transformers 在 __init__ 内惰性导入 —— 模块本身可被无 GPU 环境
    （如主 venv 的 pytest）导入以测试纯逻辑。
    """

    name = MODEL_NAME
    max_length = MAX_LENGTH

    def __init__(self, model_path: str | Path = DEFAULT_MODEL, device: str | None = None):
        import torch
        from transformers import AutoModel, AutoTokenizer

        if device is None:
            # ASCEND_RT_VISIBLE_DEVICES 已设置且 torch_npu 可用时上 NPU，否则 CPU
            npu_ok = os.environ.get("ASCEND_RT_VISIBLE_DEVICES") and hasattr(torch, "npu")
            device = "npu:0" if npu_ok else "cpu"
        self._torch = torch
        self.device = device
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_path))
        self.model = AutoModel.from_pretrained(str(model_path)).to(device).eval()

    def encode(self, texts: list[str], batch_size: int = BATCH_SIZE):
        """归一化稠密向量，shape (len(texts), 1024)，float32。"""
        import numpy as np

        torch = self._torch
        chunks = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            encoded = self.tokenizer(
                batch, padding=True, truncation=True,
                max_length=self.max_length, return_tensors="pt",
            ).to(self.device)
            with torch.no_grad():
                hidden = self.model(**encoded).last_hidden_state
            emb = torch.nn.functional.normalize(hidden[:, 0], p=2, dim=1)  # CLS
            chunks.append(emb.cpu().numpy())
        return np.vstack(chunks).astype("float32")


class Qwen3EmbeddingEncoder:
    """Qwen3-Embedding 编码器：因果 LM，last-token pooling + L2 归一化。

    与 BGE-M3 的关键差异：不能用 CLS；pooling 走 last_token_pool 双分支
    （左 padding 取末尾位，右 padding 用 attention_mask sum-1 定位）。
    NPU 上 bf16，CPU 上 fp32。物品-物品对称相似，不加 instruction 前缀。
    torch/transformers 同样惰性导入，纯逻辑测试可在主 venv 跑。
    """

    # 类级缺省名（0.6B）；__init__ 按实际模型目录名覆盖，8B 等变体如实进 meta
    name = QWEN3_MODEL_NAME
    # 原生 32k 上下文；实测产品文本最长 589 token，1024 留足余量且不影响短文本 batch 效率
    max_length = 1024

    def __init__(self, model_path: str | Path, device: str | None = None):
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.name = Path(model_path).name.lower()

        if device is None:
            npu_ok = os.environ.get("ASCEND_RT_VISIBLE_DEVICES") and hasattr(torch, "npu")
            device = "npu:0" if npu_ok else "cpu"
        self._torch = torch
        self.device = device
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_path))
        dtype = torch.bfloat16 if device.startswith("npu") else torch.float32
        # AutoModel 加载基座（无 LM head），输出 last_hidden_state
        self.model = (
            AutoModel.from_pretrained(str(model_path), dtype=dtype)
            .to(device)
            .eval()
        )

    def encode(self, texts: list[str], batch_size: int = BATCH_SIZE):
        """归一化稠密向量，shape (len(texts), hidden_size)，float32。"""
        import numpy as np

        torch = self._torch
        chunks = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            encoded = self.tokenizer(
                batch, padding=True, truncation=True,
                max_length=self.max_length, return_tensors="pt",
            ).to(self.device)
            with torch.no_grad():
                hidden = self.model(**encoded).last_hidden_state
            emb = last_token_pool(hidden, encoded["attention_mask"])
            emb = torch.nn.functional.normalize(emb.float(), p=2, dim=1)
            chunks.append(emb.cpu().numpy())
        return np.vstack(chunks).astype("float32")


def last_token_pool(hidden, attention_mask):
    """last-token pooling（官方 Qwen3-Embedding 做法）：hidden (B,T,H)，mask (B,T) → (B,H)。

    左 padding（batch 内每条末尾都是有效 token，mask[:, -1] 全 1）→ 直接取 [:, -1]；
    右 padding → 用 sum-1 定位最后一个非 pad token。sum-1 单独用只对右 padding
    正确（左 pad 时会数到 pad 位上），所以必须分两支。
    """
    import torch

    if bool((attention_mask[:, -1].sum() == attention_mask.shape[0])):
        return hidden[:, -1]  # 左 padding
    last_idx = attention_mask.sum(dim=1) - 1  # 右 padding
    return hidden[torch.arange(hidden.shape[0]), last_idx]


ENCODERS = {"bge-m3": BGEM3Encoder, "qwen3": Qwen3EmbeddingEncoder}


def resolve_encoder(model_path: str, encoder: str | None) -> str:
    """--encoder 未显式给出时按模型目录 basename 猜测（含 "qwen3" → qwen3，否则 bge-m3）。

    basename 同时含 "qwen3" 和 "bge" 无法判断，显式报错要求用 --encoder 指定。
    """
    if encoder:
        return encoder
    name = Path(model_path).name.lower()
    if "qwen3" in name and "bge" in name:
        raise ValueError(
            f"无法从模型目录名 {name!r} 判断编码器类型（同时含 qwen3 和 bge），"
            "请用 --encoder 显式指定"
        )
    return "qwen3" if "qwen3" in name else "bge-m3"


def default_out_dir(encoder_name: str) -> Path:
    """各编码器默认索引目录：BGE-M3 保持原位（运行时在消费），Qwen3 分目录。"""
    if encoder_name == "qwen3":
        return DEFAULT_OUT_DIR / "qwen3-0.6b"
    return DEFAULT_OUT_DIR


def _write_index(ids: list[int], vectors, out_dir: Path, kind: str,
                 model_name: str = MODEL_NAME) -> None:
    import faiss

    out_dir.mkdir(parents=True, exist_ok=True)
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    faiss.write_index(index, str(out_dir / f"{kind}.faiss"))
    meta = {"model": model_name, "dim": vectors.shape[1], "ids": ids}
    (out_dir / f"{kind}.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )


def build(db_path: str | Path, out_dir: str | Path, encoder,
          batch_size: int = BATCH_SIZE) -> None:
    """全量重建两类索引（覆盖写，幂等）。encoder 需有 encode(texts, batch_size)。"""
    out_dir = Path(out_dir)
    model_name = getattr(encoder, "name", MODEL_NAME)
    for kind, texts_fn in (("products", product_texts), ("ingredients", ingredient_texts)):
        pairs = texts_fn(db_path)
        ids = [pid for pid, _ in pairs]
        vectors = encoder.encode([text for _, text in pairs], batch_size=batch_size)
        _write_index(ids, vectors, out_dir, kind, model_name)
        print(f"[build_embeddings] {kind}: {len(ids)} 条, dim={vectors.shape[1]} -> {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 库路径")
    parser.add_argument("--out-dir", default=None,
                        help="索引输出目录（默认按编码器：bge-m3 → faiss/，qwen3 → faiss/qwen3-0.6b/）")
    parser.add_argument("--model", default=str(DEFAULT_MODEL), help="模型权重目录")
    parser.add_argument("--encoder", choices=sorted(ENCODERS), default=None,
                        help="编码器类型（默认按 --model 路径名自动识别）")
    parser.add_argument("--device", default=None, help="cpu / npu:0（默认按环境自动选）")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = parser.parse_args()
    encoder_name = resolve_encoder(args.model, args.encoder)
    out_dir = args.out_dir or str(default_out_dir(encoder_name))
    encoder = ENCODERS[encoder_name](args.model, device=args.device)
    build(args.db, out_dir, encoder, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
