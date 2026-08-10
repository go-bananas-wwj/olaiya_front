"""build_usan_alias 判定规则测试：同 CID 唯一 IECIC 命中才接受；零/多命中、多 CID 拒收。"""

from data.tools.build_usan_alias import eval_pubchem, norm

IECIC_KEYS = {norm(k): k for k in [
    "ALCOHOL", "ALCOHOL DENAT.", "CERAMIDE AP", "WATER", "AQUA",
    "TEREPHTHALYLIDENE DICAMPHOR SULFONIC ACID",
]}


def _payload(*cid_and_syns):
    return {"InformationList": {"Information": [
        ({"CID": cid, "Synonym": syns} if cid is not None else {"Synonym": syns})
        for cid, syns in cid_and_syns]}}


def test_unique_iecic_hit_accepted():
    """同一 CID 同义词恰好唯一命中 IECIC 键：接受（CERAMIDE 6 II → CERAMIDE AP）。"""
    data = _payload((44625889, ["Ceramide AP", "Ceramide 6 II", "ceramide 6", "Ceramide VI"]))
    key, reason = eval_pubchem(data, IECIC_KEYS)
    assert key == "CERAMIDE AP" and reason == ""


def test_zero_hit_rejected():
    """同义词不含任何 IECIC 键：拒收（CERAMIDE 3 的实际情形）。"""
    data = _payload((9898642, ["Ceramide 3", "N-Stearoyl Phytosphingosine"]))
    key, reason = eval_pubchem(data, IECIC_KEYS)
    assert key is None and reason == "IECIC 零命中"


def test_multi_iecic_hit_rejected():
    """同义词命中多个 IECIC 键：拒收（ETHANOL 同时命中 ALCOHOL 与 ALCOHOL DENAT.）。"""
    data = _payload((702, ["ethanol", "alcohol", "Alcohol denat."]))
    key, reason = eval_pubchem(data, IECIC_KEYS)
    assert key is None and "命中 2 个" in reason
    data = _payload((962, ["water", "aqua", "Purified water"]))  # PURIFIED WATER 情形
    key, _ = eval_pubchem(data, IECIC_KEYS)
    assert key is None


def test_multi_cid_rejected():
    """名字查询返回多个 CID（歧义物质）：拒收，不跨 CID 合并同义词。"""
    data = _payload((111, ["alcohol"]), (222, ["water"]))
    key, reason = eval_pubchem(data, IECIC_KEYS)
    assert key is None and "多 CID 拒收" in reason and "111" in reason and "222" in reason


def test_cidless_entry_not_counted():
    """无 CID 的条目不算一个 CID；单 CID + 无 CID 条目仍按单 CID 判定。"""
    data = _payload((None, ["junk"]), (44625889, ["Ceramide AP"]))
    key, _ = eval_pubchem(data, IECIC_KEYS)
    assert key == "CERAMIDE AP"


def test_synonym_case_and_whitespace_normalized():
    """同义词匹配大小写无关、空白归一后精确匹配。"""
    data = _payload((44625889, ["  ceramide   ap "]))
    key, _ = eval_pubchem(data, IECIC_KEYS)
    assert key == "CERAMIDE AP"
