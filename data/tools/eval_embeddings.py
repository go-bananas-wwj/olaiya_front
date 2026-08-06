"""嵌入模型域内对比评测器：同一批查询在多个 FAISS 索引产物上的相似检索质量对比。

回答的问题：在化妆品成分域，哪个嵌入模型的相似检索更好（BGE-M3 vs
Qwen3-Embedding-0.6B vs 后续 8B）。评测**不加载模型**，只读已有索引产物
（products.faiss + products.json，IndexFlatIP + L2 归一化，得分即余弦）。

代理标签（确定性相似信号，与 app.services.similar_levels 同口径）：
- L1 成分集合 Jaccard Top-k：shared/union，零交集不入选，(-score, id) 排序；
- L3 功效指纹余弦 Top-k：指纹聚合直接复用 similar_levels._batch_fingerprints
  （剂量因子 × 证据强度，法规/防腐族不计分），此处仅按同口径重实现 Top-k 比对
  （排除「其他」维，排除后为空的产品不参与，无功效信号时指标记 None 而非 0 分）。

指标（产品级；k 默认 5/10 两档）：
- pred Top-k 与 L1/L3 Top-k 的集合重合度（Jaccard of sets）与共有项 Spearman；
- 跨品牌召回率：Top-k 中非同品牌产品占比——真平替必须跨品牌，同品牌屠榜是
  已知名称/系列主导的失败模式（build_embeddings 编码文本不含名称/品牌，该指标
  检验嵌入是否仍被系列配方惯性主导）。品牌比对前做主名归一（normalize_brand：
  取首个连续中文段，无中文取整串），「理肤泉 / 理肤泉 La Roche-Posay」
  「OLAY 玉兰油 / 玉兰油」这类同族双名不互计跨品牌；已知局限：中文名与纯外文名
  分写（如 适乐肤 vs CeraVe）不会归并——库内暂无此形态；
- 模型间 Top-k 集合一致度（参考指标，非质量标准）。

注意：不同时间构建的索引可能对应不同代数据库（id 集合不一致）。公平性口径：
查询、gold 候选池、pred 候选池三者统一限制在**所有索引共有的产品 id** 上
（pred 限池在 search_topk 内完成：全量排序后按池过滤，Top-k 在过滤后按原序
补足，池内不足 k 时如实变短）；报告 coverage 字段记录覆盖情况，若某索引
明显落后（n_ids 远小于库内产品数）会写 note 提示重建。

用法（主 venv 即可，无需 torch；faiss/numpy 为主 venv 已有依赖）：
    PYTHONPATH=backend .venv/bin/python data/tools/eval_embeddings.py \
      --indexes bge-m3=data/models/embedding/faiss \
                qwen3-0.6b=data/models/embedding/faiss/qwen3-0.6b --k 10
输出 data/eval/embedding_compare_report.json（机器可读）+ 终端摘要。
幂等：只读索引与 DB，仅覆盖写报告文件。
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sqlite3
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "cfz.db"
DEFAULT_OUT = REPO_ROOT / "data" / "eval" / "embedding_compare_report.json"
OTHER = "其他"  # 与 app.services.efficacy_canon.OTHER 一致（兜底功效族，无语义区分度）


# ---------------------------------------------------------------- 索引读写


def load_index(index_dir: str | Path, kind: str = "products"):
    """读 products.faiss + products.json → (index, ids)。faiss 惰性导入。"""
    import faiss  # 延迟导入：未装 faiss-cpu 时其余函数仍可单测

    index_dir = Path(index_dir)
    index = faiss.read_index(str(index_dir / f"{kind}.faiss"))
    meta = json.loads((index_dir / f"{kind}.json").read_text(encoding="utf-8"))
    return index, meta["ids"]


def search_topk(index, ids: list[int], entity_id: int, k: int,
                pool: set[int] | None = None) -> list[tuple[int, float]]:
    """与 similarity._search 同口径：reconstruct 查询向量，排除自身，Top-k (id, score)。

    pool：候选池限制（评测时传索引共有 id 集合）——池外 id 不出现；为在过滤后
    仍能补足 Top-k，限池时改为全量排序再按池过滤（IndexFlat 本身是全扫描，
    额外代价仅堆大小）；池内候选不足 k 时如实变短。None = 不限（检索 k+1 即返回）。
    """
    if entity_id not in ids:
        return []
    row = ids.index(entity_id)
    vec = index.reconstruct(row).reshape(1, -1)  # IndexFlat 支持按行号取向量
    n = index.ntotal if pool is not None else k + 1  # +1 为排除自身留位
    scores, rows = index.search(vec, n)
    hits = []
    for score, r in zip(scores[0], rows[0]):
        if r < 0 or ids[r] == entity_id:  # r<0 = 结果不足 n 的填充位
            continue
        if pool is not None and ids[r] not in pool:
            continue
        hits.append((ids[r], float(score)))
        if len(hits) >= k:
            break
    return hits


# ---------------------------------------------------------------- 代理标签（与 similar_levels 同口径）


def jaccard_topk(sets: dict[int, set[int]], product_id: int, k: int,
                 pool: set[int] | None = None) -> list[int]:
    """L1 成分集合 Jaccard Top-k（id 列表）：零交集不入选，(-score, id) 排序。

    pool：候选池限制（评测时传索引共有 id 集合——代理金标准若含索引物理上
    召不回的产品，集合重合度会被不公平压低）；None = 全库。
    """
    target = sets.get(product_id, set())
    if not target:
        return []
    scored = []
    for pid, s in sets.items():
        if pid == product_id or (pool is not None and pid not in pool):
            continue
        shared = len(target & s)
        if shared == 0:
            continue
        scored.append((pid, shared / len(target | s)))
    scored.sort(key=lambda t: (-t[1], t[0]))
    return [pid for pid, _ in scored[:k]]


def fingerprint_topk(fps: dict[int, dict[str, float]], product_id: int, k: int,
                     pool: set[int] | None = None) -> list[int]:
    """L3 功效指纹余弦 Top-k（id 列表）：排除「其他」维，排除后为空的双方不参与。

    pool 语义同 jaccard_topk。
    """
    target = {d: v for d, v in fps.get(product_id, {}).items() if d != OTHER}
    if not target:
        return []
    t_norm = _norm(target)
    scored = []
    for pid, fp in fps.items():
        if pid == product_id or (pool is not None and pid not in pool):
            continue
        cand = {d: v for d, v in fp.items() if d != OTHER}
        shared = [d for d in target if d in cand]
        if not shared:
            continue
        dot = sum(target[d] * cand[d] for d in shared)
        scored.append((pid, dot / (t_norm * _norm(cand))))
    scored.sort(key=lambda t: (-t[1], t[0]))
    return [pid for pid, _ in scored[:k]]


def _norm(vec: dict) -> float:
    return sum(v * v for v in vec.values()) ** 0.5


def _batch_fingerprints(db_path: str | Path) -> dict[int, dict[str, float]]:
    """全库功效指纹：直接复用 similar_levels._batch_fingerprints（口径唯一来源）。

    需要 app 包可导入（CLI 用 PYTHONPATH=backend；pytest.ini 已配 pythonpath）。
    兜底只在 app 包本身找不到时补 sys.path；app 包内部的导入错误照常抛出，
    不被兜底掩盖。
    """
    import importlib.util

    if importlib.util.find_spec("app") is None:  # 直接脚本运行且未设 PYTHONPATH
        sys.path.insert(0, str(REPO_ROOT / "backend"))
    from app.services.similar_levels import _batch_fingerprints as impl
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        return impl(session)


# ---------------------------------------------------------------- 指标


def set_jaccard(a: list[int], b: list[int]) -> float:
    """两个 Top-k 列表的集合 Jaccard（忽略顺序）。"""
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def spearman(a: list[int], b: list[int]) -> float | None:
    """共有项上的 Spearman 排序相关（名次 = 各自列表中的位次）；共有 <2 项返回 None。"""
    shared = set(a) & set(b)
    if len(shared) < 2:
        return None
    ra = [a.index(i) for i in a if i in shared]
    rb = [b.index(i) for i in a if i in shared]
    return _pearson(ra, rb)


def _pearson(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    dx = [v - mx for v in x]
    dy = [v - my for v in y]
    denom = (sum(v * v for v in dx) * sum(v * v for v in dy)) ** 0.5
    if denom == 0:
        return None
    return sum(a * b for a, b in zip(dx, dy)) / denom


_CJK_RUN = re.compile(r"[一-鿿]+")


def normalize_brand(brand: str | None) -> str:
    """品牌主名归一：取首个连续中文段；无中文取整串（去首尾空白）。

    覆盖库内 7 个双名族（理肤泉/理肤泉 La Roche-Posay、修丽可/修丽可 SkinCeuticals
    等「中文 拉丁」形态）与 OLAY 玉兰油、资生堂 Shiseido 等「拉丁 中文」形态；
    SK-II 等纯外文名归一为其自身。已知局限：中文名与纯外文名分写（如
    适乐肤 vs CeraVe）不会归并——当前库内无此形态。
    """
    if not brand:
        return ""
    m = _CJK_RUN.search(brand)
    return m.group(0) if m else brand.strip()


def cross_brand_ratio(hit_ids: list[int], query_brand: str, brands: dict[int, str]) -> float:
    """Top-k 命中中非同品牌占比（品牌经 normalize_brand 主名归一后比对）；空列表计 0。"""
    if not hit_ids:
        return 0.0
    query_main = normalize_brand(query_brand)
    cross = sum(1 for i in hit_ids
                if brands.get(i) is not None and normalize_brand(brands[i]) != query_main)
    return cross / len(hit_ids)


# ---------------------------------------------------------------- 查询集与库数据


def select_queries(db_path: str | Path, id_sets: list[set[int]],
                   min_ingredients: int = 10) -> list[int]:
    """查询集：所有索引共有的产品 id ∩ 不同成分数 ≥ min_ingredients 的产品，按 id 升序。

    成分数口径 COUNT(DISTINCT ingredient_id)——与集合语义一致，重复关联行不凑数。
    """
    common = set.intersection(*id_sets) if id_sets else set()
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT product_id FROM product_ingredients GROUP BY product_id "
            "HAVING COUNT(DISTINCT ingredient_id) >= ? ORDER BY product_id",
            (min_ingredients,)).fetchall()
    finally:
        conn.close()
    eligible = {r[0] for r in rows}
    return sorted(common & eligible)


def _product_info(db_path: str | Path) -> dict[int, dict]:
    """产品 id → {name, brand, n_ingredients}（sqlite3 直读，两条查询）。"""
    conn = sqlite3.connect(str(db_path))
    try:
        products = conn.execute("SELECT id, name, brand FROM products").fetchall()
        counts = dict(conn.execute(
            "SELECT product_id, COUNT(*) FROM product_ingredients GROUP BY product_id"
        ).fetchall())
    finally:
        conn.close()
    return {pid: {"name": name, "brand": brand, "n_ingredients": counts.get(pid, 0)}
            for pid, name, brand in products}


def _ingredient_sets(db_path: str | Path) -> dict[int, set[int]]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT product_id, ingredient_id FROM product_ingredients").fetchall()
    finally:
        conn.close()
    sets: dict[int, set[int]] = {}
    for pid, iid in rows:
        sets.setdefault(pid, set()).add(iid)
    return sets


# ---------------------------------------------------------------- 汇总


def _stats(values: list[float]) -> dict:
    vals = [v for v in values if v is not None]
    if not vals:
        return {"mean": None, "median": None, "n": 0}
    return {"mean": round(statistics.fmean(vals), 4),
            "median": round(statistics.median(vals), 4), "n": len(vals)}


def _cross_brand_stats(values: list[float]) -> dict:
    s = _stats(values)
    vals = [v for v in values if v is not None]
    if vals:
        s["share_ge_0_8"] = round(sum(1 for v in vals if v >= 0.8) / len(vals), 4)
        s["quantiles"] = [round(q, 4) for q in statistics.quantiles(vals, n=4)] if len(vals) >= 2 else None
    else:
        s["share_ge_0_8"] = None
        s["quantiles"] = None
    return s


# ---------------------------------------------------------------- 主评测


def evaluate(db_path: str | Path, indexes: dict[str, str | Path], k: int = 10,
             ks: tuple[int, ...] | None = None,
             min_ingredients: int = 10, n_cases: int = 3) -> dict:
    """全量评测：读索引 + DB 算指标，返回机器可读报告 dict（不写库）。"""
    if not indexes:
        raise ValueError("至少需要一个 名=路径 索引")
    ks = tuple(sorted(set(ks))) if ks else (k,)
    k_eval = max(ks)

    loaded: dict[str, tuple] = {}
    index_meta: dict[str, dict] = {}
    for name, d in indexes.items():
        index, ids = load_index(d)
        loaded[name] = (index, ids)
        meta = json.loads((Path(d) / "products.json").read_text(encoding="utf-8"))
        index_meta[name] = {"dir": str(d), "model": meta.get("model"),
                            "dim": meta.get("dim"), "n_ids": len(ids)}

    products = _product_info(db_path)
    queries = select_queries(db_path, [set(ids) for _, ids in loaded.values()],
                             min_ingredients)
    sets = _ingredient_sets(db_path)
    fps = _batch_fingerprints(db_path)
    brands = {pid: p["brand"] for pid, p in products.items()}

    # 公平性口径：查询 / gold 候选池 / pred 候选池统一限制为索引共有 id。
    # gold 若含索引物理上召不回的产品，集合重合度会被不公平压低；pred 若含池外 id
    # （异代索引 id 更多一侧），同样物理上不可能命中 gold 而被不公平压低。
    pool = set.intersection(*[set(ids) for _, ids in loaded.values()])
    # 代理标签（每查询一次，两档 k 共用 k_eval 截断）
    gold_l1 = {q: jaccard_topk(sets, q, k_eval, pool) for q in queries}
    gold_l3 = {q: fingerprint_topk(fps, q, k_eval, pool) for q in queries}
    # 各模型检索（pred 限池：全量排序后按池过滤，Top-k 过滤后按原序补足）
    preds: dict[str, dict[int, list[tuple[int, float]]]] = {
        name: {q: search_topk(index, ids, q, k_eval, pool) for q in queries}
        for name, (index, ids) in loaded.items()
    }

    per_query = []
    for q in queries:
        entry = {"product_id": q, **products.get(q, {"name": None, "brand": None,
                                                     "n_ingredients": 0}),
                 "models": {}}
        for name in loaded:
            hit_ids = [i for i, _ in preds[name][q]]
            metrics = {}
            for kk in ks:
                pred, g1, g3 = hit_ids[:kk], gold_l1[q][:kk], gold_l3[q][:kk]
                metrics[str(kk)] = {
                    "l1_jaccard": round(set_jaccard(pred, g1), 4) if g1 else None,
                    "l1_spearman": (round(s, 4) if (s := spearman(pred, g1)) is not None else None),
                    "l3_jaccard": round(set_jaccard(pred, g3), 4) if g3 else None,
                    "l3_spearman": (round(s, 4) if (s := spearman(pred, g3)) is not None else None),
                    "cross_brand_ratio": round(
                        cross_brand_ratio(pred, brands.get(q), brands), 4),
                }
            entry["models"][name] = {"topk": hit_ids,
                                     "scores": [round(s, 4) for _, s in preds[name][q]],
                                     "metrics": metrics}
        per_query.append(entry)

    # 汇总：每模型每 k 各指标 mean/median
    models_summary: dict[str, dict] = {}
    for name in loaded:
        per_k = {}
        for kk in ks:
            vals = [q["models"][name]["metrics"][str(kk)] for q in per_query]
            per_k[str(kk)] = {
                "l1_jaccard": _stats([v["l1_jaccard"] for v in vals]),
                "l1_spearman": _stats([v["l1_spearman"] for v in vals]),
                "l3_jaccard": _stats([v["l3_jaccard"] for v in vals]),
                "l3_spearman": _stats([v["l3_spearman"] for v in vals]),
                "cross_brand_ratio": _cross_brand_stats(
                    [v["cross_brand_ratio"] for v in vals]),
            }
        models_summary[name] = {"summary": per_k}

    # 模型间一致度（参考指标）：每对模型每 k 的 Top-k 集合 Jaccard
    agreement: dict[str, dict] = {}
    for kk in ks:
        pair_stats = {}
        for a, b in itertools.combinations(loaded, 2):
            sims = [set_jaccard([i for i, _ in preds[a][q][:kk]],
                                [i for i, _ in preds[b][q][:kk]])
                    for q in queries]
            pair_stats[f"{a}|{b}"] = _stats(sims)
        agreement[str(kk)] = pair_stats

    # 差异案例：模型间 Top-k 平均两两不相似度最大的查询，并列展示各模型 Top-5
    def _divergence(q: int) -> float:
        pairs = list(itertools.combinations(loaded, 2))
        if not pairs:
            return 0.0
        sim = statistics.fmean(
            set_jaccard([i for i, _ in preds[a][q][:k_eval]],
                        [i for i, _ in preds[b][q][:k_eval]])
            for a, b in pairs)
        return 1 - sim

    cases = []
    for q in sorted(queries, key=_divergence, reverse=True)[:n_cases]:
        top5 = {}
        for name in loaded:
            top5[name] = [
                {"id": i, "name": products.get(i, {}).get("name"),
                 "brand": products.get(i, {}).get("brand"), "score": round(s, 4)}
                for i, s in preds[name][q][:5]]
        cases.append({"product_id": q, "name": products.get(q, {}).get("name"),
                      "brand": products.get(q, {}).get("brand"),
                      "divergence": round(_divergence(q), 4), "top5": top5})

    # 覆盖情况：索引 id 与库内产品数差距大时提示（旧索引场景）
    n_db_products = len(products)
    common_n = len(set.intersection(*[set(ids) for _, ids in loaded.values()]))
    lagging = [n for n, m in index_meta.items() if m["n_ids"] < n_db_products * 0.9]
    note = (f"索引 {lagging} 的 id 数明显少于库内产品数（{n_db_products}）：数据库晚于"
            "索引构建（或索引为旧库产物），评测仅在共有 id 子集上进行，建议重建后复评"
            if lagging else None)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db": str(db_path),
        "config": {"k": k, "ks": list(ks), "min_ingredients": min_ingredients,
                   "n_queries": len(queries)},
        "indexes": index_meta,
        "coverage": {"db_products": n_db_products, "common_index_ids": common_n,
                     "note": note},
        "models": models_summary,
        "agreement": agreement,
        "cases": cases,
        "per_query": per_query,
    }


# ---------------------------------------------------------------- CLI


def _parse_indexes(pairs: list[str]) -> dict[str, str]:
    out = {}
    for p in pairs:
        if "=" not in p:
            raise SystemExit(f"--indexes 需要 名=路径 格式，收到：{p!r}")
        name, path = p.split("=", 1)
        out[name] = path
    return out


def _fmt(v) -> str:
    return "-" if v is None else f"{v:.4f}"


def print_summary(report: dict) -> None:
    cfg = report["config"]
    print(f"查询集：{cfg['n_queries']} 个产品（成分数 ≥{cfg['min_ingredients']}，"
          f"共有索引 id {report['coverage']['common_index_ids']}）")
    if report["coverage"]["note"]:
        print(f"⚠ {report['coverage']['note']}")
    names = list(report["models"])
    for kk in cfg["ks"]:
        print(f"\n== k={kk} ==")
        header = f"{'模型':<16}{'L1重合':>8}{'L1秩相关':>9}{'L3重合':>8}{'L3秩相关':>9}{'跨品牌':>8}{'跨品牌≥0.8占比':>14}"
        print(header)
        for n in names:
            s = report["models"][n]["summary"][str(kk)]
            print(f"{n:<16}{_fmt(s['l1_jaccard']['mean']):>8}"
                  f"{_fmt(s['l1_spearman']['mean']):>9}"
                  f"{_fmt(s['l3_jaccard']['mean']):>8}"
                  f"{_fmt(s['l3_spearman']['mean']):>9}"
                  f"{_fmt(s['cross_brand_ratio']['mean']):>8}"
                  f"{_fmt(s['cross_brand_ratio']['share_ge_0_8']):>14}")
        for pair, st in report["agreement"][str(kk)].items():
            print(f"模型间一致度 {pair}: mean={_fmt(st['mean'])} median={_fmt(st['median'])}")
    print("\n== 模型差异最大的案例（各模型 Top-5 并列）==")
    for c in report["cases"]:
        print(f"\n查询 [{c['product_id']}] {c['name']}（{c['brand']}） 差异度 {c['divergence']}")
        for n in names:
            hits = "；".join(f"{h['name']}({h['brand']},{h['score']})" for h in c["top5"][n])
            print(f"  {n}: {hits}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--indexes", nargs="+", required=True, metavar="名=路径",
                    help="一个或多个索引目录，如 bge-m3=data/models/embedding/faiss")
    ap.add_argument("--k", type=int, default=10, help="主评测 k（同时评 5 与 k）")
    ap.add_argument("--min-ingredients", type=int, default=10)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)

    ks = (5, args.k) if args.k > 5 else (args.k,)
    report = evaluate(args.db, _parse_indexes(args.indexes), k=args.k, ks=ks,
                      min_ingredients=args.min_ingredients)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print_summary(report)
    print(f"\n报告已写入 {out}")


if __name__ == "__main__":
    main()
