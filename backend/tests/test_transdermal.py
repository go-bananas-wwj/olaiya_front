"""D3 透皮可行性判定引擎单测（总纲 v4.1 支柱 I2 / W1-2 透皮 D3）。

覆盖：适用域闸四分支与优先级、500Da 规则、logP 窗口边界、
Potts-Guy 方程手算对账、cid_map.json 全量 60 键跑通。
所有判定语义为「理化模型估计，未考虑递送系统与配方基质」。
"""

import json
from pathlib import Path

import pytest

from app.services.transdermal import (
    TransdermalVerdict,
    get_transdermal_info,
    judge_transdermal,
    potts_guy_logkp,
)

CID_MAP_PATH = Path(__file__).resolve().parents[2] / "data" / "seed" / "cid_map.json"


@pytest.fixture(scope="module")
def cid_map() -> dict:
    return json.loads(CID_MAP_PATH.read_text(encoding="utf-8"))


# ---------- 适用域闸 ----------

class TestDomainGate:
    def test_mixture_flag_not_applicable(self):
        assert judge_transdermal(mw=None, xlogp=None, is_mixture=True) is TransdermalVerdict.NOT_APPLICABLE

    def test_mixture_beats_other_gates(self):
        # ① 混合物优先级最高：即使给了可判定的 MW/logP 也直接旁路
        assert judge_transdermal(mw=200.0, xlogp=2.0, is_mixture=True) is TransdermalVerdict.NOT_APPLICABLE
        assert judge_transdermal(mw=200.0, xlogp=2.0, is_mixture=True, is_ionic=True) is TransdermalVerdict.NOT_APPLICABLE

    def test_ionic_flag_not_applicable(self):
        assert judge_transdermal(mw=300.0, xlogp=1.5, is_ionic=True) is TransdermalVerdict.NOT_APPLICABLE

    def test_mw_over_600_not_applicable(self):
        assert judge_transdermal(mw=600.1, xlogp=2.0) is TransdermalVerdict.NOT_APPLICABLE
        # 阿基瑞林（乙酰基六肽-8）：MW 887 > 600，模型不适用
        assert judge_transdermal(mw=887.0, xlogp=-5.2) is TransdermalVerdict.NOT_APPLICABLE

    def test_xlogp_missing_not_applicable(self):
        assert judge_transdermal(mw=402.92, xlogp=None) is TransdermalVerdict.NOT_APPLICABLE

    def test_mw_missing_not_applicable(self):
        assert judge_transdermal(mw=None, xlogp=1.0) is TransdermalVerdict.NOT_APPLICABLE

    def test_mw_exactly_600_in_domain(self):
        # 闸 ③ 边界：MW 恰 600 仍在域内，再走 500Da 规则 → HARD
        assert judge_transdermal(mw=600.0, xlogp=2.0) is TransdermalVerdict.HARD


# ---------- 500Da 规则与 logP 窗口 ----------

class TestFiveHundredDaAndLogpWindow:
    @pytest.mark.parametrize(
        "mw,xlogp,expected",
        [
            # logP 最优窗口 [1,3] 且 MW ≤ 500 → EASY（含恰等边界）
            (200.0, 1.0, TransdermalVerdict.EASY),
            (200.0, 3.0, TransdermalVerdict.EASY),
            (500.0, 2.0, TransdermalVerdict.EASY),   # MW 恰 500 仍 EASY
            # 次优窗口 0–1 或 3–4 → MEDIUM（含恰等边界）
            (200.0, 0.0, TransdermalVerdict.MEDIUM),
            (200.0, 0.999, TransdermalVerdict.MEDIUM),
            (200.0, 3.5, TransdermalVerdict.MEDIUM),
            (200.0, 4.0, TransdermalVerdict.MEDIUM),
            # 窗口外 → HARD
            (200.0, -0.1, TransdermalVerdict.HARD),
            (200.0, 4.1, TransdermalVerdict.HARD),
            # 500Da 规则：500 < MW ≤ 600 → HARD（无论 logP）
            (500.1, 2.0, TransdermalVerdict.HARD),
            (524.9, 13.6, TransdermalVerdict.HARD),  # 视黄醇棕榈酸酯数值
            # MW>600 的大分子（如高分子量透明质酸）先中闸③旁路，不走 500Da HARD
            (5500.0, -2.0, TransdermalVerdict.NOT_APPLICABLE),
        ],
    )
    def test_window_boundaries(self, mw, xlogp, expected):
        assert judge_transdermal(mw=mw, xlogp=xlogp) is expected


# ---------- Potts-Guy 方程手算对账 ----------

class TestPottsGuy:
    def test_niacinamide_hand_calc(self):
        # 烟酰胺 MW=122.12, XLogP=-0.4，手算：
        # logKp = -2.7 + 0.71×(-0.4) − 0.0061×122.12
        #       = -2.7 − 0.284 − 0.744932 = -3.728932
        assert potts_guy_logkp(122.12, -0.4) == pytest.approx(-3.728932, abs=1e-6)

    def test_salicylic_acid_hand_calc(self):
        # 水杨酸 MW=138.12, XLogP=2.3，手算：
        # logKp = -2.7 + 0.71×2.3 − 0.0061×138.12
        #       = -2.7 + 1.633 − 0.842532 = -1.909532
        assert potts_guy_logkp(138.12, 2.3) == pytest.approx(-1.909532, abs=1e-6)


# ---------- get_transdermal_info（cid_map 集成） ----------

