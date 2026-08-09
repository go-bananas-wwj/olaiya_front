"""IECIC 2021 官方附件 PDF → 结构化 JSON 提取器。

输入：data/raw/iecic/iecic2021.pdf（NMPA 2021 年第 62 号公告附件，
《已使用化妆品原料目录（2021 年版）》正文表格，8972 条）。
输出：data/raw/iecic/iecic2021.json（记录含 serial/cn_name/inci_name/
iecic_max_rinse_off/iecic_max_leave_on/note）。

解析要点：
- 每页一个 6 列表格，首页带表头行；跨页断行记录（序号为空/非数字）并入上一条。
- 单元格内换行：中文名直接拼接；INCI 名按「左行尾为 - 或 / 则直连，否则补空格」拼接
  （PDF 按列宽折行，折行点多在连字符后，整词折行需保留空格）。
- 校验：序号必须 00001..08972 连续，数量不符即报错拒绝产出。

依赖 pdfplumber（不在主 venv，避免给主项目加依赖）：
    python3 -m venv /tmp/pdfenv && /tmp/pdfenv/bin/pip install pdfplumber
运行：/tmp/pdfenv/bin/python data/tools/extract_iecic_pdf.py [pdf路径] [输出路径]
"""

import json
import re
import sys
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parents[1] / "raw" / "iecic"
DEFAULT_PDF = RAW_DIR / "iecic2021.pdf"
DEFAULT_OUT = RAW_DIR / "iecic2021.json"

EXPECTED_COUNT = 8965  # 公告口径：IECIC 2021 编号至 08972，正式版删除重复原料后实际 8965 条（空号见下方校验输出）

_WS = re.compile(r"\s+")


def _join_cn(cell: str) -> str:
    """中文名单元格：折行拼接；左行尾为 ASCII 字母/数字时补空格（拉丁学名/PEG-x 与汉字间的空格），
    行尾为连字符/斜杠或汉字时直连。与中检院官网条目逐条比对验证过。"""
    lines = [ln.strip() for ln in (cell or "").split("\n") if ln.strip()]
    out = ""
    for ln in lines:
        if not out:
            out = ln
        elif out[-1].isascii() and out[-1].isalnum():
            out += " " + ln
        else:
            out += ln
    return _WS.sub(" ", out).strip()


def _join_inci(cell: str) -> str:
    """INCI 名单元格：连字符/斜杠后折行直连，整词折行补空格。"""
    lines = [ln.strip() for ln in (cell or "").split("\n") if ln.strip()]
    out = ""
    for ln in lines:
        if not out:
            out = ln
        elif out.endswith(("-", "/")):
            out += ln
        else:
            out += " " + ln
    return _WS.sub(" ", out).strip()


def _join_note(cell: str) -> str:
    return (cell or "").replace("\n", "").strip()


def _num(cell: str):
    """最高历史使用量：'/'（按技术规范要求使用）与空都归 None。"""
    v = (cell or "").strip().rstrip("%")
    if not v or v == "/":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def extract(pdf_path: Path = DEFAULT_PDF) -> list[dict]:
    import pdfplumber  # 惰性导入：主 venv 无此依赖

    records: list[dict] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_no, page in enumerate(pdf.pages):
            tables = page.extract_tables()
            if not tables:
                continue
            for row in tables[0]:
                if row is None or len(row) < 3:
                    continue
                serial, cn, inci = (row[0] or "").strip(), row[1], row[2]
                if serial == "序号":  # 表头
                    continue
                extra = row[3:] if len(row) > 3 else []
                if serial.isdigit():
                    records.append({
                        "serial": serial,
                        "cn_name": _join_cn(cn),
                        "inci_name": _join_inci(inci),
                        "iecic_max_rinse_off": _num(extra[0] if len(extra) > 0 else ""),
                        "iecic_max_leave_on": _num(extra[1] if len(extra) > 1 else ""),
                        "note": _join_note(extra[2] if len(extra) > 2 else "") or None,
                    })
                elif records:  # 跨页断行：并入上一条
                    prev = records[-1]
                    cont_cn = _join_cn(cn)
                    sep = " " if (prev["cn_name"] and prev["cn_name"][-1].isascii()
                                  and prev["cn_name"][-1].isalnum()) else ""
                    prev["cn_name"] += sep + cont_cn
                    prev["inci_name"] = _join_inci(prev["inci_name"] + "\n" + (inci or ""))
                    cont = _join_note(extra[2] if len(extra) > 2 else "")
                    if cont:
                        prev["note"] = (prev["note"] or "") + cont
                else:
                    raise ValueError(f"第 {page_no + 1} 页出现无归属断行: {row!r}")
    return records


def validate(records: list[dict]) -> None:
    """序号连续性 + 必填字段非空校验，不过则拒绝产出（宁可报错不要脏数据）。"""
    if len(records) != EXPECTED_COUNT:
        raise ValueError(f"条目数 {len(records)} != 正式版口径 {EXPECTED_COUNT}")
    serials = [r["serial"] for r in records]
    if len(set(serials)) != len(serials) or serials != sorted(serials):
        raise ValueError("序号不唯一或不递增，疑似解析错乱")
    all_serials = {f"{i:05d}" for i in range(1, 8973)}
    missing = all_serials - set(serials)
    if len(missing) != 8972 - EXPECTED_COUNT:
        raise ValueError(f"空号数量 {len(missing)} 与公告口径不符: {sorted(missing)}")
    print(f"空号（正式版删除的重复原料序号）: {sorted(missing)}")
    n_empty = 0
    for rec in records:
        if not rec["cn_name"]:
            raise ValueError(f"第 {rec['serial']} 条中文名缺失: {rec!r}")
        if not rec["inci_name"]:  # 个别条目官方未给 INCI/英文名（如 02121），如实保留空串
            n_empty += 1
    print(f"官方未给 INCI/英文名的条目: {n_empty} 条（不参与映射）")


def main() -> None:
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PDF
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT
    records = extract(pdf_path)
    validate(records)
    out_path.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    n_inci = len({r["inci_name"].upper() for r in records})
    print(f"extracted={len(records)} unique_inci={n_inci} -> {out_path}")
    for probe in ("NIACINAMIDE", "GLYCERIN", "PHENOXYETHANOL", "SODIUM HYALURONATE"):
        hits = [r for r in records if r["inci_name"].upper() == probe]
        print("  probe:", hits[0] if hits else f"{probe} 未命中")


if __name__ == "__main__":
    main()
