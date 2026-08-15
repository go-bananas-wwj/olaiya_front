"""三级相似检索（总纲 I3「诚实版」相似性报告）——真平替的技术底座。

- L1 成分集合相似（确定性）：Jaccard(成分集合) = |交| / |并|，无估计成分，
  结果可复算可解释；零交集产品不入选（0 分无信号，不刷榜）。
- L2 剂量级相似：仅对「有推断浓度的产品」有意义。向量 = 各成分推断区间中点
  conc_mid = (conc_low + conc_high) / 2；相似度为 min 加权余弦 ——
  分子 = Σ_共享成分 min(a_i, b_i)²，分母 = 双方全向量二范数之积。
  剂量一致时退化为普通余弦；剂量不匹配（min < 双方）与非共享成分都会拉低得分。
  推断浓度本身是模型估计值；无推断浓度的产品不进候选池（任一方无推断即不可比，
  不伪造剂量）；目标产品无推断时整体降级 available=false。
- L3 功效级相似：功效指纹（与 compute_fingerprint 同口径：剂量因子 × 证据强度，
  同成分同功效族取 max，法规/防腐族/原料商宣称断言不计分）的余弦相似度；「其他」维被排除
  （兜底功效族无语义区分度，且常由无关断言堆出高分）。指纹为相对排序信号，
  非功效承诺。

三个级别均为「一次批量查询取全库数据 + 内存计算」（每级 ≤2 条 SQL：数据查询 +
产品信息查询），禁止 N+1 循环单查。得分统一 round(4)，排序 (-score, id) 保证确定性。

全库数据（成分集合 / 剂量向量 / 功效指纹）经模块级快照缓存（_snapshot_section）：
产品/成分数据只在离线 loader 跑批时变化，服务运行期只读，故首次请求惰性构建后
各请求 O(1) 命中（仅剩产品信息查询）；sqlite 库文件 mtime 为失效签名，loader 跑批
改写库文件后下次请求自动重建；非 sqlite URL（如 PostgreSQL）退化为进程级永久缓存，
跑批后需重启进程生效。读写均在锁内，FastAPI 线程池下并发安全。
"""

from __future__ import annotations

import logging
import math
import os
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models.evidence import Evidence, EvidenceType
from ..models.ingredient import EfficacyAssertion
from ..models.product import Product, ProductIngredient
from .efficacy_canon import OTHER, canonicalize
from .evidence_level import REGULATION
from .fingerprint import dose_factor

_snapshot_lock = threading.Lock()
_snapshot_cache: dict | None = None

_logger = logging.getLogger(__name__)


def _db_signature() -> tuple[str, int] | None:
    """缓存失效签名：sqlite 为 (库文件绝对路径, mtime_ns)。

    非 sqlite URL、:memory: 或文件不可 stat 时返回 None —— 无失效信号，
    缓存退化为进程级永久（跑批后需重启进程），docstring 已注明。
    sqlite 相对路径按进程 CWD 解析，stat 失败会记 warning（可能启动目录不对）。
    """
    url = settings.database_url
    if not url.startswith("sqlite:///"):
        return None
    path = url[len("sqlite:///"):]
    if not path or path == ":memory:":
        return None
    try:
        return (os.path.abspath(path), os.stat(path).st_mtime_ns)
    except OSError as exc:
        _logger.warning("similar-levels 缓存失效签名不可用（stat 失败，缓存退化为进程级永久）: %s", exc)
        return None


def _snapshot_section(session: Session, name: str):
    """取全库快照的一个区段（sets 成分集合 / vecs 剂量向量 / fps 功效指纹）。

    按区段惰性构建（每区段一条全库 SQL，保持各级别「数据查询 + 产品信息查询」的
    语句数口径），签名失效后整份快照作废、各区段随用随重建。
    快照内容均为纯 dict/set 基本类型，与 ORM session 无关，可跨请求安全复用；
    构建与读取都在锁内：并发请求每区段最多构建一次，不会读到半成品。
    """
    global _snapshot_cache
    sig = _db_signature()
    with _snapshot_lock:
        if _snapshot_cache is None or _snapshot_cache["sig"] != sig:
            _snapshot_cache = {"sig": sig}
        if name not in _snapshot_cache:
            if name == "sets":
                _snapshot_cache[name] = _ingredient_sets(session)
            elif name == "vecs":
                _snapshot_cache[name] = _dose_vectors(session)
            else:
                _snapshot_cache[name] = _batch_fingerprints(session)
        return _snapshot_cache[name]


