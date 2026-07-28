"""D3 透皮可行性判定引擎（总纲 v4.1 支柱 I2，W1-2 透皮 D3）。

基于公开理化规则的经验模型：

1. 适用域闸（顺序固定，先中先出）：
   ① 混合物/提取物/聚合物 → NOT_APPLICABLE（无单一结构，模型不适用）；
   ② 离子型/盐 → NOT_APPLICABLE（Potts-Guy 校于中性小分子，带电物种出域）；
   ③ MW > 600 或 XLogP 缺失 → NOT_APPLICABLE（超出规则外推边界/缺数据）；
   ④ 500Da 规则（Bos & Meinardi 2000）：MW > 500 → HARD；
   ⑤ logP 窗口：1 ≤ xlogp ≤ 3 且 MW ≤ 500 → EASY；
      0 ≤ xlogp < 1 或 3 < xlogp ≤ 4 → MEDIUM；其他 → HARD。
2. Potts-Guy 方程：logKp = -2.7 + 0.71·logP − 0.0061·MW
   （Potts & Guy 1992，仅中性小分子域，Kp 单位 cm/h）。
3. 不可判定旁路：NOT_APPLICABLE 是合法输出而非失败——对混合物/盐/
   大分子/缺数据成分显式声明「模型不适用」，不给数值。

**铁律：本模块所有输出语义为「理化模型估计，未考虑递送系统与配方
基质」**。EASY/MEDIUM/HARD 仅表达被动扩散的理化可行性分级，不构成
功效可达性断言；实际透皮受促渗剂、载体、配方基质、皮肤状态影响。
判定结果不做超过模型能力的断言。
"""

from __future__ import annotations

import enum

DISCLAIMER = "理化模型估计，未考虑递送系统与配方基质"

MW_NA_LIMIT = 600.0   # 闸③：MW 超过此值模型不适用
MW_500DA = 500.0      # 闸④：500Da 规则
LOGP_EASY_LO, LOGP_EASY_HI = 1.0, 3.0      # 闸⑤最优窗口（闭区间）
LOGP_MEDIUM_BANDS = ((0.0, 1.0), (3.0, 4.0))  # 次优窗口 [0,1) 与 (3,4]

# 名称级混合物/聚合物关键词（整词匹配；仅作 cid_map 未收录时的保守兜底）
_MIXTURE_WORDS = {
    "EXTRACT", "OIL", "BUTTER", "FERMENT", "COLLAGEN",
    "HYALURONATE", "HYALURONIC", "POLYSACCHARIDE", "PROTEIN",
}


class TransdermalVerdict(str, enum.Enum):
    EASY = "easy"                        # 易透皮
    MEDIUM = "medium"                    # 中等
    HARD = "hard"                        # 难透皮
    NOT_APPLICABLE = "not_applicable"    # 模型不适用（混合物/盐/大分子/缺数据）


def judge_transdermal(
    *,
    mw: float | None,
    xlogp: float | None,
    is_mixture: bool = False,
    is_ionic: bool = False,
) -> TransdermalVerdict:
    """透皮可行性判定。适用域闸顺序固定：①混合物 ②离子/盐 ③MW>600 或
    XLogP 缺失 ④500Da 规则 ⑤logP 窗口（见模块 docstring）。"""
    # ① 混合物/提取物/聚合物：无单一结构，模型不适用
    if is_mixture:
        return TransdermalVerdict.NOT_APPLICABLE
    # ② 离子型/盐：Potts-Guy 校于中性小分子，带电物种出域
    if is_ionic:
        return TransdermalVerdict.NOT_APPLICABLE
    # ③ MW > 600 或数据缺失：超出规则外推边界
    if mw is None or mw > MW_NA_LIMIT or xlogp is None:
        return TransdermalVerdict.NOT_APPLICABLE
    # ④ 500Da 规则
    if mw > MW_500DA:
        return TransdermalVerdict.HARD
    # ⑤ logP 窗口
    if LOGP_EASY_LO <= xlogp <= LOGP_EASY_HI and mw <= MW_500DA:
        return TransdermalVerdict.EASY
    if any(lo <= xlogp < hi for lo, hi in LOGP_MEDIUM_BANDS[:1]) or (
        LOGP_MEDIUM_BANDS[1][0] < xlogp <= LOGP_MEDIUM_BANDS[1][1]
    ):
        return TransdermalVerdict.MEDIUM
    return TransdermalVerdict.HARD


