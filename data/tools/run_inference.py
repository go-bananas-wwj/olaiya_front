"""浓度推断执行器 + 锚点校准（计划 02 Task 3）。

对库内所有「成分位次非空」的产品批量执行浓度区间推断：
组装 IngredientInput（cap 取成分先验最小值）→ 调推断引擎 →
回写 conc_low/conc_high/conc_confidence → 用品牌披露锚点做校准验收。

CLI：
    cd /root/workspace/olaiya && PYTHONPATH=backend .venv/bin/python -m data.tools.run_inference

校准说明（详见 .superpowers/sdd/p02t3-report.md）：
- 默认引擎先验（Dirichlet α=1 平坦、无下限、水相 [50,95]）在真实库上
  锚点覆盖率不足，且成分数多的大配方拒绝采样接受率趋零直接报错；
  以下 CALIBRATED_* 常量是经锚点校准网格搜索确定的采样先验参数，
  只调先验，不动披露值与区间输出语义（p5/p95 + confidence 公式不变）。
- 水相标记规则：按成分名判定（WATER/AQUA/水），但仅当水位居成分表
  首位（position == 1，即水为配方基底）时才适用水相先验。SK-II 神仙水
  首位是半乳糖酵母样菌发酵产物滤液（披露 90%）、水仅在第 4 位，若对
  其中位水施加 ≥50% 的水相先验则与位次降序约束矛盾（前三位均须 ≥ 水）。
"""

from __future__ import annotations

from sqlalchemy.orm import object_session

from app.db import SessionLocal
from app.models.ingredient import Ingredient
from app.models.product import Product, ProductIngredient
from app.services.concentration import IngredientInput, estimate_concentrations

# —— 锚点校准确定的采样先验（网格搜索结果，见 p02t3-report.md）——
CALIBRATED_DIRICHLET_ALPHA = 0.45
CALIBRATED_DIRICHLET_DECAY: float | None = None  # 位次衰减路径扫参劣于可交换路径，弃用
CALIBRATED_MAIN_FLOOR = 0.15  # 主段非水成分下限先验（%）：救大配方接受率并托底低位次
CALIBRATED_WATER_PRIOR_LEAVE_ON: tuple[float, float] | None = (30.0, 95.0)

WATER_INCI_NAMES = {"WATER", "AQUA"}
# category 含任一关键词即淋洗类，否则驻留类
RINSE_OFF_KEYWORDS = ("洗", "洁面", "洗发", "沐浴", "卸妆", "发膜")

ANCHOR_TOLERANCE = 0.2  # 锚点命中相对容差：披露值 ∈ [low×0.8, high×1.2]


def is_leave_on(category: str | None) -> bool:
    """驻留类(True)/淋洗类(False)：category 不含淋洗关键词即驻留类。"""
    if not category:
        return True
    return not any(kw in category for kw in RINSE_OFF_KEYWORDS)


def _is_water_name(ingredient: Ingredient) -> bool:
    return (
        ingredient.inci_name.upper() in WATER_INCI_NAMES
        or (ingredient.cn_name or "") == "水"
    )


def _upper_cap(ingredient: Ingredient, leave_on: bool) -> float | None:
    """min(legal_cap, iecic_max(按 leave_on), cir_conc_high, sccs_limit)；None 不参与。"""
    iecic = ingredient.iecic_max_leave_on if leave_on else ingredient.iecic_max_rinse_off
    candidates = [
        v
        for v in (ingredient.legal_cap, iecic, ingredient.cir_conc_high, ingredient.sccs_limit)
        if v is not None
    ]
    return min(candidates) if candidates else None


def _positioned_rows(product: Product) -> list[ProductIngredient]:
    session = object_session(product)
    if session is None:
        raise ValueError(f"产品 {product.name!r} 未附着于 session，无法读取成分关联")
    return (
        session.query(ProductIngredient)
        .filter(
            ProductIngredient.product_id == product.id,
            ProductIngredient.position.isnot(None),
        )
        .order_by(ProductIngredient.position)
        .all()
    )


def assemble_inputs(
    product: Product, ingredients_by_id: dict[int, Ingredient]
) -> tuple[list[IngredientInput], bool]:
    """按位次升序组装引擎输入，返回 (inputs, leave_on)。

    水相先验仅适用于位居成分表首位（position == 1）的水——此时水才是
    配方基底；水居表中位（如 SK-II）则按普通成分处理，否则水相先验与
    位次降序约束矛盾。
    """
    leave_on = is_leave_on(product.category)
    items: list[IngredientInput] = []
    for pi in _positioned_rows(product):
        ing = ingredients_by_id[pi.ingredient_id]
        items.append(
            IngredientInput(
                inci_name=ing.inci_name,
                is_trace=pi.is_trace,
                upper_cap=_upper_cap(ing, leave_on),
                water=_is_water_name(ing) and pi.position == 1,
            )
        )
    return items, leave_on


def anchor_hit(low: float, high: float, disclosed: float, *, tol: float = ANCHOR_TOLERANCE) -> bool:
    """锚点命中判定：披露值落在 [low×(1−tol), high×(1+tol)]（±20% 相对容差，含边界）。"""
    return low * (1.0 - tol) <= disclosed <= high * (1.0 + tol)


