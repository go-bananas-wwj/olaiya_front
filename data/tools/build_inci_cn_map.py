"""由 IECIC 2021 提取产物生成 INCI→中文名映射 seed：data/seed/inci_cn_map.json。

输入：data/raw/iecic/iecic2021.json（extract_iecic_pdf.py 产物，8965 条官方记录）。
规则：
- 映射键为规范化 INCI（大写、压空白、弯引号归直引号）；loader 查表时用同一规范化。
- 同一 INCI 对应多条中文条目时（官方目录一 INCI 多名，共 6 个），取序号最小者，
  但 PEG-2 STEARATE 取「PEG-2 硬脂酸酯」（00876 条中文名 PPG-2 硬脂酸酯 与 INCI 不符，
  按 INCI 前缀一致的条目取值）；全部冲突记录在 conflicts_resolved 供人工复核。
- 官方未给 INCI 名的 30 条不参与映射。

运行：.venv/bin/python data/tools/build_inci_cn_map.py
"""

import json
import re
from pathlib import Path

RAW_JSON = Path(__file__).resolve().parents[1] / "raw" / "iecic" / "iecic2021.json"
SEED_OUT = Path(__file__).resolve().parents[1] / "seed" / "inci_cn_map.json"

_WS = re.compile(r"\s+")
# 官方目录一 INCI 多名时的人工裁定（值 = 选用的中文名所在条目序号）
OVERRIDES = {"PEG-2 STEARATE": "00566"}


def norm_inci(name: str) -> str:
    """INCI 查表键规范化：大写、压空白、弯引号归直引号。loader 必须复用本函数。"""
    return _WS.sub(" ", name.replace("’", "'").replace("‘", "'")).strip().upper()


def build(records: list[dict]) -> dict:
    groups: dict[str, list[dict]] = {}
    for r in records:
        if r["inci_name"]:
            groups.setdefault(norm_inci(r["inci_name"]), []).append(r)

    mapping: dict[str, dict] = {}
    conflicts: list[dict] = []
    for key, group in sorted(groups.items()):
        group = sorted(group, key=lambda r: r["serial"])
        chosen = group[0]
        if key in OVERRIDES:
            chosen = next(r for r in group if r["serial"] == OVERRIDES[key])
        if len({r["cn_name"] for r in group}) > 1:
            conflicts.append({
                "inci_name": key,
                "chosen": {"serial": chosen["serial"], "cn_name": chosen["cn_name"]},
                "candidates": [{"serial": r["serial"], "cn_name": r["cn_name"]} for r in group],
            })
        mapping[key] = {"cn_name": chosen["cn_name"], "iecic_serial": chosen["serial"]}
    return {"mapping": mapping, "conflicts": conflicts}


def main() -> None:
    records = json.loads(RAW_JSON.read_text(encoding="utf-8"))
    result = build(records)
    seed = {
        "source": {
            "name": "NMPA《已使用化妆品原料目录（2021年版）》",
            "announcement": "国家药监局关于发布《已使用化妆品原料目录（2021年版）》的公告（2021年第62号）",
            "announcement_url": "https://www.nmpa.gov.cn/xxgk/ggtg/hzhpggtg/jmhzhptg/20210430162707173.html",
            "pdf_url": "https://extract-resource.oss-cn-hangzhou.aliyuncs.com/mt_file/16636590854308.pdf",
            "raw_pdf": "data/raw/iecic/iecic2021.pdf",
            "extractor": "data/tools/extract_iecic_pdf.py → data/raw/iecic/iecic2021.json",
            "verification": (
                "2026-08-09 随机抽 30 条与中国食品药品检定研究院「已使用化妆品原料目录」"
                "在线库（https://hzpsys.nifdc.org.cn/hzpGS/ysyhzpylmla）逐条比对，"
                "中文名与 INCI 名全部一致；条目数 8965、编号至 08972（7 个空号为公告删除的"
                "重复原料），与公告口径一致。关键常识抽查：烟酰胺=NIACINAMIDE、甘油=GLYCERIN、"
                "苯氧乙醇=PHENOXYETHANOL、透明质酸钠=SODIUM HYALURONATE、水=WATER/AQUA。"
            ),
        },
        "conflicts_resolved": result["conflicts"],
        "map": result["mapping"],
    }
    SEED_OUT.write_text(json.dumps(seed, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"map={len(result['mapping'])} conflicts={len(result['conflicts'])} -> {SEED_OUT}")


if __name__ == "__main__":
    main()