def potts_guy_logkp(mw: float, xlogp: float) -> float:
    """Potts-Guy 方程：logKp = -2.7 + 0.71·logP − 0.0061·MW（仅中性小分子域）。"""
    return -2.7 + 0.71 * xlogp - 0.0061 * mw


def _ionic_rule_hit(name: str) -> str | None:
    """INCI 名盐/两性离子规则；命中返回规则描述，未命中返回 None。

    规则：PCA 盐形态（ZINC PCA 等）、(DI)POTASSIUM 钾盐、SODIUM/DISODIUM
    前缀钠盐、-ATE 结尾盐（保守：酯类如 PALMITATE/RETINOATE 亦会被旁路，
    宁可不可判定也不超出模型能力给数值）。
    """
    words = name.split()
    if "PCA" in words:
        return "PCA 盐形态"
    if any(w in ("POTASSIUM", "DIPOTASSIUM") for w in words):
        return "钾盐"
    if words and words[0] in ("SODIUM", "DISODIUM"):
        return "钠盐"
    if words and words[-1].endswith("ATE"):
        return "-ATE 结尾盐"
    return None


def _verdict_reason(verdict: TransdermalVerdict, *, mw, xlogp, ionic_hit) -> str:
    if verdict is TransdermalVerdict.NOT_APPLICABLE:
        if ionic_hit:
            return f"离子型/盐（名称规则：{ionic_hit}），Potts-Guy 仅适用中性小分子，模型不适用"
        if mw is not None and mw > MW_NA_LIMIT:
            return f"MW={mw:g} > 600 Da，超出 500Da 规则外推边界，模型不适用"
        return "缺 MW/XLogP 数据，模型不适用"
    if verdict is TransdermalVerdict.EASY:
        return f"1 ≤ logP={xlogp:g} ≤ 3 且 MW={mw:g} ≤ 500，logP 最优窗口内 → 易透皮（估计）"
    if verdict is TransdermalVerdict.MEDIUM:
        return f"logP={xlogp:g} 处次优窗口（0–1 或 3–4）→ 中等（估计）"
    if mw is not None and mw > MW_500DA:
        return f"MW={mw:g} > 500 Da（500Da 规则）→ 难透皮（估计）"
    return f"logP={xlogp:g} 在窗口外（<0 或 >4）→ 难透皮（估计）"


def get_transdermal_info(inci_name: str, cid_map: dict) -> dict:
    """查成分透皮信息：{verdict, mw, xlogp, logkp(可算则给), reason}。

    混合物/无单一 CID 的判定优先于盐名规则（如 SODIUM ACETYLATED
    HYALURONATE 属聚合物，先按 cid_map 的 no_single_cid/not_found 旁路）。
    """
    name = inci_name.strip().upper()
    entry = cid_map.get(name)
    base = {"verdict": None, "mw": None, "xlogp": None, "logkp": None, "reason": ""}

    if entry is not None and entry.get("status") != "ok":
        # 混合物/聚合物/未命中 PubChem：无单一 CID，模型不适用（优先于盐名规则）
        note = entry.get("note") or entry.get("status") or "无单一 CID"
        return {
            **base,
            "verdict": TransdermalVerdict.NOT_APPLICABLE,
            "reason": f"无单一 CID/结构（{note}），模型不适用",
        }
    if entry is None:
        words = set(name.split())
        if words & _MIXTURE_WORDS:
            reason = "聚合物/混合物名称（未收录单一 CID），模型不适用"
        else:
            reason = "不在 CID 映射表中，无理化数据，模型不适用"
        return {**base, "verdict": TransdermalVerdict.NOT_APPLICABLE, "reason": reason}

    mw = float(entry["mw"]) if entry.get("mw") not in (None, "") else None
    xlogp_raw = entry.get("xlogp")
    xlogp = float(xlogp_raw) if xlogp_raw is not None else None
    ionic_hit = _ionic_rule_hit(name)
    verdict = judge_transdermal(mw=mw, xlogp=xlogp, is_ionic=ionic_hit is not None)
    logkp = None
    if verdict is not TransdermalVerdict.NOT_APPLICABLE and mw is not None and xlogp is not None:
        logkp = round(potts_guy_logkp(mw, xlogp), 4)
    return {
        "verdict": verdict,
        "mw": mw,
        "xlogp": xlogp,
        "logkp": logkp,
        "reason": _verdict_reason(verdict, mw=mw, xlogp=xlogp, ionic_hit=ionic_hit),
    }
