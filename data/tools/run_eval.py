"""域内评测跑分器：对评测集逐条调 /api/chat，按 verdict∧evidence∧dose 三条件计分。

计分口径（总纲评测指标本体，逐条 0/1，汇总取平均）：
- E（evidence 引用正确）：citations_used 命中 gold.must_cite_pmid 对应的证据包编号
  （PMID 经证据包文本内嵌的 PubMed URL 反查编号）；拒答类不允许引用任何编号。
- V（verdict 判定正确）：核验类看 verification 全部 supported 且 final_answer 无 ⚠️；
  拒答类看最终答案是否含「证据不足」语义（REFUSAL_KEYWORDS）。
- D（dose 剂量引用）：答案提到浓度（数字% 或「浓度」）时必须带估计/文献限定语义
  （DOSE_QUALIFIERS）；未提浓度为真空通过。
- 单条 total = E×V×D（三条件同时满足才算 1）；汇总 {n, E, V, D, total} 为逐条平均。

用法（web 服务在线时，见 AGENTS.md 的 tmux 启动命令）：
  .venv/bin/python data/tools/run_eval.py                      # 全量 40 条
  .venv/bin/python data/tools/run_eval.py --limit 2            # 冒烟
输出 data/eval/report.json（逐条明细 + 汇总）并打印汇总表。
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
from pathlib import Path

# 「证据不足」语义关键词（拒答类 V 条件）
REFUSAL_KEYWORDS = ("证据不足", "无法判定", "无法确定", "缺乏证据", "没有证据", "未检索到")
# 浓度表述的估计/文献限定语义（D 条件）
DOSE_QUALIFIERS = ("估计", "文献", "实验中", "研究浓度")
# 提到浓度：数字百分数或「浓度」字样
_DOSE_RE = re.compile(r"\d+(?:\.\d+)?\s*%|浓度")


def pmid_pack_ids(evidence_pack: list[dict], pmids: list[str]) -> set[int]:
    """PMID → 证据包编号：包条目文本内嵌 PubMed URL，子串命中即对应。"""
    ids: set[int] = set()
    for it in evidence_pack:
        text = it.get("text", "")
        for p in pmids:
            if p and p in text:
                ids.add(it["id"])
    return ids


def _final_text(result: dict) -> str:
    """最终答案文本：有校验循环产物取 final_answer，否则取原 answer。"""
    v = result.get("verification") or {}
    return v.get("final_answer") or result.get("answer") or ""


def score_evidence(gold: dict, result: dict) -> int:
    """E：核验类看 must_cite_pmid 是否被引；拒答类不引用任何编号才算干净。"""
    pmids = gold.get("must_cite_pmid") or []
    citations = set(result.get("citations_used") or [])
    if not pmids:
        return 1 if not citations else 0
    hit = citations & pmid_pack_ids(result.get("evidence_pack") or [], pmids)
    return 1 if hit else 0


def score_verdict(gold: dict, result: dict) -> int:
    """V：拒答类看「证据不足」语义；核验类看全部 supported 且无 ⚠️。"""
    if gold.get("expect_refusal"):
        return 1 if any(k in _final_text(result) for k in REFUSAL_KEYWORDS) else 0
    v = result.get("verification")
    if not v:
        return 0
    checks = v.get("verification") or []
    final = v.get("final_answer") or ""
    return 1 if all(c.get("supported") for c in checks) and "⚠️" not in final else 0


def score_dose(gold: dict, result: dict) -> int:
    """D：提到浓度时必须带估计/文献限定语义；未提浓度真空通过。"""
    text = _final_text(result)
    if not _DOSE_RE.search(text):
        return 1
    return 1 if any(k in text for k in DOSE_QUALIFIERS) else 0


def score_item(item: dict, result: dict) -> dict:
    """单条三条件计分：total = E×V×D。"""
    gold = item["gold"]
    e = score_evidence(gold, result)
    v = score_verdict(gold, result)
    d = score_dose(gold, result)
    return {"E": e, "V": v, "D": d, "total": e * v * d}


def summarize(details: list[dict]) -> dict:
    """汇总 {n, E, V, D, total}：逐条 0/1 的平均。"""
    n = len(details)
    if n == 0:
        return {"n": 0, "E": 0.0, "V": 0.0, "D": 0.0, "total": 0.0}
    return {
        "n": n,
        "E": sum(d["E"] for d in details) / n,
        "V": sum(d["V"] for d in details) / n,
        "D": sum(d["D"] for d in details) / n,
        "total": sum(d["total"] for d in details) / n,
    }


def run_eval(items: list[dict], ask, sleep_s: float = 0.0) -> dict:
    """逐条问答 + 计分。ask(question) -> /api/chat 响应 dict；单条异常记 error 并计 0。"""
    details = []
    for item in items:
        rec = {"id": item["id"], "question": item["question"], "gold": item["gold"]}
        try:
            result = ask(item["question"])
            rec["scores"] = score_item(item, result)
            rec["answer"] = _final_text(result)
            rec["citations_used"] = result.get("citations_used")
            rec["hallucinated_citations"] = result.get("hallucinated_citations")
        except Exception as e:  # 单条失败不中断全量，如实记 error 并计 0
            rec["error"] = str(e)
            rec["scores"] = {"E": 0, "V": 0, "D": 0, "total": 0}
        details.append(rec)
        if sleep_s:
            time.sleep(sleep_s)
    return {"details": details, "summary": summarize([d["scores"] for d in details])}


def make_http_ask(base_url: str, timeout: float = 300.0):
    """构造经 HTTP 调 /api/chat 的 ask（verify=true 需要校验循环产物判 V）。"""
    def ask(question: str) -> dict:
        body = json.dumps({"question": question, "verify": True}).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/api/chat", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    return ask


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="域内评测跑分（verdict∧evidence∧dose 三条件计分）")
    ap.add_argument("--eval-set", default="data/eval/qa_eval.json")
    ap.add_argument("--out", default="data/eval/report.json")
    ap.add_argument("--base-url", default="http://127.0.0.1:8008")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（冒烟用）")
    ap.add_argument("--sleep", type=float, default=0.0, help="逐条间隔秒数")
    args = ap.parse_args(argv)

    items = json.loads(Path(args.eval_set).read_text(encoding="utf-8"))["items"]
    if args.limit:
        items = items[: args.limit]

    # 预检：服务不可达直接失败，不浪费逐条超时
    with urllib.request.urlopen(f"{args.base_url}/api/stats", timeout=5) as resp:
        resp.read()

    t0 = time.time()
    report = run_eval(items, make_http_ask(args.base_url), sleep_s=args.sleep)
    report["meta"] = {"base_url": args.base_url, "eval_set": args.eval_set,
                      "elapsed_s": round(time.time() - t0, 1)}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    for d in report["details"]:
        sc = d["scores"]
        mark = "✓" if sc["total"] == 1 else "✗"
        err = f"  [error: {d['error'][:40]}]" if "error" in d else ""
        print(f"{mark} #{d['id']:>2} E{sc['E']} V{sc['V']} D{sc['D']}  {d['question'][:30]}{err}")
    s = report["summary"]
    print(f"\n汇总 n={s['n']}  E={s['E']:.3f}  V={s['V']:.3f}  D={s['D']:.3f}  total={s['total']:.3f}")
    print(f"报告已写入 {args.out}")


if __name__ == "__main__":
    main()
