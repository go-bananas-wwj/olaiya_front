"""Sephora 公开数据集检索表示基准对照（论文实验素材）。

对照问题：「成分相似检索」的表示方法，经典基线 vs 我们的位次加权/语义嵌入，
在公开数据集上代理指标谁更好。数据集：DataCamp 教学族流传的 Sephora 1,472 产品
（Label/Brand/Name/Price/Rank/Ingredients + 5 维肤质适配标记），成分表按含量降序
（美国 FDA 标签法规），位次信息真实可用。

方法（全部余弦相似度 Top-K，自检索排除）：
1. onehot     —— 成分 one-hot（经典基线，DataCamp/t-SNE 族做法）
2. tfidf      —— 成分 TF-IDF 加权（numpy 手写，主 venv 无 sklearn）
3. rank_decay —— 位次衰减加权 w = 1/log2(rank+2)（我们的位次思想：降序位次≈浓度
                 贡献代理，越靠前权重越高；验证「位次携带信息」假设）
4. bge_m3     —— BGE-M3 语义嵌入（我们的 AI 嵌入通道；成分表逗号拼接文本，与
                 build_embeddings.py 同模型同 pooling；--skip-embed 可跳过，
                 主 venv 无 torch 时只跑前三个稀疏方法）
5. hybrid_tfidf_bge —— 混合（我们的混合检索主张）：sqrt(0.5) 加权 TF-IDF ‖ BGE-M3
                 拼接，余弦 = 0.5·cos_tfidf + 0.5·cos_bge；仅在跑 bge_m3 时生成

代理指标（无功效 ground truth，均为代理，report 中如实注明）：
- same_label_rate：Top-K 邻居与目标同品类的平均比例（品类一致性参考）
- skin_jaccard：Top-K 邻居与目标的 5 维肤质适配标记平均 Jaccard
  （相似产品应适合相似人群——最接近「平替」语义的代理）
- dupe / dupe_xbrand：高价半区（价格 ≥ 中位数）产品中，Top-K 内存在更便宜且
  成分 Jaccard ≥ 0.5 的替代品的比例（平替发现率）与平均价格节省比
  （最优平替 = Jaccard 最高者，非最低价者）；dupe 含同品牌候选（正装→Mini 容量装
  是平凡平替，会抬高发现率），dupe_xbrand 排除同品牌，双口径并列给出；
  附价位最高 5 个产品的各方法定性案例
- sim 分布 p10/p50/p90（区分度参考；稠密嵌入常见「相似度饱和」问题在此暴露）

运行：
    # 稀疏三方法（主 venv 即可）：
    .venv/bin/python data/tools/sephora_benchmark.py --skip-embed
    # 全量（BGE-M3 编码需 .venv-llm；CPU 可跑但 1472 条约 40 分钟，建议 NPU）：
    TORCH_DEVICE_BACKEND_AUTOLOAD=0 .venv-llm/bin/python data/tools/sephora_benchmark.py
    # NPU（卡 2，约 1-2 分钟；LD_LIBRARY_PATH 前置 conda lib 修 torch_npu 的 libstdc++ 错）：
    LD_LIBRARY_PATH=/data/wwj_torch21/conda/envs/torch26/lib:$LD_LIBRARY_PATH \\
      ASCEND_RT_VISIBLE_DEVICES=2 .venv-llm/bin/python data/tools/sephora_benchmark.py

产物：data/eval/sephora_benchmark_report.json（进 git；原始 CSV 在 data/raw/sephora/，git 忽略）
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV = REPO_ROOT / "data" / "raw" / "sephora" / "cosmetics.csv"
DEFAULT_MODEL = REPO_ROOT / "data" / "models" / "embedding" / "bge-m3"
DEFAULT_OUT = REPO_ROOT / "data" / "eval" / "sephora_benchmark_report.json"
CSV_SOURCE_URL = ("https://raw.githubusercontent.com/yerramsettysuchita/"
                  "Cosmetics-Ingredient-Analysis-and-Content-Based-Recommendation-System/"
                  "main/cosmetics.csv")

SKIN_FLAGS = ("Combination", "Dry", "Normal", "Oily", "Sensitive")
K = 10  # Top-K 评估窗口
DUPE_JACCARD = 0.5  # 平替判定的成分重合门槛


def load_products(csv_path: str | Path) -> list[dict]:
    """读 CSV（utf-8-sig 去 BOM），成分 split 成 token 列表，价格/肤质标记解析好。"""
    products = []
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            products.append({
                "label": row["Label"], "brand": row["Brand"], "name": row["Name"],
                "price": float(row["Price"]), "rank": float(row["Rank"]),
                "tokens": tokenize(row["Ingredients"]),
                "skin": tuple(1 if row[flag] == "1" else 0 for flag in SKIN_FLAGS),
            })
    return products


def tokenize(ingredients: str) -> list[str]:
    """逗号分隔、去空白、小写归一；保持原始位次（位次是 rank_decay 的输入）。"""
    return [t.strip().lower() for t in ingredients.split(",") if t.strip()]


def build_vocab(tokens_list: list[list[str]]) -> dict[str, int]:
    vocab: dict[str, int] = {}
    for tokens in tokens_list:
        for t in tokens:
            if t not in vocab:
                vocab[t] = len(vocab)
    return vocab


def _l2_normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0  # 空成分表行不除零（得分全 0，不会刷榜）
    return mat / norms


def onehot_matrix(tokens_list: list[list[str]], vocab: dict[str, int]) -> np.ndarray:
    mat = np.zeros((len(tokens_list), len(vocab)), dtype=np.float64)
    for i, tokens in enumerate(tokens_list):
        for t in set(tokens):
            mat[i, vocab[t]] = 1.0
    return _l2_normalize(mat)


def tfidf_matrix(tokens_list: list[list[str]], vocab: dict[str, int]) -> np.ndarray:
    """TF = 文档内频率，IDF = log(N / df)（无平滑；df≥1 恒成立，不除零）。"""
    n = len(tokens_list)
    tf = np.zeros((n, len(vocab)), dtype=np.float64)
    for i, tokens in enumerate(tokens_list):
        for t in tokens:
            tf[i, vocab[t]] += 1.0
    df = (tf > 0).sum(axis=0)
    idf = np.log(n / df)
    return _l2_normalize(tf * idf)


def rank_decay_matrix(tokens_list: list[list[str]], vocab: dict[str, int]) -> np.ndarray:
    """位次衰减加权：w = 1/log2(rank+2)，rank 为成分表中的 0 基位次。

    位次 0 → w=1；位次 6 → w=1/3；位次 30 → w=1/5。同一成分重复出现取最大权重。
    """
    mat = np.zeros((len(tokens_list), len(vocab)), dtype=np.float64)
    for i, tokens in enumerate(tokens_list):
        for rank, t in enumerate(tokens):
            w = 1.0 / math.log2(rank + 2)
            mat[i, vocab[t]] = max(mat[i, vocab[t]], w)
    return _l2_normalize(mat)


def bge_m3_matrix(tokens_list: list[list[str]], model_path: str | Path = DEFAULT_MODEL,
                  batch_size: int = 32, max_length: int = 512) -> np.ndarray:
    """BGE-M3 语义嵌入：AutoModel + CLS pooling + L2 归一化（与 build_embeddings.py 同口径）。

    惰性导入 transformers（主 venv 无 torch，只有 .venv-llm 能走到这里）。
    设备选择同 build_embeddings.py：ASCEND_RT_VISIBLE_DEVICES 已设置且 torch.npu
    可用时上 NPU（npu:0，bf16；本机 torch_npu 需 LD_LIBRARY_PATH 前置 conda lib，
    见 docs/npu-inference-setup.md），否则 CPU fp32。
    """
    import torch  # noqa: PLC0415
    from transformers import AutoModel, AutoTokenizer  # noqa: PLC0415 惰性导入

    npu_ok = os.environ.get("ASCEND_RT_VISIBLE_DEVICES") and hasattr(torch, "npu")
    device = "npu:0" if npu_ok else "cpu"
    dtype = torch.bfloat16 if device.startswith("npu") else torch.float32
    tokenizer = AutoTokenizer.from_pretrained(str(model_path))
    model = AutoModel.from_pretrained(str(model_path), torch_dtype=dtype).to(device)
    model.eval()
    texts = [", ".join(tokens) for tokens in tokens_list]
    vecs = []
    with torch.no_grad():
        for start in range(0, len(texts), batch_size):
            batch = tokenizer(texts[start:start + batch_size], padding=True,
                              truncation=True, max_length=max_length,
                              return_tensors="pt").to(device)
            out = model(**batch).last_hidden_state[:, 0]  # CLS pooling
            vecs.append(out.float().cpu().numpy())
    return _l2_normalize(np.vstack(vecs).astype(np.float64))


def topk_cosine(mat: np.ndarray, k: int = K) -> tuple[np.ndarray, np.ndarray]:
    """归一化矩阵的 Top-K 余弦近邻（自检索排除）。返回 (indices, scores)。

    k 必须小于产品数：k ≥ N 时 argsort 封顶 N 列，对角线 -inf 会被选进邻居
    （自排除静默失效），直接报错比静默更诚实。
    """
    if k >= mat.shape[0]:
        raise ValueError(f"k({k}) 必须小于产品数({mat.shape[0]})，否则自排除失效")
    sims = mat @ mat.T
    np.fill_diagonal(sims, -np.inf)
    idx = np.argsort(-sims, axis=1)[:, :k]
    scores = np.take_along_axis(sims, idx, axis=1)
    return idx, scores


def _jaccard(a: set, b: set) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def evaluate(products: list[dict], idx: np.ndarray, scores: np.ndarray) -> dict:
    """代理指标：品类一致性 / 肤质 Jaccard / 相似度分布。"""
    same_label, skin_jac = [], []
    for i in range(len(products)):
        neighbors = idx[i]
        same_label.append(np.mean([products[j]["label"] == products[i]["label"]
                                   for j in neighbors]))
        skin_jac.append(np.mean([_jaccard(
            {f for f, v in zip(SKIN_FLAGS, products[i]["skin"]) if v},
            {f for f, v in zip(SKIN_FLAGS, products[j]["skin"]) if v})
            for j in neighbors]))
    flat = scores.flatten()
    return {
        "same_label_rate": round(float(np.mean(same_label)), 4),
        "skin_jaccard": round(float(np.mean(skin_jac)), 4),
        "sim_p10": round(float(np.percentile(flat, 10)), 4),
        "sim_p50": round(float(np.percentile(flat, 50)), 4),
        "sim_p90": round(float(np.percentile(flat, 90)), 4),
    }


def dupe_analysis(products: list[dict], idx: np.ndarray,
                  threshold: float = DUPE_JACCARD, n_examples: int = 5,
                  exclude_same_brand: bool = False) -> dict:
    """平替发现：高价半区（价格 ≥ 中位数）产品 Top-K 内更便宜且成分 Jaccard ≥ threshold 的替代品。

    「最优平替」= 成分 Jaccard 最高者（不是最低价者）。返回发现率、平均价格节省比
    （(目标价-平替价)/目标价，取每目标最优平替）、价位最高 n_examples 个产品的定性案例。
    exclude_same_brand=True 时排除同品牌候选——同配方容量装（如正装 vs Mini）是平凡
    「平替」，跨品牌口径才是有意义的发现率（两种口径都在报告中给出，不藏）。
    """
    median_price = float(np.median([p["price"] for p in products]))
    premium = [i for i, p in enumerate(products) if p["price"] >= median_price]
    found, savings = 0, []
    for i in premium:
        target = products[i]
        best = None
        for j in idx[i]:
            cand = products[j]
            if exclude_same_brand and cand["brand"] == target["brand"]:
                continue
            if cand["price"] >= target["price"]:
                continue
            jac = _jaccard(set(target["tokens"]), set(cand["tokens"]))
            if jac >= threshold and (best is None or jac > best[1]):
                best = (j, jac)
        if best is not None:
            found += 1
            savings.append((target["price"] - products[best[0]]["price"]) / target["price"])

    examples = []
    richest = sorted(range(len(products)), key=lambda i: -products[i]["price"])[:n_examples]
    for i in richest:
        target = products[i]
        dupes = []
        for j in idx[i]:
            cand = products[j]
            if exclude_same_brand and cand["brand"] == target["brand"]:
                continue
            jac = _jaccard(set(target["tokens"]), set(cand["tokens"]))
            if cand["price"] < target["price"] and jac >= threshold:
                dupes.append({"name": cand["name"], "brand": cand["brand"],
                              "price": cand["price"], "ingredient_jaccard": round(jac, 4)})
        examples.append({
            "target": {"name": target["name"], "brand": target["brand"],
                       "price": target["price"], "label": target["label"]},
            "dupes_in_topk": dupes[:3]})
    return {
        "premium_count": len(premium),
        "dupe_found_rate": round(found / len(premium), 4) if premium else 0.0,
        "mean_saving_ratio": round(float(np.mean(savings)), 4) if savings else 0.0,
        "threshold_ingredient_jaccard": threshold,
        "examples": examples,
    }


def run(csv_path: str | Path, out_path: str | Path, *, skip_embed: bool = False,
        model_path: str | Path = DEFAULT_MODEL, k: int = K) -> dict:
    products = load_products(csv_path)
    tokens_list = [p["tokens"] for p in products]
    vocab = build_vocab(tokens_list)

    builders = {
        "onehot": onehot_matrix,
        "tfidf": tfidf_matrix,
        "rank_decay": rank_decay_matrix,
    }
    methods: dict[str, np.ndarray] = {}
    for name, builder in builders.items():
        t0 = time.time()
        methods[name] = builder(tokens_list, vocab)
        methods[name + "__build_sec"] = time.time() - t0
    if not skip_embed:
        t0 = time.time()
        methods["bge_m3"] = bge_m3_matrix(tokens_list, model_path)
        methods["bge_m3__build_sec"] = time.time() - t0
        # 混合（我们的混合检索主张）：sqrt(0.5) 加权的 TF-IDF ‖ BGE-M3 拼接，
        # 拼接向量的余弦 = 0.5·cos_tfidf + 0.5·cos_bge（行已各自 L2 归一化；
        # 空成分表行的 tfidf 分量为零向量、行范数 <1，得分系统性偏低——
        # 本数据集无空成分表行，影响为 0，仅作 caveat 记录）
        methods["hybrid_tfidf_bge"] = np.hstack(
            [np.sqrt(0.5) * methods["tfidf"], np.sqrt(0.5) * methods["bge_m3"]])
        methods["hybrid_tfidf_bge__build_sec"] = 0.0

    report = {
        "dataset": {
            "source_url": CSV_SOURCE_URL, "csv": str(csv_path),
            "products": len(products), "vocab_size": len(vocab),
            "labels": sorted({p["label"] for p in products}),
            "note": "Sephora 公开教学数据集；成分表按含量降序（FDA 标签法规）",
        },
        "environment": {
            "skip_embed": skip_embed,
            # bge_m3 数值随硬件/精度不同（NPU bf16 vs CPU fp32），复现时需对齐
            "embed_device": (None if skip_embed else
                             f"npu:0 bf16 (ASCEND_RT_VISIBLE_DEVICES={os.environ['ASCEND_RT_VISIBLE_DEVICES']})"
                             if os.environ.get("ASCEND_RT_VISIBLE_DEVICES") else "cpu fp32"),
        },
        "k": k,
        "metrics_note": ("无功效 ground truth，全部为代理指标：skin_jaccard 最接近平替语义。"
                         "dupe：高价半区 = 价格 ≥ 中位数；判定 = Top-K 内更便宜且成分 Jaccard ≥ 0.5；"
                         "最优平替 = 成分 Jaccard 最高者（非最低价者）。dupe 含同品牌候选"
                         "（正装→Mini 容量装是平凡平替，会抬高发现率），dupe_xbrand 为排除"
                         "同品牌的跨品牌口径，两口径并列给出不藏"),
        "methods": {},
    }
    for name in [n for n in methods if not n.endswith("__build_sec")]:
        idx, scores = topk_cosine(methods[name], k)
        report["methods"][name] = {
            "dim": int(methods[name].shape[1]),
            "build_sec": round(methods[name + "__build_sec"], 3),
            **evaluate(products, idx, scores),
            "dupe": dupe_analysis(products, idx),
            "dupe_xbrand": dupe_analysis(products, idx, exclude_same_brand=True),
        }

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=str(DEFAULT_CSV))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--model", default=str(DEFAULT_MODEL))
    ap.add_argument("--skip-embed", action="store_true",
                    help="跳过 BGE-M3 语义嵌入（主 venv 无 torch 时用）")
    ap.add_argument("--k", type=int, default=K)
    args = ap.parse_args()

    report = run(args.csv, args.out, skip_embed=args.skip_embed,
                 model_path=args.model, k=args.k)
    print(f"数据集 {report['dataset']['products']} 产品 / {report['dataset']['vocab_size']} 成分")
    for name, m in report["methods"].items():
        print(f"{name:12s} dim={m['dim']:6d} 品类一致={m['same_label_rate']:.3f} "
              f"肤质Jaccard={m['skin_jaccard']:.3f} 平替发现率={m['dupe']['dupe_found_rate']:.3f}"
              f"(跨品牌{m['dupe_xbrand']['dupe_found_rate']:.3f}) "
              f"平均节省={m['dupe']['mean_saving_ratio']:.3f} sim_p50={m['sim_p50']:.3f}")
    print(f"报告已写入 {args.out}")


if __name__ == "__main__":
    main()
