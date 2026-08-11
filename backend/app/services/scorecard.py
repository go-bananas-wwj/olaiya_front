"""白盒平替得分卡（借鉴「匹配得分」交互并白盒化，总纲 I3 相似性报告的组合视图）。

score = Σ w_d · s_d，默认权重 成分 0.5 / 功效 0.3 / 价格 0.2，三个维度全部可拆解：

- 成分维：Jaccard(成分集合)，附 shared/union 可复算（与 similar-levels L1 同口径）；
- 功效维：功效指纹余弦（排除「其他」维，与 L3 同口径），附共有维数与主要共享方向；
  任一方无功效指纹（排除「其他」后为空）→ 该维 null；双方有指纹但零共享维 →
  score=0.0（真实的零重叠信号，照常计权，不当缺失降级，避免零重叠反而得分更高的
  排序失真）；
- 价格维：相似度 = min(price)/max(price)（同价=1，差价越大越低，纯比值可解释）；
  任一方无官方零售价、或双方价格均 ≤0 无法计算比值 → 该维 null。

诚实降级：维度缺失不伪造，缺失维权重置 0，score 在可用维权重上重归一化
（weights_used 记录实际使用的归一化权重）。候选门槛：与目标至少共享 1 个成分
（零交集无相似信号，不入选）。分数为相对排序信号，非功效承诺。

数据经 similar-levels 快照缓存（成分集合/功效指纹 O(1) 命中）+ 一条价格全表查询，
无 N+1。排序 (-score, id) 保证确定性。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.product import Product
from .efficacy_canon import OTHER
from .similar_levels import _norm, _snapshot_section

W_INGREDIENT = 0.5
W_EFFICACY = 0.3
W_PRICE = 0.2


def substitute_scorecard(session: Session, product_id: int, k: int = 5) -> dict:
    """返回 {"substitutes": [...]}；目标无成分表时 {"substitutes": [], "reason": ...}。"""
    sets = _snapshot_section(session, "sets")
    target = sets.get(product_id, set())
    if not target:
        return {"substitutes": [], "reason": "目标产品无成分表，无法比对"}
    fps = _snapshot_section(session, "fps")
    t_fp = {d: v for d, v in fps.get(product_id, {}).items() if d != OTHER}
    t_fp_norm = _norm(t_fp) if t_fp else None
    prices = dict(
        session.execute(select(Product.id, Product.price_current)
                        .where(Product.price_current.isnot(None))).all()
    )
    t_price = prices.get(product_id)

    scored = []
    for pid, s in sets.items():
        if pid == product_id:
            continue
        shared = len(target & s)
        if shared == 0:
            continue
        union = len(target | s)
        l1 = shared / union
        comp: dict = {"ingredient": {"score": round(l1, 4), "shared": shared, "union": union},
                      "efficacy": None, "price": None}
        parts = [(W_INGREDIENT, l1)]

        if t_fp and pid in fps:
            c_fp = {d: v for d, v in fps[pid].items() if d != OTHER}
            if c_fp:
                shared_dims = [d for d in t_fp if d in c_fp]
                # 零共享维 = 真实的零重叠信号（cos 0），照常计权；不降级为缺失
                cos = (sum(t_fp[d] * c_fp[d] for d in shared_dims)
                       / (t_fp_norm * _norm(c_fp))) if shared_dims else 0.0
                comp["efficacy"] = {
                    "score": round(cos, 4), "dimensions": len(shared_dims),
                    "top_shared_dims": sorted(shared_dims,
                                              key=lambda d: -min(t_fp[d], c_fp[d]))[:3]}
                parts.append((W_EFFICACY, cos))

        c_price = prices.get(pid)
        if t_price is not None and c_price is not None and max(t_price, c_price) > 0:
            sim = min(t_price, c_price) / max(t_price, c_price)
            comp["price"] = {"similarity": round(sim, 4),
                             "target_price": t_price, "candidate_price": c_price}
            parts.append((W_PRICE, sim))

        wsum = sum(pw for pw, _ in parts)
        score = sum(pw * pv for pw, pv in parts) / wsum
        weights_used = {
            "ingredient": round(W_INGREDIENT / wsum, 4),
            "efficacy": round(W_EFFICACY / wsum, 4) if comp["efficacy"] else 0.0,
            "price": round(W_PRICE / wsum, 4) if comp["price"] else 0.0,
        }
        scored.append((pid, score, comp, weights_used))

    scored.sort(key=lambda t: (-t[1], t[0]))
    top = scored[:k]
    products = {p.id: p for p in session.execute(
        select(Product).where(Product.id.in_([t[0] for t in top]))).scalars().all()} if top else {}
    substitutes = [
        {"id": pid, "name": products[pid].name, "brand": products[pid].brand,
         "score": round(score, 4), "components": comp, "weights_used": wu}
        for pid, score, comp, wu in top if pid in products
    ]
    return {"substitutes": substitutes}