class TestGetTransdermalInfo:
    def test_mixture_centella(self, cid_map):
        # 积雪草提取物：no_single_cid → 混合物旁路
        info = get_transdermal_info("CENTELLA ASIATICA EXTRACT", cid_map)
        assert info["verdict"] is TransdermalVerdict.NOT_APPLICABLE
        assert info["logkp"] is None
        assert info["reason"]

    def test_salt_dipotassium_glycyrrhizate(self, cid_map):
        # 甘草酸二钾：DIPOTASSIUM 前缀 + -ATE 结尾 → 盐旁路（闸②先于 MW>600 闸③）
        info = get_transdermal_info("DIPOTASSIUM GLYCYRRHIZATE", cid_map)
        assert info["verdict"] is TransdermalVerdict.NOT_APPLICABLE
        assert info["logkp"] is None
        assert "盐" in info["reason"] or "离子" in info["reason"]

    def test_salt_zinc_pca(self, cid_map):
        # PCA 锌：PCA 盐形态名称规则命中 → 盐旁路（即使 MW 321.6 在域内）
        info = get_transdermal_info("ZINC PCA", cid_map)
        assert info["verdict"] is TransdermalVerdict.NOT_APPLICABLE
        assert info["logkp"] is None
        assert "盐" in info["reason"] or "离子" in info["reason"] or "PCA" in info["reason"]

    def test_polymer_priority_over_sodium_salt_rule(self, cid_map):
        # SODIUM ACETYLATED HYALURONATE 虽以 SODIUM 前缀命中盐名规则，
        # 但 cid_map 无单一 CID（聚合物），混合物/无 CID 优先级更高
        info = get_transdermal_info("SODIUM ACETYLATED HYALURONATE", cid_map)
        assert info["verdict"] is TransdermalVerdict.NOT_APPLICABLE
        assert "盐" not in info["reason"] and "离子" not in info["reason"]
        assert "CID" in info["reason"]

    def test_mw_over_600_acetyl_hexapeptide(self, cid_map):
        info = get_transdermal_info("ACETYL HEXAPEPTIDE-8", cid_map)
        assert info["verdict"] is TransdermalVerdict.NOT_APPLICABLE
        assert "600" in info["reason"]

    def test_xlogp_missing_copper_tripeptide(self, cid_map):
        info = get_transdermal_info("COPPER TRIPEPTIDE-1", cid_map)
        assert info["verdict"] is TransdermalVerdict.NOT_APPLICABLE
        assert "XLogP" in info["reason"] or "logP" in info["reason"].lower()

    def test_ceramide_np_hard_by_500da(self, cid_map):
        # 神经酰胺 NP：MW 582 ∈ (500, 600] 过闸③，命中 500Da 规则 → HARD
        info = get_transdermal_info("CERAMIDE NP", cid_map)
        assert info["verdict"] is TransdermalVerdict.HARD
        assert "500" in info["reason"]

    def test_hyaluronic_acid_mixture_not_hard(self, cid_map):
        # 透明质酸在 cid_map 为聚合物 no_single_cid：混合物旁路优先于 500Da 数值判定
        info = get_transdermal_info("HYALURONIC ACID", cid_map)
        assert info["verdict"] is TransdermalVerdict.NOT_APPLICABLE

    def test_glycolic_acid_hard_polar_small(self, cid_map):
        # 甘醇酸 MW 76.05 虽远小于 500Da，但 XLogP=-1.1 < 0：
        # 极亲水的极性小分子落在 logP 窗口（0 起点）之外 → HARD。
        # 与常识一致：强亲水小分子被动经皮渗透差（脂溶性路径为主），模型保守判难。
        info = get_transdermal_info("GLYCOLIC ACID", cid_map)
        assert info["verdict"] is TransdermalVerdict.HARD
        assert info["mw"] == pytest.approx(76.05)
        assert info["xlogp"] == pytest.approx(-1.1)
        # 可算 logKp（非 NOT_APPLICABLE 且有数据）→ 给出
        assert info["logkp"] == pytest.approx(potts_guy_logkp(76.05, -1.1), abs=1e-4)

    def test_salicylic_acid_easy(self, cid_map):
        info = get_transdermal_info("SALICYLIC ACID", cid_map)
        assert info["verdict"] is TransdermalVerdict.EASY
        assert info["logkp"] == pytest.approx(-1.909532, abs=1e-4)

    def test_niacinamide_info(self, cid_map):
        info = get_transdermal_info("NIACINAMIDE", cid_map)
        assert info["verdict"] is TransdermalVerdict.HARD  # XLogP=-0.4 < 0，窗口外
        assert info["logkp"] == pytest.approx(-3.728932, abs=1e-4)

    def test_info_keys_and_types(self, cid_map):
        info = get_transdermal_info("CAFFEINE", cid_map)
        assert set(info) >= {"verdict", "mw", "xlogp", "logkp", "reason"}
        assert isinstance(info["verdict"], TransdermalVerdict)

    def test_unknown_name_not_applicable(self, cid_map):
        info = get_transdermal_info("SOME FUTURE INGREDIENT", cid_map)
        assert info["verdict"] is TransdermalVerdict.NOT_APPLICABLE
        assert info["reason"]

    def test_full_cid_map_60_keys_no_exception(self, cid_map):
        assert len(cid_map) == 60
        for name in cid_map:
            info = get_transdermal_info(name, cid_map)
            assert isinstance(info["verdict"], TransdermalVerdict), name
            if info["verdict"] is TransdermalVerdict.NOT_APPLICABLE:
                assert info["reason"].strip(), f"{name} 的 NOT_APPLICABLE 缺 reason"
                assert info["logkp"] is None, f"{name} 不适用时不应给 logKp"
