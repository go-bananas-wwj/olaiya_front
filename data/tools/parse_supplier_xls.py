"""供应商原料库 xls 解析器：欧莱雅比赛/原料库/原料库（认识原料性能及作用）.xls → 结构化 JSON。

数据性质：原料商产品资料（供应商卖原料的手册），功效文本为**供应商宣称**，
未经同行评议 —— 入库走降级通道（supplier_loader），本工具只做忠实解析，不做功效断言加工。

解析规则：
- 每个 sheet 是一个原料类别（乳化剂/功效性活性成分/植物类提取物…），表头行 0，
  按表头关键词定位列：INCI英文名 / INCI中文名 / 功效|性能 / 类别 / 生产商 / 用量列
- 复配行（INCI 含「、」分隔多组分）拆成 components 列表，loader 侧逐组分匹配；
  功效指向复配整体的语义由 loader 在 note 里如实注明
- 无 功效/性能 列的 sheet（水溶色素类/粉剂类）仍解析（商品名→INCI 映射有价值），
  function_text 为空，loader 只登记映射不建断言
- 空表/兼容性报表 sheet 跳过

产物：data/research/supplier_ingredients.json（机验后入库；原始 xls 在 欧莱雅比赛/，git 忽略）
运行：.venv/bin/python data/tools/parse_supplier_xls.py [--xls 路径] [--out 路径]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import xlrd

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_XLS = REPO_ROOT / "欧莱雅比赛" / "原料库" / "原料库（认识原料性能及作用）.xls"
DEFAULT_OUT = REPO_ROOT / "data" / "research" / "supplier_ingredients.json"

SKIP_SHEETS = {"Sheet1", "兼容性报表"}

# 列定位关键词（各 sheet 表头写法不一，按包含匹配）
_COL_KEYS = {
    "product_name": ("产品名称", "Product"),
    "inci_en": ("INCI英文名", "INCI英文"),
    "inci_cn": ("INCI中文名", "INCI中文"),
    "category": ("类型", "类别"),
    "producer": ("生产商",),
    "dosage": ("推荐用量", "最大用量"),
    "legal_limit": ("限用量",),
}
_FUNCTION_KEYS = ("功效", "性能")  # 功效优先，性能兜底（不同 sheet 用词不同）

_SPLIT = re.compile(r"[、，,；;]")  # 复配组分分隔符
_ASCII_LETTER = re.compile(r"[A-Za-z]")


def _find_col(header: list[str], keys: tuple[str, ...]) -> int | None:
    for c, h in enumerate(header):
        if any(k in h for k in keys):
            return c
    return None


def split_components(inci_en: str) -> list[str]:
    """复配拆分：按 、，,；； 分隔，只保留含拉丁字母的组分（防中文描述混入）。"""
    parts = [p.strip() for p in _SPLIT.split(inci_en) if p.strip()]
    return [p for p in parts if _ASCII_LETTER.search(p)]


def parse_xls(xls_path: str | Path) -> dict:
    wb = xlrd.open_workbook(str(xls_path))
    records: list[dict] = []
    sheet_stats: dict[str, dict] = {}
    for sheet in wb.sheets():
        if sheet.name in SKIP_SHEETS or sheet.nrows < 2:
            continue
        header = [str(sheet.cell_value(0, c)).replace("\n", "").strip()
                  for c in range(sheet.ncols)]
        cols = {k: _find_col(header, keys) for k, keys in _COL_KEYS.items()}
        # 功效列优先「功效」，无则「性能」
        func_col = _find_col(header, ("功效",))
        if func_col is None:
            func_col = _find_col(header, ("性能",))
        n = 0
        for r in range(1, sheet.nrows):
            def cell(key, _r=r):
                c = cols.get(key)
                if c is None or c >= sheet.ncols:
                    return ""
                return str(sheet.cell_value(_r, c)).strip()

            func_text = (str(sheet.cell_value(r, func_col)).strip()
                         if func_col is not None and func_col < sheet.ncols else "")
            rec = {
                "sheet": sheet.name,
                "product_name": cell("product_name"),
                "inci_en": cell("inci_en"),
                "inci_cn": cell("inci_cn"),
                "function_text": func_text,
                "category": cell("category"),
                "producer": cell("producer"),
                "dosage": cell("dosage"),
                "legal_limit": cell("legal_limit"),
                "components": split_components(cell("inci_en")),
            }
            # 全空行跳过（商品名和 INCI 都空的行无信息）
            if not (rec["product_name"] or rec["inci_en"] or rec["inci_cn"]):
                continue
            records.append(rec)
            n += 1
        with_func = sum(1 for rec in records if rec["sheet"] == sheet.name
                        and rec["function_text"])
        sheet_stats[sheet.name] = {"rows": n, "with_function_text": with_func}

    return {
        "source": {
            "file": str(xls_path),
            "nature": "原料商产品资料（供应商手册），功效文本为供应商宣称，未经同行评议",
            "note": "入库走 supplier 降级通道（supplier_loader）：措辞保守、强制 unknown",
        },
        "stats": {"total_records": len(records), "by_sheet": sheet_stats},
        "records": records,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--xls", default=str(DEFAULT_XLS))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    data = parse_xls(args.xls)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(f"共 {data['stats']['total_records']} 条记录 → {args.out}")
    for name, st in data["stats"]["by_sheet"].items():
        print(f"  {name:12s} rows={st['rows']:4d} 有功效文本={st['with_function_text']:4d}")


if __name__ == "__main__":
    main()
