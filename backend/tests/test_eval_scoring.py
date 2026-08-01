"""run_eval 三条件计分（verdict∧evidence∧dose）玩具用例：不触网、不调 LLM。

计分口径（总纲评测指标本体）：
- E（evidence 引用正确）：citations_used 命中 must_cite_pmid 对应证据包编号；
  拒答类不允许引用任何编号。
- V（verdict 判定正确）：核验类看 verification 全部 supported 且 final_answer 无 ⚠️；
  拒答类看答案是否含「证据不足」语义。
- D（dose 剂量引用）：答案提到浓度时必须带估计/文献限定语义；未提浓度为真空通过。
- total = E×V×D（三条件同时满足才算 1）。
"""

from data.tools.run_eval import (
    pmid_pack_ids,
    score_dose,
    score_evidence,
    score_item,
    score_verdict,
    summarize,
)


def _pack(*pmids):
    """每条 PMID 造一个证据包条目（文本内嵌 PubMed URL，与真实证据包格式一致）。"""
    return [
        {"id": i, "kind": "assertion",
         "text": f"成分X：美白，证据：paper title，期刊，2020，https://pubmed.ncbi.nlm.nih.gov/{p}/"}
        for i, p in enumerate(pmids, start=1)
    ]


def _result(citations, answer="答案", verification=None):
    return {
        "answer": answer,
        "evidence_pack": _pack("12100180", "17515510"),
        "citations_used": citations,
        "hallucinated_citations": [],
        "verification": verification,
    }


def _fact_gold():
    return {"must_cite_pmid": ["17515510"], "expected_verdict_hint": "effective",
            "type": "fact_check"}


def _refusal_gold():
    return {"must_cite_pmid": [], "expect_refusal": True,
            "expected_verdict_hint": "refusal", "type": "refusal"}


def _verification(supporteds, final_answer="答案"):
    return {
        "final_answer": final_answer,
        "verification": [
            {"claim": f"c{i}", "supported": s, "reason": "", "citations": [i]}
            for i, s in enumerate(supporteds, start=1)
        ],
        "rewritten": False,
        "rounds": 1,
    }


# ---------- E：evidence 引用正确 ----------

def test_pmid_pack_ids_maps_pmid_to_item_ids():
    assert pmid_pack_ids(_pack("12100180", "17515510"), ["17515510"]) == {2}
    assert pmid_pack_ids(_pack("12100180"), ["99999999"]) == set()


def test_evidence_hit_when_citation_covers_must_cite_pmid():
    assert score_evidence(_fact_gold(), _result([1, 2])) == 1


def test_evidence_miss_when_citations_do_not_cover_pmid():
    assert score_evidence(_fact_gold(), _result([1])) == 0
    assert score_evidence(_fact_gold(), _result([])) == 0


def test_evidence_refusal_clean_only_when_no_citation():
    assert score_evidence(_refusal_gold(), _result([])) == 1
    assert score_evidence(_refusal_gold(), _result([1])) == 0


# ---------- V：verdict 判定正确 ----------

def test_verdict_factcheck_pass_all_supported_no_warn():
    assert score_verdict(_fact_gold(), _result([1], verification=_verification([True, True]))) == 1


def test_verdict_factcheck_fail_on_unsupported():
    assert score_verdict(_fact_gold(), _result([1], verification=_verification([True, False]))) == 0


def test_verdict_factcheck_fail_on_warn_mark():
    assert score_verdict(
        _fact_gold(), _result([1], verification=_verification([], final_answer="答案⚠️"))) == 0


def test_verdict_factcheck_fail_when_verification_missing():
    assert score_verdict(_fact_gold(), _result([1], verification=None)) == 0


def test_verdict_refusal_pass_with_insufficient_evidence_semantics():
    v = _verification([], final_answer="证据不足，无法判定该成分的功效。")
    assert score_verdict(_refusal_gold(), _result([], verification=v)) == 1


def test_verdict_refusal_fail_when_answer_fabricates():
    v = _verification([], final_answer="该成分可以美白，效果很好。")
    assert score_verdict(_refusal_gold(), _result([], verification=v)) == 0


def test_verdict_refusal_falls_back_to_answer_without_verification():
    assert score_verdict(_refusal_gold(), _result([], answer="证据不足，无法判定")) == 1


# ---------- D：dose 剂量引用 ----------

def test_dose_vacuous_pass_when_no_concentration_mentioned():
    assert score_dose(_fact_gold(), _result([1], answer="可以美白。")) == 1


def test_dose_pass_when_concentration_carries_qualifier():
    for text in ["起效浓度 2-5%（文献值，非产品中浓度）",
                 "产品中浓度为估计值，约 3%",
                 "实验中浓度 2% 起效",
                 "研究浓度 0.4% 改善细纹"]:
        assert score_dose(_fact_gold(), _result([1], answer=text)) == 1, text


def test_dose_fail_when_concentration_bare():
    assert score_dose(_fact_gold(), _result([1], answer="产品中浓度为 5%，可以美白。")) == 0


def test_dose_prefers_final_answer_over_answer():
    v = _verification([True], final_answer="起效浓度 2%（文献值）")
    assert score_dose(_fact_gold(), _result([1], answer="浓度 5%", verification=v)) == 1


# ---------- 三条件乘法与汇总 ----------

def test_item_total_is_product_of_three_conditions():
    item = {"id": 1, "question": "q", "gold": _fact_gold()}
    ok = _result([2], verification=_verification([True], final_answer="起效浓度 2%（文献值）"))
    assert score_item(item, ok) == {"E": 1, "V": 1, "D": 1, "total": 1}

    bad_dose = _result([2], verification=_verification([True], final_answer="浓度 5% 美白"))
    assert score_item(item, bad_dose)["total"] == 0

    bad_ev = _result([1], verification=_verification([True], final_answer="起效浓度 2%（文献值）"))
    assert score_item(item, bad_ev) == {"E": 0, "V": 1, "D": 1, "total": 0}


def test_summarize_averages_per_item_scores():
    details = [
        {"E": 1, "V": 1, "D": 1, "total": 1},
        {"E": 0, "V": 1, "D": 0, "total": 0},
    ]
    assert summarize(details) == {"n": 2, "E": 0.5, "V": 1.0, "D": 0.5, "total": 0.5}


def test_summarize_empty():
    assert summarize([]) == {"n": 0, "E": 0.0, "V": 0.0, "D": 0.0, "total": 0.0}