def reset_similar_levels_cache() -> None:
    """清空快照缓存（测试与维护用；正常失效由 mtime 签名自动处理）。"""
    global _snapshot_cache
    with _snapshot_lock:
        _snapshot_cache = None


def _products_by_id(session: Session, ids: list[int]) -> dict[int, Product]:
    """批量取产品信息（一条 IN 查询）。"""
    if not ids:
        return {}
    rows = session.execute(select(Product).where(Product.id.in_(ids))).scalars().all()
    return {p.id: p for p in rows}


def _ingredient_sets(session: Session) -> dict[int, set[int]]:
    """全库 产品 → 成分 id 集合（一条查询）。"""
    rows = session.query(ProductIngredient.product_id, ProductIngredient.ingredient_id).all()
    sets: dict[int, set[int]] = {}
    for pid, iid in rows:
        sets.setdefault(pid, set()).add(iid)
    return sets


def level1_jaccard(session: Session, product_id: int, k: int = 5) -> list[dict]:
    """L1 成分集合相似（确定性）：Jaccard(成分集合) Top-k。

    返回 [{id, name, brand, score, shared, union}]，score = shared/union（round 4）。
    零交集产品不入选；目标无成分时返回空列表。
    """
    sets = _snapshot_section(session, "sets")
    target = sets.get(product_id, set())
    if not target:
        return []
    scored = []
    for pid, s in sets.items():
        if pid == product_id:
            continue
        shared = len(target & s)
        if shared == 0:
            continue
        union = len(target | s)
        scored.append((pid, shared / union, shared, union))
    scored.sort(key=lambda t: (-t[1], t[0]))
    top = scored[:k]
    products = _products_by_id(session, [t[0] for t in top])
    return [
        {"id": pid, "name": products[pid].name, "brand": products[pid].brand,
         "score": round(score, 4), "shared": shared, "union": union}
        for pid, score, shared, union in top if pid in products
    ]


def _dose_vectors(session: Session) -> dict[int, dict[int, float]]:
    """全库 产品 → {成分 id: 推断区间中点}，仅含有推断浓度的关联（一条查询）。"""
    rows = (
        session.query(ProductIngredient.product_id, ProductIngredient.ingredient_id,
                      ProductIngredient.conc_low, ProductIngredient.conc_high)
        .filter(ProductIngredient.conc_low.isnot(None),
                ProductIngredient.conc_high.isnot(None))
        .all()
    )
    vecs: dict[int, dict[int, float]] = {}
    for pid, iid, lo, hi in rows:
        vecs.setdefault(pid, {})[iid] = (lo + hi) / 2
    return vecs


def _norm(vec: dict) -> float:
    return math.sqrt(sum(v * v for v in vec.values()))


def level2_dose(session: Session, product_id: int, k: int = 5) -> dict:
    """L2 剂量级相似：推断区间中点向量的 min 加权余弦 Top-k。

    目标无推断浓度 → {"available": False, "reason": ...}（估计语义，不伪造）；
    候选池仅含有推断浓度的产品；零共享成分（score 0）不入选。
    可用时返回 {"available": True, "similar": [{id, name, brand, score}]}。
    """
    vecs = _snapshot_section(session, "vecs")
    target = vecs.get(product_id)
    if not target:
        return {"available": False,
                "reason": "无推断浓度，L2 不可用（估计语义，不伪造）"}
    t_norm = _norm(target)
    scored = []
    for pid, vec in vecs.items():
        if pid == product_id:
            continue
        numerator = sum(min(target[i], v) ** 2 for i, v in vec.items() if i in target)
        if numerator <= 0:
            continue
        scored.append((pid, numerator / (t_norm * _norm(vec))))
    scored.sort(key=lambda t: (-t[1], t[0]))
    top = scored[:k]
    products = _products_by_id(session, [t[0] for t in top])
    similar = [
        {"id": pid, "name": products[pid].name, "brand": products[pid].brand,
         "score": round(score, 4)}
        for pid, score in top if pid in products
    ]
    return {"available": True, "similar": similar}


