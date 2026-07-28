"""浓度区间推断引擎：排序化 Dirichlet 拒绝采样。

在只有成分降序位次（INCI 表）、没有精确含量的情况下，用约束采样
估计每个成分的浓度区间：

1. 微量段（is_trace=True，共 t 个）：每个从 U(0, min(0.1, cap)) 采样，
   总和 S_trace；主段总量 S_main = 100 − S_trace。
2. 主成分段（is_trace=False，共 m 个）：从 Dirichlet(1,...,1) 采样并
   降序排列，赋给对应位次。带“水相先验”的成分（water=True）直接从
   先验区间均匀抽取——纯拒绝采样在驻留类先验 [50,95] 下接受率仅
   ~1.6%，无法在 n_samples×20 次尝试内收满样本；先验区间直接抽取
   后，驻留类下水 ≥50 而其余成分总和 <50，位次约束自动成立，其余
   约束仍走拒绝。
3. 约束拒绝：主段末位必须 ≥0.1（微量线定义）；任何成分不得超过
   upper_cap；leave_on 且 water=True 的成分必须在 [50,95]，淋洗类
   水相先验为 [40,90]；主段全体位次必须保持降序。
4. 拒绝采样最多 n_samples×20 次，收集 n_samples 个有效样本；不足则
   报错（说明约束矛盾，不得静默放宽）。
5. 输出：每成分取样本的 p5/p95 为 low/high；confidence =
   0.5 + 0.3×(有 cap 或 water 先验) + 0.2×(1 − 归一化区间宽度)，
   截断到 [0,1]；同一批输入同一 seed 输出逐位一致。
6. upper_cap 的组装不在本函数内（调用方从 Ingredient priors 取 min）。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

TRACE_LINE = 0.1  # 微量线：≤0.1% 的成分可乱序标注
WATER_PRIOR_LEAVE_ON = (50.0, 95.0)
WATER_PRIOR_RINSE_OFF = (40.0, 90.0)
MAX_ATTEMPTS_FACTOR = 20


@dataclass
class IngredientInput:
    inci_name: str
    is_trace: bool = False
    upper_cap: float | None = None  # min(legal_cap, iecic_max, cir_high)，无则 None
    water: bool = False  # 是否水（水相先验的对象）


@dataclass
class ConcentrationEstimate:
    inci_name: str
    low: float  # p5
    high: float  # p95
    confidence: float  # 0-1


def _water_prior(leave_on: bool) -> tuple[float, float]:
    return WATER_PRIOR_LEAVE_ON if leave_on else WATER_PRIOR_RINSE_OFF


def _preflight_check(ingredients: list[IngredientInput], leave_on: bool) -> None:
    """显式矛盾的静态预检：直接报错，不进入采样。"""
    main = [x for x in ingredients if not x.is_trace]
    trace = [x for x in ingredients if x.is_trace]
    if not main:
        raise ValueError("约束矛盾：主成分段为空，无法凑满 100%")
    for x in main:
        if x.upper_cap is not None and x.upper_cap < TRACE_LINE:
            raise ValueError(
                f"约束矛盾：{x.inci_name} 为主段成分（必须 ≥{TRACE_LINE}%），"
                f"但 upper_cap={x.upper_cap}"
            )
    lo, hi = _water_prior(leave_on)
    for x in main:
        if x.water:
            effective_hi = min(hi, x.upper_cap) if x.upper_cap is not None else hi
            if effective_hi < lo:
                raise ValueError(
                    f"约束矛盾：{x.inci_name} 水相先验要求 ≥{lo}%，"
                    f"但 upper_cap={x.upper_cap}"
                )
    total_cap = sum(min(x.upper_cap, 100.0) if x.upper_cap is not None else 100.0 for x in main)
    total_cap += sum(min(TRACE_LINE, x.upper_cap) if x.upper_cap is not None else TRACE_LINE for x in trace)
    if total_cap < 100.0:
        raise ValueError(f"约束矛盾：全部成分 upper_cap 之和 {total_cap:.3g} < 100")


def _sample_concentrations(
    ingredients: list[IngredientInput],
    *,
    leave_on: bool = True,
    n_samples: int = 2000,
    seed: int = 42,
) -> np.ndarray:
    """约束拒绝采样，返回 (n_samples, len(ingredients)) 的有效样本矩阵。

    列序与输入成分顺序一致。约束矛盾导致无法在 n_samples×20 次尝试内
    收满样本时抛出 ValueError。
    """
    _preflight_check(ingredients, leave_on)
    n = len(ingredients)
    main_idx = [i for i, x in enumerate(ingredients) if not x.is_trace]
    trace_idx = [i for i, x in enumerate(ingredients) if x.is_trace]
    water_idx = [i for i in main_idx if ingredients[i].water]
    other_main_idx = [i for i in main_idx if not ingredients[i].water]
    prior_lo, prior_hi = _water_prior(leave_on)

    rng = np.random.default_rng(seed)
    max_attempts = n_samples * MAX_ATTEMPTS_FACTOR
    attempts = 0
    chunks: list[np.ndarray] = []
    collected = 0

    while collected < n_samples and attempts < max_attempts:
        batch = min(max(2 * (n_samples - collected), 256), max_attempts - attempts)
        attempts += batch

        # 1) 微量段：U(0, min(0.1, cap))，总和 S_trace
        if trace_idx:
            trace_mat = np.column_stack(
                [
                    rng.uniform(
                        0.0,
                        min(TRACE_LINE, ingredients[i].upper_cap)
                        if ingredients[i].upper_cap is not None
                        else TRACE_LINE,
                        batch,
                    )
                    for i in trace_idx
                ]
            )
            s_trace = trace_mat.sum(axis=1)
        else:
            trace_mat = np.zeros((batch, 0))
            s_trace = np.zeros(batch)

        # 2) 主段：水相先验成分直接从先验区间抽取，其余 Dirichlet(1,...,1) 降序
        main_mat = np.empty((batch, len(main_idx)))
        water_sum = np.zeros(batch)
        for pos, i in enumerate(main_idx):
            x = ingredients[i]
            if x.water:
                hi = min(prior_hi, x.upper_cap) if x.upper_cap is not None else prior_hi
                wval = rng.uniform(prior_lo, hi, batch)
                main_mat[:, pos] = wval
                water_sum += wval
        remainder = 100.0 - s_trace - water_sum
        if other_main_idx:
            others = rng.dirichlet(np.ones(len(other_main_idx)), size=batch)
            others = np.sort(others, axis=1)[:, ::-1] * remainder[:, None]
            for j, i in enumerate(other_main_idx):
                main_mat[:, main_idx.index(i)] = others[:, j]

        # 3) 约束拒绝
        valid = remainder >= 0.0
        # 主段末位 ≥0.1（微量线定义）
        valid &= main_mat[:, -1] >= TRACE_LINE
        # 主段位次降序（含跨水相先验成分的位次一致性）
        if len(main_idx) > 1:
            valid &= np.all(np.diff(main_mat, axis=1) <= 1e-12, axis=1)
        # upper_cap
        for pos, i in enumerate(main_idx):
            cap = ingredients[i].upper_cap
            if cap is not None:
                valid &= main_mat[:, pos] <= cap + 1e-12

        kept = main_mat[valid]
        kept_trace = trace_mat[valid]
        if kept.size:
            rows = np.empty((kept.shape[0], n))
            for pos, i in enumerate(main_idx):
                rows[:, i] = kept[:, pos]
            for j, i in enumerate(trace_idx):
                rows[:, i] = kept_trace[:, j]
            chunks.append(rows)
            collected += rows.shape[0]

    if collected < n_samples:
        raise ValueError(
            f"约束矛盾：{attempts} 次尝试（上限 n_samples×{MAX_ATTEMPTS_FACTOR}）内"
            f"仅收集到 {collected}/{n_samples} 个有效样本，"
            "请检查 upper_cap 与水相先验是否互相冲突"
        )
    return np.concatenate(chunks, axis=0)[:n_samples]


def estimate_concentrations(
    ingredients: list[IngredientInput],
    *,
    leave_on: bool = True,  # 驻留类(True)/淋洗类(False)，影响水相先验
    n_samples: int = 2000,
    seed: int = 42,
) -> list[ConcentrationEstimate]:
    """估计每个成分的浓度区间（p5/p95）与置信度。"""
    if not ingredients:
        return []
    samples = _sample_concentrations(
        ingredients, leave_on=leave_on, n_samples=n_samples, seed=seed
    )
    low = np.percentile(samples, 5, axis=0)
    high = np.percentile(samples, 95, axis=0)
    estimates: list[ConcentrationEstimate] = []
    for i, x in enumerate(ingredients):
        has_prior = x.upper_cap is not None or x.water
        width_norm = (high[i] - low[i]) / 100.0
        confidence = 0.5 + 0.3 * has_prior + 0.2 * (1.0 - width_norm)
        confidence = min(1.0, max(0.0, confidence))
        estimates.append(
            ConcentrationEstimate(
                inci_name=x.inci_name,
                low=float(low[i]),
                high=float(high[i]),
                confidence=float(confidence),
            )
        )
    return estimates
