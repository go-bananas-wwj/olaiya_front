"""SCCS（欧委会消费者安全科学委员会）意见 PDF 采集器。

来源（health.ec.europa.eu，免费，无需登录；礼貌延时默认 4s，429/5xx 冷却熔断）：
- 现行意见页 sccs-opinions_en（2022+，出版物 slug）
- 存档页 2016-2021（出版物 slug）
- 存档页 2013-2016（出版物 slug）
- 存档页 2009-2013（直链 /document/download/...pdf，锚文本即标题）

流程：列表页 → 关键词命中目标成分 → 出版物页取 PDF 直链 → 下载 PDF →
抽取「意见结论」候选句（含 safe/not safe/% 的结论段）→ data/raw/sccs/extraction.json。
结论数值一律由人工对照 PDF 原文核订后写进 data/seed/sccs_opinions.json，
本脚本不自动定值（数据铁律：拿不准不猜）。

用法：/tmp/pdfenv/bin/python data/tools/collect_sccs.py [--delay 4]
"""

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "sccs"
PDF_DIR = RAW / "pdf"
BASE = "https://health.ec.europa.eu"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

LISTING_PAGES = {
    "2022plus": "/scientific-committees/scientific-committee-consumer-safety-sccs/sccs-opinions_en",
    "2016-2021": "/scientific-committees/former-scientific-committees/scientific-committee-consumer-safety-2016-2021/sccs-opinions-2016-2021_en",
    "2013-2016": "/scientific-committees/former-scientific-committees/scientific-committee-consumer-safety-sccs-2013-2016/sccs-opinions-2013-2016_en",
    "2009-2013": "/scientific-committees/former-scientific-committees/scientific-committee-consumer-safety-sccs-2009-2013/sccs-opinions-april-2009-march-2013_en",
}

# 目标成分（库内高风险成分）→ 标题/slug 命中关键词（小写子串，全部命中其一即收）
TARGETS: dict[str, list[str]] = {
    "ALPHA-ARBUTIN": ["alpha-arbutin", "α-arbutin", "alpha arbutin"],
    "ARBUTIN": ["arbutin"],  # b-arbutin 页也收，人工分辨 α/β
    "KOJIC ACID": ["kojic"],
    "HOMOSALATE": ["homosalate"],
    "OCTOCRYLENE": ["octocrylene"],
    "ETHYLHEXYL METHOXYCINNAMATE": ["ethylhexyl methoxycinnamate", "ehmc"],
    "BENZOPHENONE-1": ["benzophenone-1"],
    "BENZOPHENONE-3": ["benzophenone-3"],
    "BENZOPHENONE-5": ["benzophenone-5", "bp-5"],
    "TITANIUM DIOXIDE": ["titanium dioxide"],
    "ZINC OXIDE": ["zinc oxide"],
    "METHYLENE BIS-BENZOTRIAZOLYL TETRAMETHYLBUTYLPHENOL": ["methylene bis", "methylene-bis-(6-(2h-benzotriazol"],
    "DIETHYLAMINO HYDROXYBENZOYL HEXYL BENZOATE": ["diethylamino hydroxybenzoyl hexyl benzoate", "dhhb"],
    "BUTYLPARABEN": ["butylparaben"],
    "PROPYLPARABEN": ["propylparaben", "propyl- and butylparaben", "propyl and butylparaben"],
    "METHYLPARABEN": ["methylparaben"],
    "ETHYLPARABEN": ["ethylparaben"],
    "TRICLOSAN": ["triclosan"],
    "PIROCTONE OLAMINE": ["piroctone"],
    "METHYLISOTHIAZOLINONE": ["methylisothiazolinone"],
    "SALICYLIC ACID": ["salicylic acid"],
    "RETINOL": ["retinol"],
    "CITRAL": ["citral"],
    "BUTYLPHENYL METHYLPROPIONAL": ["butylphenyl methylpropional", "p-bmhca"],
    "HYDROXYISOHEXYL 3-CYCLOHEXENE CARBOXALDEHYDE": ["hydroxyisohexyl"],
    "BENZYL SALICYLATE": ["benzyl salicylate"],
    "TOLUENE-2,5-DIAMINE": ["toluene-2,5-diamine"],
    "P-PHENYLENEDIAMINE": ["p-phenylenediamine"],
    "RESORCINOL": ["resorcinol"],
    "M-AMINOPHENOL": ["m-aminophenol"],
    "PHENOXYETHANOL": ["phenoxyethanol"],
    "BHT": ["butylated hydroxytoluene", "bht"],
    "DIHYDROXYACETONE": ["dihydroxyacetone", "dha"],
    "ZINC PYRITHIONE": ["zinc pyrithione", "zpt"],
}

_fails = 0


def fetch(url: str, delay: float, retries: int = 2) -> bytes:
    global _fails
    time.sleep(delay)
    last = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                data = r.read()
            _fails = 0
            return data
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504):
                print(f"  限流/服务错误 {e.code}，冷却 60s", flush=True)
                time.sleep(60)
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            time.sleep(20)
    _fails += 1
    if _fails >= 3:
        raise RuntimeError(f"熔断：连续 {_fails} 次失败（{last}）")
    raise RuntimeError(f"请求失败 {url}: {last}")


