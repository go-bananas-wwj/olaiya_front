"""extract_guige_names 提取规则测试：标题识别 / 跳过逻辑 / 水印丢弃（玩具数据）。

规则回顾（data/tools/extract_guige_names.py）：
- 页首「化妆品技术在线 HzpOnline」水印行丢弃；
- 标题行 `N.中文名`（≥2 CJK 字、无正文特征字符、非目录引导点结尾）；
- 下一行必须是英文行（无 CJK、≥3 拉丁字母），允许折行拼接、括号别名行跳过；
- 英文名后必须有「本品/性状/参考」确认句，否则跳过计 no_confirm（绝不猜）。
"""

import json

from data.tools.extract_guige_names import (
    extract_pairs,
    is_en_line,
    load_pages,
    strip_watermark,
    valid_cn_name,
)

ENTRY = """化妆品技术在线:Http://www.Hzp0nline.com/
3.硬脂酸辛酯
2-Ethyl hexyl Stearate
本品主要是2-乙基已醇的硬脂酸酯（CHs20：396.70)。
性状无色至淡黄色透明油液，稍有特异气味。
酸价5以下(第1法，10g).
"""


def _pairs(pages):
    pairs, stats = extract_pairs(pages)
    return pairs, stats


def test_basic_entry_extracted():
    pairs, stats = _pairs([(59, ENTRY)])
    assert pairs == [{"cn_name": "硬脂酸辛酯", "en_name": "2-Ethyl hexyl Stearate", "page": 59}]
    assert stats["pairs"] == 1
    assert stats["title_candidates"] == 1


def test_watermark_lines_dropped():
    lines = strip_watermark([
        "化妆品技术在线:Http://www.Hzp0nline.com/",
        "化妆品技在线",
        "Wuw .Hzponllae:ooe",
        "3.硬脂酸辛酯",
        "",
        "   ",
    ])
    assert lines == ["3.硬脂酸辛酯"]


def test_watermark_variant_not_misparsed_as_title():
    # 水印行若不被丢弃，「化妆品技术在线:Http…」含冒号也不会过中文名校验，双保险
    text = "化妆品技术在线：Http：//www.Hzp0nIine.com/\n" + ENTRY.split("\n", 1)[1]
    pairs, _ = _pairs([(1, text)])
    assert len(pairs) == 1


def test_toc_line_skipped():
    # 目录条目：引导点结尾 + 下一行是页码而非英文名
    toc = """目录
1.硬脂酸异十六烷基酯
(3)
2.硬脂酸乙酯.···.
(4)
"""
    pairs, stats = _pairs([(9, toc)])
    assert pairs == []
    # 第二条引导点同行 → toc_like；第一条引导点被 OCR 断到下一行 → 页码行非英文 → no_en_line
    assert stats["skipped"]["toc_like"] == 1
    assert stats["skipped"]["no_en_line"] == 1


def test_toc_leader_ocr_garbled_page_ref_rejected():
    # 目录行引导点被 OCR 吃掉、页码误识为字母（如 (LTL)）：英文行通过但无确认句 → 拒收
    toc = """46.山楂提取液...
(LTL)...
180.接骨木提取液·
"""
    pairs, stats = _pairs([(46, toc)])
    assert pairs == []
    assert stats["skipped"]["toc_like"] >= 1


def test_missing_english_line_skipped():
    # 断头漏识：标题后英文行丢失 → no_en_line，不猜
    text = "5.α-甘草酸一铵\n本品为甘草酸一铵用碱处理而α一化的产物。\n"
    pairs, stats = _pairs([(537, text)])
    assert pairs == []
    assert stats["skipped"]["no_en_line"] == 1


def test_missing_confirm_line_skipped():
    # 英文名后正文断头（既非本品/性状开头）→ no_confirm，不猜
    text = "7.海水干燥物\nSea Salt\n化镁和氯化钾。\n"
    pairs, stats = _pairs([(676, text)])
    assert pairs == []
    assert stats["skipped"]["no_confirm"] == 1


