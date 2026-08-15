"""流式扫描版 PDF OCR（草稿，选型验证版）。

用法：
    .venv/bin/python data/tools/ocr_pdfs.py PDF [PDF ...] \
        --pages 1-20,50,100-105 --out data/raw/ocr/out.jsonl [--dpi 250]

行为：
- 逐页渲染 → OCR → 立即丢弃位图，图片不落盘（内存流式处理）。
- 每页一行 JSONL：{"pdf": ..., "page": ..., "text": ..., "ocr_ms": ...}，追加写。
- --pages 支持逗号分隔的页码/区间（1-based，含端点）；缺省为全部页。
- 断点续跑：输出文件已存在的 (pdf, page) 自动跳过。

依赖：PyMuPDF（fitz）渲染、rapidocr-onnxruntime（PP-OCRv4 ONNX，纯 CPU）。
注意：rapidocr 引擎全局只初始化一次（模型加载有开销）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
from rapidocr_onnxruntime import RapidOCR


def parse_pages(spec: str, total: int) -> list[int]:
    """'1-20,50,100-105' -> 排序去重的 1-based 页码列表，越界裁剪。"""
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            pages.update(range(int(a), int(b) + 1))
        else:
            pages.add(int(part))
    return sorted(p for p in pages if 1 <= p <= total)


def load_done(out_path: Path) -> set[tuple[str, int]]:
    done: set[tuple[str, int]] = set()
    if out_path.exists():
        with out_path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    done.add((rec["pdf"], rec["page"]))
                except Exception:
                    continue
    return done


def ocr_pdf(pdf_path: str, pages: list[int], engine: RapidOCR, out_fh, dpi: int) -> None:
    doc = fitz.open(pdf_path)
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    for pno in pages:
        page = doc[pno - 1]
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB, alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        t0 = time.perf_counter()
        result, _ = engine(img)
        ocr_ms = int((time.perf_counter() - t0) * 1000)
        # result: list[[box, text, score]] 或 None；按阅读顺序拼接
        text = "\n".join(line[1] for line in result) if result else ""
        out_fh.write(json.dumps(
            {"pdf": pdf_path, "page": pno, "text": text, "ocr_ms": ocr_ms},
            ensure_ascii=False,
        ) + "\n")
        out_fh.flush()
        del img, pix  # 位图只活在内存，立即释放
    doc.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdfs", nargs="+", help="PDF 文件路径")
    ap.add_argument("--pages", default=None, help="页码范围，如 1-20,50,100-105（1-based，缺省全部）")
    ap.add_argument("--out", required=True, help="输出 JSONL 路径（追加写，支持断点续跑）")
    ap.add_argument("--dpi", type=int, default=250, help="渲染 DPI（200-300 之间质量/速度折中）")
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = load_done(out_path)

    t0 = time.perf_counter()
    engine = RapidOCR()  # 模型只加载一次
    print(f"[init] RapidOCR loaded in {time.perf_counter() - t0:.1f}s", file=sys.stderr)

    with out_path.open("a", encoding="utf-8") as out_fh:
        for pdf_path in args.pdfs:
            with fitz.open(pdf_path) as probe:
                total = probe.page_count
            pages = parse_pages(args.pages, total) if args.pages else list(range(1, total + 1))
            todo = [p for p in pages if (pdf_path, p) not in done]
            print(f"[run] {pdf_path}: {len(todo)}/{len(pages)} pages todo", file=sys.stderr)
            ocr_pdf(pdf_path, todo, engine, out_fh, args.dpi)


if __name__ == "__main__":
    main()
