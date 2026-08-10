"""batch-9-cir.json 人工核订后处理：浓度回填候选逐条与 PDF 原文核对后的修正表。

背景：collect_cir.py 的 prose「up to X%」提取存在已知误吸（纯度/毒理剂量/同句其他
成分数值/历史年份数据/药品语境），2026-08-10 对全部 57 个浓度候选逐条回读
data/raw/cir/pdf/ 原文核对（上下文审查记录见任务交接）。第二轮（同日，独立审查
M1）：low 为 prose 命中最小值的问题成批存在，52 个有值成分再逐条回读 PDF 使用表，
语义统一为「行业调查使用浓度区间（全品类合计）」（Total/range 行优先）。本脚本把
核对结论固化为修正表，幂等地重写 batch-9-cir.json：
- OVERRIDE[inci] = (low, high)：修正 cir_conc_low/high（None 表示该侧无数值）；
- OVERRIDE[inci] = None：撤回浓度回填（误吸，原文无可信的 CIR 行业调查使用浓度）；
- 断言 efficacy 的浓度表述按最终 (low, high) 重新生成，保证不断言错误数值；
- 被人工修正的成分在断言 note 追加「浓度数值经人工与报告原文核对」。

运行：/tmp/pdfenv/bin/python data/tools/review_cir_batch.py  或  .venv/bin/python（无第三方依赖）
"""

import json
from pathlib import Path

BATCH = Path(__file__).resolve().parents[1] / "research" / "batch-9-cir.json"