def _batch_fingerprints(session: Session) -> dict[int, dict[str, float]]:
    """全库产品功效指纹（一条 join 查询 + 内存聚合，与 compute_fingerprint 同口径）。

    逐条断言：剂量因子 × 证据强度，同 (产品, 成分, 规范功效族) 取 max；
    法规类、防腐功效族与原料商宣称（supplier 降级通道）断言不计分；
    强度 NULL 按 0 计（不进维度）。
    """
    rows = (
        session.query(
            ProductIngredient.product_id,
            ProductIngredient.ingredient_id,
            ProductIngredient.conc_low,
            ProductIngredient.conc_high,
            ProductIngredient.is_trace,
            EfficacyAssertion.efficacy,
            EfficacyAssertion.efficacy_canonical,
            EfficacyAssertion.effective_conc_low,
            EfficacyAssertion.evidence_strength,
            EfficacyAssertion.evidence_level,
            Evidence.type.label("ev_type"),
        )
        .join(EfficacyAssertion,
              EfficacyAssertion.ingredient_id == ProductIngredient.ingredient_id)
        .join(Evidence, Evidence.id == EfficacyAssertion.evidence_id)
        .all()
    )
    best: dict[int, dict[tuple[int, str], float]] = {}
    for r in rows:
        canonical = r.efficacy_canonical or canonicalize(r.efficacy)
        if (r.evidence_level == REGULATION or canonical == "防腐"
                or r.ev_type == EvidenceType.SUPPLIER):
            continue  # 法规/防腐不是皮肤功效；原料商宣称（降级通道）不计入功效信号
        factor, _ = dose_factor(conc_low=r.conc_low, conc_high=r.conc_high,
                                eff_low=r.effective_conc_low, is_trace=r.is_trace)
        contribution = round(factor * (r.evidence_strength or 0.0), 4)
        key = (r.ingredient_id, canonical)
        slot = best.setdefault(r.product_id, {})
        if contribution > slot.get(key, 0.0):
            slot[key] = contribution
    fps: dict[int, dict[str, float]] = {}
    for pid, slots in best.items():
        fp: dict[str, float] = {}
        for (_iid, canonical), contrib in slots.items():
            fp[canonical] = fp.get(canonical, 0.0) + contrib
        fps[pid] = {c: round(s, 4) for c, s in fp.items() if s > 0}
    return fps


def level3_fingerprint(session: Session, product_id: int, k: int = 5) -> list[dict]:
    """L3 功效级相似：功效指纹余弦 Top-k（排除「其他」维）。

    返回 [{id, name, brand, score, dimensions, top_shared_dims}]：
    dimensions 为双方共有的非零功效维数；top_shared_dims 为共有维按
    min(双方得分) 降序的前 3 个（相似主要来自哪些功效方向）。
    目标或候选排除「其他」后为空向量的不参与比对（无功效信号可比对）。
    """
    fps = _snapshot_section(session, "fps")
    target = {d: v for d, v in fps.get(product_id, {}).items() if d != OTHER}
    if not target:
        return []
    t_norm = _norm(target)
    scored = []
    for pid, fp in fps.items():
        if pid == product_id:
            continue
        cand = {d: v for d, v in fp.items() if d != OTHER}
        shared = [d for d in target if d in cand]
        if not shared:
            continue
        dot = sum(target[d] * cand[d] for d in shared)
        scored.append((pid, dot / (t_norm * _norm(cand)), shared, cand))
    scored.sort(key=lambda t: (-t[1], t[0]))
    top = scored[:k]
    products = _products_by_id(session, [t[0] for t in top])
    return [
        {"id": pid, "name": products[pid].name, "brand": products[pid].brand,
         "score": round(score, 4),
         "dimensions": len(shared),
         "top_shared_dims": sorted(shared, key=lambda d: -min(target[d], cand[d]))[:3]}
        for pid, score, shared, cand in top if pid in products
    ]
