"""化妆品原料手册(新) 双栏重排：按行级包围盒还原双栏 OCR 的阅读顺序。

用法：
    .venv/bin/python data/tools/reorder_shouce.py \
        --inp data/raw/ocr/shouce_boxed.jsonl --out /tmp/shouce_reordered.jsonl [--pages 150,211,300]

输入：ocr_pdfs.py --boxes 产物（每页一行 {"pdf","page","width","height","lines":[{box,text,score}]}）。
规则：
- 丢弃水印行（化妆品技术在线 / HzpOnline）与页脚页码行（页底 20% 内的纯数字短行）。
- 整宽行（包围盒横跨中缝，如章节标题「第二节 香料与香精」）作为分带边界：
  带内先左栏后右栏，带与整宽行按 y 顺序交错输出（带上内容 → 整宽行 → 带下内容）。
- 栏判定：行中心 x < 页宽一半 → 左栏，否则右栏。
- 栏内按视觉行聚合：垂直中心差 ≤ 0.6×行高中位数的 box 并入同一行，行内按 x 拼接文本
  （OCR 常把「用途」标签与同行内容拆成两个 box，不拼会破坏字段关键字检测）；
  行间按 y 排序。
- 输出 JSONL 每页一行：{"pdf","page","width","height","text","lines":[{text,col,box}]}，
  text 为重排后行文本 \\n 连接；lines 保留合并后包围盒与栏标记（col ∈ L/R/W）供下游校验。

幂等：整体覆盖写输出文件；--pages 只处理指定页（1-based）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

WATERMARK_RE = re.compile(r"(HzpOnline|化妆品\s*技术\s*在线)", re.I)
FOOTER_PAGE_RE = re.compile(r"\d{1,4}")
# 中缝容差（px，250DPI 版面）：box 左缘在中线左侧且右缘在中线右侧各超过该值才算整宽行
GUTTER_PX = 60
# 页脚判定：行顶 y 超过页高该比例且是纯数字短行 → 页码，丢弃
FOOTER_Y_FRAC = 0.80
# 视觉行聚合阈值：垂直中心差 ≤ 行高中位数 × 该系数 → 同一行
ROW_MERGE_FRAC = 0.6


def _box_xy(box: list) -> tuple[float, float, float, float]:
    (x0, y0), (_, _), (x1, y1), (_, _) = box[0], box[1], box[2], box[3]
    return float(x0), float(y0), float(x1), float(y1)


def filter_lines(lines: list[dict], width: float, height: float) -> list[dict]:
    """去水印/页脚/空行，并标注整宽行与栏归属。"""
    kept = []
    mid = width / 2
    for ln in lines:
        text = (ln.get("text") or "").strip()
        if not text or WATERMARK_RE.search(text):
            continue
        x0, y0, x1, y1 = _box_xy(ln["box"])
        if FOOTER_PAGE_RE.fullmatch(text) and y0 > FOOTER_Y_FRAC * height:
            continue
        full = (x0 < mid - GUTTER_PX) and (x1 > mid + GUTTER_PX)
        kept.append({
            "text": text,
            "box": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
            "cy": (y0 + y1) / 2,
            "h": y1 - y0,
            "full": full,
            "col": "W" if full else ("L" if (x0 + x1) / 2 < mid else "R"),
        })
    return kept


def merge_rows(lines: list[dict]) -> list[dict]:
    """同一栏（或整宽流）内按视觉行聚合并按 x 拼接；行间按 y 排序。"""
    if not lines:
        return []
    heights = sorted(ln["h"] for ln in lines)
    h_med = heights[len(heights) // 2] or 1.0
    rows: list[dict] = []
    for ln in sorted(lines, key=lambda l: (l["cy"], l["box"][0][0])):
        if rows and abs(ln["cy"] - rows[-1]["cy"]) <= ROW_MERGE_FRAC * h_med:
            rows[-1]["items"].append(ln)
            # 行中心取成员均值，避免单行高 box 带偏聚合基准
            rows[-1]["cy"] = sum(i["cy"] for i in rows[-1]["items"]) / len(rows[-1]["items"])
        else:
            rows.append({"cy": ln["cy"], "items": [ln]})
    out = []
    for row in rows:
        items = sorted(row["items"], key=lambda l: l["box"][0][0])
        xs0 = [i["box"][0][0] for i in items]
        ys0 = [i["box"][0][1] for i in items]
        xs1 = [i["box"][2][0] for i in items]
        ys1 = [i["box"][2][1] for i in items]
        x0, y0, x1, y1 = min(xs0), min(ys0), max(xs1), max(ys1)
        out.append({
            "text": "".join(i["text"] for i in items),
            "col": items[0]["col"],
            "box": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
        })
    return out


def reorder_page(rec: dict) -> dict:
    """整宽行分带，带内左栏整体在前、右栏在后，整宽行按 y 交错。"""
    width, height = float(rec["width"]), float(rec["height"])
    kept = filter_lines(rec.get("lines") or [], width, height)
    fulls = sorted((l for l in kept if l["full"]), key=lambda l: l["cy"])
    cols = [l for l in kept if not l["full"]]

    def band_of(ln: dict) -> int:
        return sum(1 for f in fulls if f["cy"] < ln["cy"])

    bands: dict[int, list[dict]] = {}
    for ln in cols:
        bands.setdefault(band_of(ln), []).append(ln)

    out_lines: list[dict] = []
    for k in range(len(fulls) + 1):
        band = bands.get(k, [])
        out_lines.extend(merge_rows([l for l in band if l["col"] == "L"]))
        out_lines.extend(merge_rows([l for l in band if l["col"] == "R"]))
        if k < len(fulls):
            out_lines.extend(merge_rows([fulls[k]]))

    return {
        "pdf": rec["pdf"],
        "page": rec["page"],
        "width": rec["width"],
        "height": rec["height"],
        "text": "\n".join(l["text"] for l in out_lines),
        "lines": out_lines,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="化妆品原料手册(新) 双栏重排")
    ap.add_argument("--inp", default="data/raw/ocr/shouce_boxed.jsonl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--pages", default="", help="只处理指定页，如 150,211,300；缺省全部")
    args = ap.parse_args()

    page_filter = {int(p) for p in args.pages.split(",") if p.strip()} or None
    n_in = n_out = 0
    with open(args.inp, encoding="utf-8") as f, \
            open(args.out, "w", encoding="utf-8") as out:
        for line in f:
            rec = json.loads(line)
            n_in += 1
            if page_filter and rec["page"] not in page_filter:
                continue
            out.write(json.dumps(reorder_page(rec), ensure_ascii=False) + "\n")
            n_out += 1
    print(f"reorder: {n_in} pages in, {n_out} pages out -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
