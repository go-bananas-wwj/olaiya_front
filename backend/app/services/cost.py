"""每起效成本（总纲 I3）：把产品按文献起效浓度折算后的每日使用成本（估计值）。

口径：每日用量按 1ml 计，将产品「稀释」到文献起效浓度后折算——
成本 = (price / spec_ml) × (eff_low / conc_mid)。输出为模型估计值，
展示必须带「估计」语义（数据铁律 3）。
"""

from __future__ import annotations

import re

# 单一容量/质量规格："30ml" / "50g" / "230毫升" / "50克"（克按 1g≈1ml 折算体积口径）
_SPEC_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ml|g|毫升|克)\s*$", re.IGNORECASE)


def parse_spec_ml(spec: str | None) -> float | None:
    """解析主规格为 ml 数（g 视同 ml）："30ml"→30.0，"50g"→50.0，其他形态→None。"""
    if not spec:
        return None
    m = _SPEC_RE.match(spec)
    if m is None:
        return None
    return float(m.group(1))


def cost_per_effective_dose(
    *, price: float, spec_ml: float, conc_mid: float, eff_low: float
) -> float | None:
    """按起效浓度折算的每日使用成本（元/天，按 1ml 用量）：
    = (price / spec_ml) × (eff_low / conc_mid)；conc_mid<=0 时返回 None。
    语义：把产品按推断浓度稀释到文献起效浓度后，每毫升用量折算的成本（估计值）。
    """
    if conc_mid <= 0:
        return None
    return price / spec_ml * eff_low / conc_mid