# 人工核订表（2026-08-10，逐条回读 PDF 原文）：
# (low, high) 修正；None 撤回。未列出的成分保持解析器原值（已核对无误）。
#
# 第二轮（2026-08-10，独立审查 M1 修复）：cir_conc_low/high 语义统一为
# 「CIR 行业调查使用浓度区间（全品类合计）」——取报告使用表 Total/range 行；
# 无 Total 行取驻留/淋洗区间最小低值与最大高值；报告只报最大值或表格机读不出
# （矢量表格无文本层）时 low 置 None。第一轮只核了 high，本轮 52 个有值成分
# 逐条回读 PDF 使用表重核 low（并顺带修正少数 high）。
OVERRIDE: dict[str, tuple[float | None, float | None] | None] = {
    # —— 第二轮修正（low 重核，部分 high 连带修正）——
    "GLYCERIN": (0.0001, 99.4),           # 表2 Total/range 15,654 0.0001-99.4（原 low=4.0 为 prose 最小值）
    "TOCOPHEROL": (0.0000009, 5.4),       # 表4 Totals 2013 调查 0.0000009-5.4（原 70.0 为棕榈油组成、原 low 0.2 为 tocopheryl acetate 喷雾值）
    "TOCOPHERYL ACETATE": (0.00000001, 36.0),  # 表4 Totals 2013 调查 0.00000001-36（原 low 0.1 为气雾除臭剂值）
    "CITRIC ACID": (0.0000005, 39.0),     # 表6 Totals 6795 0.0000005-39（39% 为浴用稀释前浓度，Total 行口径）
    "TRISODIUM EDTA": (None, 2.0),        # 2023 增补仅散文：2% 为 1998 历史最大（淋洗浴皂），无区间，low 置空
    "SODIUM HYDROXIDE": (0.0000083, 12.9),  # 表4 Totals 5147 0.0000083-12.9（原 low 0.26 为偶然摄入行值）
    "POTASSIUM HYDROXIDE": (0.0000049, 10.0),  # 表4 Totals 1074 0.0000049-10（原 1.5 为 SCCS 引文、high 7 仅驻留）
    "XANTHAN GUM": (0.00001, 6.0),        # 表5 Totals 3,470 0.00001-6
    "SODIUM HYALURONATE": (0.00001, 7.5), # 表4 Totals 2022 调查 0.00001-7.5（原 low 0.005 为 prose）
    "SILICA": (0.000005, 82.0),           # 表3 Totals 2018 调查 0.000005-82（原 low 0.84 为气雾除臭剂值）
    "PANTHENOL": (0.0000053, 5.3),        # 表3 Panthenol 列 Totals 2016 调查 0.0000053-5.3（原 low 0.1 为 prose）
    "GLYCERYL STEARATE": (0.0002, 18.9),  # 表5 Totals 2014 调查 0.0002-18.9（原 50% 为 1976 历史值）
    "SALICYLIC ACID": (0.00001, 30.0),    # 表3 Totals 2018 调查 0.00001-30（原 low 0.1 为 prose）
    "ETHYLHEXYL SALICYLATE": (0.0003, 5.1),  # 表3 Totals 2018 调查 0.0003-5.1（2000 历史调查另有 0.001-8；原 35.9 为 Butyloctyl Salicylate）
    "CAPRYLIC/CAPRIC TRIGLYCERIDE": (0.0000067, 95.6),  # 表5 Totals 2017 调查 0.0000067-95.6（原 83.3 为眼部品类历史值）
    "PROPANEDIOL": (None, 39.9),          # 表4 矢量表格无文本层机读不出；散文最高 39.9%（非喷雾除臭剂），low 置空
    "BENZYL SALICYLATE": (0.0036, 0.5),   # 表2 Totals 3079 0.0036-0.5（2016 调查仅覆盖光稳定剂用途）
    "METHYLPARABEN": (0.000001, 0.9),     # 表5 Totals 2016 调查 0.000001-0.9（原 low 0.35 为 prose）
    "ETHYLPARABEN": (0.00000032, 0.65),   # 表5 Totals 2016 调查 0.00000032-0.65（原 0.9 为 Methylparaben）
    "BUTYROSPERMUM PARKII (SHEA) BUTTER": (None, 100.0),  # 表4 矢量表格机读不出；Discussion 最大 100%（驻留），low 置空
    "ETHYLHEXYLGLYCERIN": (0.000001, 8.0),  # 表3 Totals/concrange 1066 0.000001-8
    "PENTAERYTHRITYL TETRA-DI-T-BUTYL HYDROXYHYDROCINNAMATE": (0.00001, 0.8),  # 表2 Totals 769 0.00001-0.8
    "CHLORPHENESIN": (0.000008, 0.32),    # 表2 Totals/concrange 1386 0.000008-0.32
    "TRISODIUM ETHYLENEDIAMINE DISUCCINATE": (0.0039, 0.64),  # 表3 Totals 199 0.0039-0.64（原 0.19 为婴儿产品品类值）
    "CAFFEINE": (0.00005, 6.0),           # 表3 Totals 1033 0.00005-6
    "DISTEARDIMONIUM HECTORITE": (0.04, 28.0),  # 表3 Totals/concrange 584 0.04-28（原 low 3.0 为 hair-coloring 品类值）
    "ASCORBYL GLUCOSIDE": (0.00081, 5.0), # 表2 Totals/Conc.Range 532 0.00081-5（原 low 0.01 为头发喷雾品类值）
    "HYDROXYACETOPHENONE": (0.00009, 5.0),  # 表2 Totals 791 0.00009-5（原 100 为纯度、原 low 0.23 为眼部品类值）
    "POLYMETHYLSILSESQUIOXANE": (0.00001, 55.2),  # 表4 Total/range 397 0.00001-55.2
    "POTASSIUM CETYL PHOSPHATE": (0.05, 8.3),  # 表3 Totals 375 0.05-8.3（原 8.3 单边值）
    "SORBITOL": (0.00007, 70.0),          # 表3 Totals Sorbitol 列 0.00007-70（原 70 单边值）
    "CAMELLIA SINENSIS LEAF EXTRACT": (0.00002, 2.0),  # 表7 Total/range 1,966 0.00002-2
    "TALC": (0.0005, 100.0),              # 表2 Totals 3469 0.0005-100（原 low 30 为 prose）
    "MAGNESIUM SULFATE": (0.00001, 49.0), # 表1 Totals/Concrange 504 0.00001-49（原 1.0-25 漏浴用 49%）
    "TRIETHOXYCAPRYLYLSILANE": (0.000001, 2.6),  # 表3 Total/range 417 0.000001-2.6
    "PALMITOYL PENTAPEPTIDE-4": (0.000005, 0.0035),  # 表3 Totals 239 0.000005-0.0035
    "PEG/PPG-14/7 DIMETHYL ETHER": (0.00011, 7.0),  # 表4 Total 35 0.00011-7
    "PPG-5-CETETH-20": (0.05, 10.0),      # 表4 Total 445 0.05-10
    "SODIUM PCA": (None, 3.0),            # 报告只报最大值（驻留 2.5%/淋洗 3%），无区间，low 置空
    "HYDROLYZED SOY PROTEIN": (0.00003, 3.5),  # 表4 Totals 862 0.00003-3.5
    "DICAPRYLYL CARBONATE": (0.3, 34.5),  # 表4 Totals/Conc.Range 384 0.3-34.5（原 low 1.5 为喷雾品类值）
    "POLYSILICONE-11": (0.025, 19.9),     # 表1 Totals 440 0.025-19.9
    # —— 第一轮已核对、第二轮表格复核确认不变 ——
    "PROPYLENE GLYCOL": (0.0008, 99.0),   # 表4 Total for propylene glycol 0.0008-99（第一轮值表格复核一致）
    "CAPRYLOYL SALICYLIC ACID": (0.1, 0.5),  # 表2 Totals 104 0.1-0.5 复核一致
    "ADENOSINE": (0.04, 1.0),             # 表3 Totals 905 0.04-1 复核一致
    "CERAMIDE NP": (None, 0.2),           # 原 4-20 为毒理试验浓度；驻留最大 0.2%
    "CERAMIDE AP": (None, 0.2),           # 同上
    "2-OLEAMIDO-1,3-OCTADECANEDIOL": (None, 0.2),  # 同上
    "SYNTHETIC FLUORPHLOGOPITE": (0.00002, 67.0),  # 表3 Total/concentrationrange 675 0.00002-67 复核一致
    "CYCLOPENTASILOXANE": (0.0001, 93.0), # 表3 Total uses/ranges for cyclopentasiloxane 0.0001-93 复核一致
    "DIMETHICONE CROSSPOLYMER": (0.007, 25.0),  # 表4 Total/range 442 0.007-25 复核一致
    "ALLANTOIN": (0.0001, 2.0),           # 表 Total uses/ranges for allantoin 1376 0.0001-2 复核一致（原 4.0 为药品语境）
    # —— 撤回（原文无可信的 CIR 行业调查使用浓度）——
    "SODIUM ACETYLATED HYALURONATE": None,  # 0.39% 实为 Sodium Hyaluronate 唇膏数值
    "SODIUM BENZOATE": None,                # 提取值出自 SCCP 意见引文，非 CIR 调查
    "BENZOIC ACID": None,                   # 同上
    "ISODODECANE": None,                    # 「10% in olive oil」为试验溶剂
    "MALTODEXTRIN": None,                   # 50% 为同句 algin 的数值；Maltodextrin 仅有使用频度
}