def parse_listing(html_text: str, page_key: str) -> list[dict]:
    """从列表页抽 (title, url, kind)。kind: pdf 直链 / pub 出版物页。"""
    out = []
    # 直链 PDF（2009-2013 存档页）：<a href="/document/download/...pdf">标题</a>
    for m in re.finditer(r'<a href="(/document/download/[^"]+\.pdf[^"]*)">([^<]+)</a>',
                         html_text):
        url, title = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
        if "biblio" in url:
            continue
        out.append({"title": title, "url": BASE + url, "kind": "pdf", "from": page_key})
    # 出版物 slug 页
    for m in re.finditer(r'<a href="(/publications/[^"]+_en)"[^>]*>(.*?)</a>',
                         html_text, re.S):
        url, title = m.group(1), re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(2))).strip()
        out.append({"title": title or url.rsplit("/", 1)[-1], "url": BASE + url,
                    "kind": "pub", "from": page_key})
    return out


def match_targets(cands: list[dict]) -> dict[str, list[dict]]:
    hits: dict[str, list[dict]] = {}
    for inci, kws in TARGETS.items():
        for c in cands:
            hay = (c["title"] + " " + c["url"]).lower()
            if any(k in hay for k in kws):
                hits.setdefault(inci, []).append(c)
    return hits


def pub_page_pdf(url: str, delay: float) -> tuple[str | None, str | None]:
    """出版物页 → (PDF 直链, 采用日期文本)。"""
    page = fetch(url, delay).decode("utf-8", "ignore")
    m = re.search(r'href="(/document/download/[^"]+\.pdf[^"]*)"', page)
    date = None
    dm = re.search(r"(\d{1,2}\s+[A-Z][a-z]+\s+\d{4})", page)
    if dm:
        date = dm.group(1)
    return (BASE + m.group(1) if m else None), date


def extract_opinion_sentences(pdf_path: Path) -> dict:
    """抽取结论候选：OPINION/结论段中含 safe/% 的句子 + 采用信息。供人工核订。"""
    import pdfplumber
    pages = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for p in pdf.pages[:12]:
            pages.append(p.extract_text() or "")
    text = "\n".join(pages)
    text = re.sub(r"[ \t]+", " ", text)
    # 结论区：优先 "OPINION" 标题之后
    m = re.search(r"(?im)^\s*OPINION\s*$", text)
    region = text[m.start():m.start() + 9000] if m else text[:9000]
    sents = re.split(r"(?<=[.!?])\s+", region)
    keep = [s.strip() for s in sents
            if re.search(r"safe|unsafe|risk", s, re.I)
            and re.search(r"%|concentration|not considered|cannot", s)]
    meta = re.search(r"SCCS/\d{4}/\d{2}", text)
    return {"opinion_no": meta.group(0) if meta else None,
            "sentences": [re.sub(r"\s+", " ", s)[:600] for s in keep[:12]]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--delay", type=float, default=4.0)
    ap.add_argument("--parse-only", action="store_true")
    args = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    cands: list[dict] = []
    for key, path in LISTING_PAGES.items():
        cache = RAW / f"listing_{key}.html"
        if cache.exists():
            html_text = cache.read_text(encoding="utf-8")
        else:
            html_text = fetch(BASE + path, args.delay).decode("utf-8", "ignore")
            cache.write_text(html_text, encoding="utf-8")
        got = parse_listing(html_text, key)
        print(f"列表页 {key}: {len(got)} 候选", flush=True)
        cands.extend(got)

    hits = match_targets(cands)
    print(f"\n命中成分 {len(hits)}/{len(TARGETS)}")
    for inci, items in hits.items():
        for it in items:
            print(f"  {inci} <- [{it['from']}] {it['title'][:70]} | {it['url'][-60:]}")
    (RAW / "hits.json").write_text(json.dumps(hits, ensure_ascii=False, indent=1),
                                   encoding="utf-8")

    if args.parse_only:
        return

    # 解析出版物页 → PDF 直链；下载 PDF
    pdfs: list[dict] = []
    seen_pdf = set()
    for inci, items in hits.items():
        for it in items:
            pdf_url, adopted = None, None
            if it["kind"] == "pdf":
                pdf_url = it["url"]
            else:
                pdf_url, adopted = pub_page_pdf(it["url"], args.delay)
                if not pdf_url:
                    print(f"  ⚠ 出版物页无 PDF：{it['url']}", flush=True)
                    continue
            if pdf_url in seen_pdf:
                pdfs.append({**it, "inci": inci, "pdf_url": pdf_url, "adopted": adopted})
                continue
            seen_pdf.add(pdf_url)
            name = pdf_url.split("filename=")[-1] or pdf_url.rsplit("/", 1)[-1]
            local = PDF_DIR / re.sub(r"[^A-Za-z0-9_.-]", "_", name)
            if not local.exists():
                local.write_bytes(fetch(pdf_url, args.delay))
                print(f"  下载 {name} {local.stat().st_size // 1024}KB", flush=True)
            pdfs.append({**it, "inci": inci, "pdf_url": pdf_url, "adopted": adopted,
                         "local": str(local)})
    (RAW / "pdfs.json").write_text(json.dumps(pdfs, ensure_ascii=False, indent=1),
                                   encoding="utf-8")

    # 抽取结论候选句
    extraction = {}
    done = set()
    for rec in pdfs:
        local = rec.get("local")
        if not local or local in done or not Path(local).exists():
            continue
        done.add(local)
        try:
            extraction[local] = extract_opinion_sentences(Path(local))
        except Exception as e:
            print(f"  ⚠ 解析失败 {local}: {e}", flush=True)
    (RAW / "extraction.json").write_text(json.dumps(extraction, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    print(f"\n抽取完成：{len(extraction)} 份 PDF → {RAW / 'extraction.json'}", flush=True)


if __name__ == "__main__":
    main()