def run_inference(
    session,
    *,
    n_samples: int = 2000,
    seed: int = 42,
    dirichlet_alpha: float = CALIBRATED_DIRICHLET_ALPHA,
    main_floor: float = CALIBRATED_MAIN_FLOOR,
    water_prior_leave_on: tuple[float, float] | None = CALIBRATED_WATER_PRIOR_LEAVE_ON,
    dirichlet_decay: float | None = CALIBRATED_DIRICHLET_DECAY,
) -> dict:
    """对所有位次非空产品跑推断并回写结果，返回统计与明细。

    返回 {products_inferred, anchors_total, anchors_hit, coverage,
          products, anchor_details}；coverage 在无锚点时为 None。
    """
    product_ids = [
        pid
        for (pid,) in session.query(ProductIngredient.product_id)
        .filter(ProductIngredient.position.isnot(None))
        .distinct()
        .order_by(ProductIngredient.product_id)
    ]
    ingredients_by_id = {i.id: i for i in session.query(Ingredient).all()}

    products_out: list[dict] = []
    anchor_details: list[dict] = []
    failed_products: list[dict] = []
    anchors_total = anchors_hit = 0
    for pid in product_ids:
        product = session.get(Product, pid)
        items, leave_on = assemble_inputs(product, ingredients_by_id)
        try:
            estimates = estimate_concentrations(
                items,
                leave_on=leave_on,
                n_samples=n_samples,
                seed=seed,
                dirichlet_alpha=dirichlet_alpha,
                main_floor=main_floor,
                water_prior=water_prior_leave_on if leave_on else None,
                dirichlet_decay=dirichlet_decay,
            )
        except ValueError as exc:
            # 约束矛盾导致采样失败：不得静默跳过——该产品锚点全部计入
            # 分母且计为未命中，保证覆盖率口径诚实
            failed_products.append({"name": product.name, "reason": str(exc)})
            for pi in _positioned_rows(product):
                if pi.disclosed_conc is not None:
                    anchors_total += 1
                    anchor_details.append(
                        {
                            "product": product.name,
                            "inci": ingredients_by_id[pi.ingredient_id].inci_name,
                            "position": pi.position,
                            "disclosed": pi.disclosed_conc,
                            "low": None,
                            "high": None,
                            "hit": False,
                        }
                    )
            continue
        # estimates 与位次升序行一一对应，逐行回写
        for pi, est in zip(_positioned_rows(product), estimates):
            pi.conc_low = est.low
            pi.conc_high = est.high
            pi.conc_confidence = est.confidence
            if pi.disclosed_conc is not None:
                hit = anchor_hit(est.low, est.high, pi.disclosed_conc)
                anchors_total += 1
                anchors_hit += int(hit)
                anchor_details.append(
                    {
                        "product": product.name,
                        "inci": est.inci_name,
                        "position": pi.position,
                        "disclosed": pi.disclosed_conc,
                        "low": est.low,
                        "high": est.high,
                        "hit": hit,
                    }
                )
        products_out.append(
            {
                "name": product.name,
                "leave_on": leave_on,
                "n_ingredients": len(items),
                "examples": [
                    {"inci": e.inci_name, "low": e.low, "high": e.high}
                    for e in estimates[:3]
                ],
            }
        )
    session.commit()
    return {
        "products_inferred": len(products_out),
        "anchors_total": anchors_total,
        "anchors_hit": anchors_hit,
        "coverage": (anchors_hit / anchors_total) if anchors_total else None,
        "products": products_out,
        "anchor_details": anchor_details,
        "failed_products": failed_products,
    }


def main() -> None:
    session = SessionLocal()
    try:
        stats = run_inference(session)
    finally:
        session.close()

    print("—— 浓度区间推断（每产品一行）——")
    for p in stats["products"]:
        examples = "; ".join(
            f"{e['inci']} [{e['low']:.2f}, {e['high']:.2f}]" for e in p["examples"]
        )
        kind = "驻留" if p["leave_on"] else "淋洗"
        print(f"{p['name']} | {p['n_ingredients']} 成分({kind}) | {examples}")

    print("\n—— 锚点校准 ——")
    for a in stats["anchor_details"]:
        mark = "✓" if a["hit"] else "✗"
        if a["low"] is None:
            print(
                f"{mark} {a['product']} / {a['inci']} (#{a['position']}) "
                f"披露 {a['disclosed']:g}% —— 采样失败，按未命中计"
            )
        else:
            print(
                f"{mark} {a['product']} / {a['inci']} (#{a['position']}) "
                f"披露 {a['disclosed']:g}% ∈? [{a['low']:.3f}, {a['high']:.3f}]"
                f"（容差 [{a['low'] * 0.8:.3f}, {a['high'] * 1.2:.3f}]）"
            )
    for f in stats["failed_products"]:
        print(f"!! 采样失败：{f['name']} —— {f['reason']}")
    cov = stats["coverage"]
    if cov is None:
        print("\n无锚点可校准。")
    else:
        verdict = "达标" if cov >= 0.8 else "未达标"
        print(
            f"\n锚点覆盖率 = {stats['anchors_hit']}/{stats['anchors_total']}"
            f" = {cov:.1%}（验收线 80%，{verdict}）"
        )
    print(f"推断产品数：{stats['products_inferred']}")


if __name__ == "__main__":
    main()