NOTE_TAG = "；浓度数值经人工与报告原文核对"


def _fmt(v: float) -> str:
    """定点格式化浓度值：禁止科学计数法（9e-07 → 0.0000009），去尾零（100.0 → 100）。"""
    return f"{v:.10f}".rstrip("0").rstrip(".")


def _conc_txt(low: float | None, high: float | None) -> str:
    if low is None and high is None:
        return ""
    if low is None or low == high:
        return f"；行业调查最大使用浓度 {_fmt(high)}%，非安全限值"
    return f"；行业调查使用浓度区间 {_fmt(low)}%-{_fmt(high)}%，非安全限值"


def main() -> None:
    batch = json.loads(BATCH.read_text(encoding="utf-8"))
    fixed = dropped = 0
    for item in batch["ingredients"]:
        inci = item["inci_name"]
        if inci not in OVERRIDE:
            continue
        ov = OVERRIDE[inci]
        if ov is None:
            if item.get("cir_conc_high") is not None or item.get("cir_conc_low") is not None:
                dropped += 1
            item["cir_conc_low"] = None
            item["cir_conc_high"] = None
            low = high = None
        else:
            low, high = ov
            if (item.get("cir_conc_low"), item.get("cir_conc_high")) != (low, high):
                fixed += 1
            item["cir_conc_low"] = low
            item["cir_conc_high"] = high
        # 断言措辞按最终浓度重新生成
        for a in item["assertions"]:
            eff = a["efficacy"]
            head = eff.split("（CIR 评估")[0]
            a["efficacy"] = f"{head}（CIR 评估{_conc_txt(low, high)}）"
            if NOTE_TAG not in a["note"]:
                a["note"] += NOTE_TAG
    BATCH.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
    n_conc = sum(1 for i in batch["ingredients"] if i.get("cir_conc_high") is not None)
    n_assert = sum(len(i["assertions"]) for i in batch["ingredients"])
    print(f"核订完成：修正 {fixed} 条、撤回 {dropped} 条；"
          f"最终 成分 {len(batch['ingredients'])}、断言 {n_assert}、浓度回填 {n_conc}")


if __name__ == "__main__":
    main()
