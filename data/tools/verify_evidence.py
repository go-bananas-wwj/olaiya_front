"""证据条目自动核验器：成分证据库入库前的质量闸门。

对每条 paper 类证据：从 URL 提取 PMID → 调 NCBI esummary → 比对标题（归一化 token 重合度）。
只有核验通过的条目才允许入库——这是「敢说真话、无幻觉」的机器保障。

用法：/root/workspace/olaiya/.venv/bin/python data/tools/verify_evidence.py 输入.json 通过.json 驳回.json
输入 JSON 结构：
{
  "ingredients": [
    {"cn_name": "...", "inci_name": "...", "cas_no": "...|null",
     "assertions": [
       {"efficacy": "...",
        "evidence": {"type": "paper|patent|regulation|white_paper", "title": "...",
                     "source": "...", "year": 2002, "url": "https://pubmed.ncbi.nlm.nih.gov/12100180/",
                     "excerpt": "..."},
        "effective_conc_low": 2.0, "effective_conc_high": 5.0, "note": "...|null"}
     ]}
  ]
}
"""

import json
import re
import sys
import time
import urllib.request

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={pmid}&retmode=json"
MATCH_THRESHOLD = 0.7   # token 重合度阈值
REQUEST_INTERVAL = 0.4  # NCBI 无 key 限速 3 req/s，保守取 2.5


def _norm_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def title_similarity(a: str, b: str) -> float:
    """Jaccard token 重合度（PubMed 标题与申报标题允许大小写/标点差异）。"""
    ta, tb = _norm_tokens(a), _norm_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def extract_pmid(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", url)
    return m.group(1) if m else None


def fetch_pubmed_title(pmid: str) -> str | None:
    url = EUTILS.format(pmid=pmid)
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["result"][pmid].get("title")
    except Exception:
        return None


def verify_entry(entry: dict) -> tuple[bool, str]:
    """核验单条断言。返回 (是否通过, 原因)。"""
    ev = entry.get("evidence") or {}
    etype = ev.get("type")
    if not ev.get("title") or not ev.get("url"):
        return False, "证据缺 title 或 url"
    if etype == "paper":
        pmid = extract_pmid(ev["url"])
        if not pmid:
            return False, "paper 类证据的 url 不含可解析的 PMID"
        real_title = fetch_pubmed_title(pmid)
        time.sleep(REQUEST_INTERVAL)
        if real_title is None:
            return False, f"PMID {pmid} 查询失败（网络或不存在）"
        sim = title_similarity(ev["title"], real_title)
        if sim < MATCH_THRESHOLD:
            return False, f"标题不匹配（相似度 {sim:.2f}）：申报「{ev['title'][:60]}」 vs PubMed「{real_title[:60]}」"
        return True, f"PMID {pmid} 标题匹配（相似度 {sim:.2f}）"
    # 非 paper 类（法规/专利/白皮书）：结构性校验（全文核验需人工）
    if etype not in ("patent", "regulation", "white_paper"):
        return False, f"未知证据类型 {etype!r}"
    if not ev["url"].startswith("http"):
        return False, "url 非法"
    return True, f"{etype} 类条目结构校验通过（内容需人工抽检）"


def main() -> None:
    src, ok_path, bad_path = sys.argv[1], sys.argv[2], sys.argv[3]
    data = json.loads(open(src, encoding="utf-8").read())
    ok_ingredients, rejected = [], []
    total = passed = 0
    for ing in data.get("ingredients", []):
        good_assertions = []
        for a in ing.get("assertions", []):
            total += 1
            ok, reason = verify_entry(a)
            if ok:
                passed += 1
                good_assertions.append(a)
            else:
                rejected.append({"ingredient": ing.get("cn_name"), "assertion": a.get("efficacy"),
                                 "reason": reason})
                print(f"  ✗ [{ing.get('cn_name')}] {a.get('efficacy')}: {reason}")
        if good_assertions:
            ok_ingredients.append({**ing, "assertions": good_assertions})
    json.dump({"ingredients": ok_ingredients}, open(ok_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump(rejected, open(bad_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n核验完成：{passed}/{total} 条通过，{total - passed} 条驳回 → {bad_path}")


if __name__ == "__main__":
    main()
