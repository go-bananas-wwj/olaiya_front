"""review_cir_batch._conc_txt 格式化测试：定点格式化（禁科学计数法）+ 非安全限值标注。"""

from data.tools.review_cir_batch import _conc_txt, _fmt


def test_fmt_no_scientific_notation():
    assert _fmt(0.0000009) == "0.0000009"
    assert _fmt(0.00001) == "0.00001"
    assert _fmt(0.00000001) == "0.00000001"
    assert _fmt(0.0000083) == "0.0000083"


def test_fmt_strips_trailing_zeros():
    assert _fmt(100.0) == "100"
    assert _fmt(0.04) == "0.04"
    assert _fmt(34.5) == "34.5"
    assert _fmt(2.0) == "2"


def test_conc_txt_range():
    assert _conc_txt(0.0001, 99.4) == "；行业调查使用浓度区间 0.0001%-99.4%，非安全限值"
    assert _conc_txt(0.0000009, 5.4) == "；行业调查使用浓度区间 0.0000009%-5.4%，非安全限值"


def test_conc_txt_max_only():
    assert _conc_txt(None, 39.9) == "；行业调查最大使用浓度 39.9%，非安全限值"
    assert _conc_txt(100.0, 100.0) == "；行业调查最大使用浓度 100%，非安全限值"


def test_conc_txt_empty():
    assert _conc_txt(None, None) == ""