def test_wrapped_english_name_joined():
    text = """3.聚氧乙烯聚氧丙烯三羟甲基丙烷(4E.O.)(23P.O.)
Polyoxyethylene Polyoxypropylene
Trimethylol Propane(4E.O.)(23P.O.)
本品为聚氧乙烯聚氧丙烯三羟甲基丙烷醚。
"""
    pairs, stats = _pairs([(419, text)])
    assert pairs[0]["en_name"] == (
        "Polyoxyethylene Polyoxypropylene Trimethylol Propane(4E.O.)(23P.O.)")
    assert stats["en_wrapped"] == 1


def test_paren_alias_line_skipped_not_joined():
    # 整行括号是别名行：不拼进英文名，跳过后再确认
    text = """1.对氨基苯甲酸甘油酯
Glyceryl p- Aminobenzoate
(Glyceryl PABA)
本品为对氨基苯甲酸的甘油酯。
"""
    pairs, _ = _pairs([(203, text)])
    assert pairs[0]["en_name"] == "Glyceryl p- Aminobenzoate"
    assert pairs[0]["cn_name"] == "对氨基苯甲酸甘油酯"


def test_body_numbered_clause_not_title():
    # 正文编号条款（确认试验 (1)… 与说明条款「1.本技术规格…」）不提取
    text = """1.本技术规格是在参考国外（日）有关技术资料的基础上编写的.它规定了原料的性状和
质量规格。
2.在各条化妆品原料名称的后面，部分附有别名，并在下面附有英文名称。
"""
    pairs, stats = _pairs([(6, text)])
    assert pairs == []


def test_cn_name_validation():
    assert valid_cn_name("硬脂酸辛酯")
    assert valid_cn_name("油酸甘油酯(2)")
    assert valid_cn_name("乙醇(96.0°～96.5°)")
    assert not valid_cn_name("本技术规格是在参考国外。规定")   # 含句号
    assert not valid_cn_name("05mol/L HSO1ml=341.54mg")        # 无 CJK + 含 =
    assert not valid_cn_name("酸")                              # CJK 不足 2 字


def test_en_line_validation():
    assert is_en_line("Isocetyl Stearate")
    assert is_en_line("Monoammonium α-Glycyrrhizinate")
    assert not is_en_line("本品为异十六烷醇的硬脂酸酯")          # 含 CJK
    assert not is_en_line("(3)")                                # 目录页码
    assert not is_en_line("0.1mol/L NaOH液1ml=28.00mg")         # 含 CJK + =
    assert not is_en_line("D")                                  # 太短


def test_cross_page_title():
    # 标题在页尾、英文名在下页页首（水印之后）
    p1 = "7.卡基二甲基硬脂基铵处理水辉石\n"
    p2 = "化妆品技术在线:Http://www.Hzp0nline.com/\nQuaternium Hectorite\n本品为水辉石的季铵盐处理物。\n"
    pairs, _ = _pairs([(37, p1), (38, p2)])
    assert pairs == [{"cn_name": "卡基二甲基硬脂基铵处理水辉石",
                      "en_name": "Quaternium Hectorite", "page": 37}]


def test_duplicate_rescan_deduped():
    # 书尾重复扫描页（PDF 1030+ 重扫正文开头）按名对去重，保留首页码
    pairs, stats = _pairs([(59, ENTRY), (1032, ENTRY)])
    assert len(pairs) == 1
    assert pairs[0]["page"] == 59
    assert stats["dup_removed"] == 1


def test_load_pages_filters_pdf(tmp_path):
    jsonl = tmp_path / "toy.jsonl"
    rows = [
        {"pdf": "欧莱雅比赛/原料相关/化妆品原料技术规格.pdf", "page": 60, "text": "b", "ocr_ms": 1},
        {"pdf": "欧莱雅比赛/原料相关/化妆品原料手册(新).pdf", "page": 1, "text": "x", "ocr_ms": 1},
        {"pdf": "欧莱雅比赛/原料相关/化妆品原料技术规格.pdf", "page": 59, "text": "a", "ocr_ms": 1},
    ]
    jsonl.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    pages = load_pages(jsonl)
    assert pages == [(59, "a"), (60, "b")]  # 只收技术规格、按页码排序
