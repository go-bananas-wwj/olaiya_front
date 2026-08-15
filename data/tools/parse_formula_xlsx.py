"""基础配方库 xlsx 解析器：19 个剂型的真实配方 → 成分典型用量 JSON。

数据源：欧莱雅比赛/基础础配方库+原料库（快速认识原料及上手操作）/
基础配方库（了解各种剂型配方设计原理）.xlsx —— 配方实践数据（每个 sheet 一个剂型的
若干配方实例，列为 相/序号/原料名称/INCI名/比例%/使用目的）。

数据性质：**配方实践典型用量**，非官方限值、非功效起效浓度 —— 入库落
ingredients.typical_use_low/high（formula_loader），只作展示参考。

解析规则：比例% 列取数值（区间「0.5-1.0」取两端，单值两端同值）；无法解析的行跳过
并计数（不猜）。每行产出 {formulation(剂型), inci_name, pct_low, pct_high, purpose}。

产物：data/research/formula_typical_dose.json；原始 xlsx 在 欧莱雅比赛/（git 忽略）
运行：.venv/bin/python data/tools/parse_formula_xlsx.py [--xlsx 路径] [--out 路径]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import openpyxl

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_XLSX = (REPO_ROOT / "欧莱雅比赛"
                / "基础础配方库+原料库（快速认识原料及上手操作）"
                / "基础配方库（了解各种剂型配方设计原理）.xlsx")
DEFAULT_OUT = REPO_ROOT / "data" / "research" / "formula_typical_dose.json"

_NUM = re.compile(r"(\d+(?:\.\d+)?)")


def parse_pct(text: str) -> tuple[float, float] | None:
    """「0.5-1.0」→(0.5, 1.0)；「3」→(3.0, 3.0)；Excel 公式/无法解析 → None（不猜）。"""
    text = str(text)
    if "=" in text:  # Excel 公式（read_only 无缓存值时拿到的是公式串），不猜
        return None
    nums = _NUM.findall(text)
    if not nums:
        return None
    if len(nums) == 1:
        v = float(nums[0])
        return (v, v)
    # 多个数字取前两个作区间（「1-3，最大5」这类混合文本会丢第三个数——
    # 配方表比例列实测无此形态；保守取舍，宁丢不多猜）
    lo, hi = float(nums[0]), float(nums[1])
    return (min(lo, hi), max(lo, hi))


def parse_xlsx(xlsx_path: str | Path) -> dict:
    wb = openpyxl.load_workbook(str(xlsx_path), read_only=True)
    records: list[dict] = []
    sheet_stats: dict[str, dict] = {}
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        # 表头行含「INCI名」与「比例%」；找不到的 sheet 整表跳过
        header_idx = None
        for i, row in enumerate(rows[:5]):
            cells = [str(c).strip() if c is not None else "" for c in row]
            if "INCI名" in cells and any("比例" in c for c in cells):
                header_idx = i
                header = cells
                break
        if header_idx is None:
            sheet_stats[ws.title] = {"records": 0, "skipped": len(rows),
                                     "note": "表头未识别"}
            continue
        ci = header.index("INCI名")
        cp = next(i for i, c in enumerate(header) if "比例" in c)
        cu = next((i for i, c in enumerate(header) if "使用目的" in c), None)
        n, skipped = 0, 0
        for row in rows[header_idx + 1:]:
            cells = [c if c is not None else "" for c in row]
            inci = str(cells[ci]).strip() if ci < len(cells) else ""
            pct_raw = str(cells[cp]).strip() if cp < len(cells) else ""
            if not inci or "=" in inci:  # Excel 公式串不是成分名，跳过不猜（计入 skipped 留痕）
                skipped += 1
                continue
            pct = parse_pct(pct_raw)
            if pct is None:
                skipped += 1
                continue
            records.append({
                "formulation": ws.title, "inci_name": inci,
                "pct_low": pct[0], "pct_high": pct[1],
                "purpose": str(cells[cu]).strip()
                if cu is not None and cu < len(cells) else "",
            })
            n += 1
        sheet_stats[ws.title] = {"records": n, "skipped": skipped}
    return {
        "source": {
            "file": str(xlsx_path),
            "nature": "配方实践典型用量（配方实例），非官方限值、非功效起效浓度",
        },
        "stats": {"total_records": len(records), "by_sheet": sheet_stats},
        "records": records,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--xlsx", default=str(DEFAULT_XLSX))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    data = parse_xlsx(args.xlsx)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(f"共 {data['stats']['total_records']} 条配方用量记录 → {args.out}")
    for name, st in data["stats"]["by_sheet"].items():
        print(f"  {name:16s} records={st['records']:3d} skipped={st['skipped']}")


if __name__ == "__main__":
    main()
