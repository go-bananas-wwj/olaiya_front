"""手册工具链玩具数据测试：双栏重排、条目切分、用途句提取、跳过逻辑。

覆盖 data/tools/reorder_shouce.py 与 data/tools/extract_shouce_book.py，
不依赖真实 OCR 产物。
"""

from data.tools.reorder_shouce import reorder_page
from data.tools.extract_shouce_book import (
    capture_field,
    extract,
    number_gaps,
    parse_header,
)

W, H = 2000.0, 3000.0


def _ln(x0, y0, x1, y1, text):
    return {"box": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "text": text, "score": 1.0}


def _row(text):
    return {"text": text}


def test_reorder_two_columns_and_fullwidth_band():
    """左右栏按栏重排：带内左栏整体在前；整宽行（章节标题）作为分带边界；
    水印行与页脚页码被丢弃。"""
    page = {"pdf": "toy.pdf", "page": 1, "width": W, "height": H, "lines": [
        _ln(0, 100, 1800, 140, "化妆品技术在线 HzpOnline"),      # 水印
        _ln(300, 300, 900, 340, "左栏上"),                        # 带1 左
        _ln(1100, 300, 1700, 340, "右栏上"),                      # 带1 右
        _ln(700, 700, 1300, 750, "第二节 香料与香精"),            # 整宽行（分带）
        _ln(300, 900, 900, 940, "左栏下"),                        # 带2 左
        _ln(1100, 900, 1700, 940, "右栏下"),                      # 带2 右
        _ln(900, 2900, 1000, 2940, "143"),                       # 页脚页码
    ]}
    out = reorder_page(page)
    assert out["text"].split("\n") == [
        "左栏上", "右栏上", "第二节 香料与香精", "左栏下", "右栏下"]


def test_reorder_merges_split_label_row():
    """同一视觉行被 OCR 拆成多个 box（「用途」标签与内容分离）时按 x 拼接。"""
    page = {"pdf": "toy.pdf", "page": 1, "width": W, "height": H, "lines": [
        _ln(1150, 500, 1700, 540, "作保湿剂，有良好"),   # 内容 box（x 在后）
        _ln(1075, 501, 1160, 539, "用途"),              # 标签 box（x 在前，y 略差）
        _ln(1075, 600, 1700, 640, "的抑菌作用。"),       # 下一行不并
    ]}
    out = reorder_page(page)
    assert out["text"].split("\n") == ["用途作保湿剂，有良好", "的抑菌作用。"]


def test_extract_two_entries_and_skip_no_purpose():
    """条目切分：粘连标题行与独立编号行两种形态；缺用途条目跳过计数。"""
    pages = [
        {"pdf": "toy.pdf", "page": 1, "width": W, "height": H, "lines": [
            _row("艾蒿油Absinthe oil2-2-001"),     # 标题粘连编号
            _row("别名苦艾油"),
            _row("性质绿色至浅黄色液体。"),
            _row("用途用于调配香水，化妆品香精。"),
            _row("贮运及保管铝桶装。"),
            _row("羟基香茅醛Hydroxy citronellal"),  # 标题与编号分行
            _row("2-2-171"),
            _row("性质无色液体。只有甜美香气。"),   # 无用途 → 跳过
        ]},
    ]
    res = extract(pages)
    assert res["stats"]["total_records"] == 1
    assert res["stats"]["skipped"] == {"no_purpose": 1}
    rec = res["records"][0]
    assert rec["entry_no"] == "2-2-001"
    assert rec["cn_name"] == "艾蒿油" and rec["en_name"] == "Absinthe oil"
    assert rec["alias"] == "苦艾油"
    assert rec["purpose"] == "用于调配香水，化妆品香精。"
    assert rec["page"] == 1


def test_purpose_multiline_verbatim_and_stop_keyword():
    """用途句跨行 verbatim 拼接（含 OCR 错字不改），止于下一个字段关键字。"""
    body = [
        "用途州作牙膏、化妆品的调",   # 「州」为 OCR 错字，verbatim 保留
        "湿剂。同时也是制备紫罗兰酮的原料。",
        "包装及贮运铝桶灌装。",
    ]
    assert capture_field(body, "用途") == "州作牙膏、化妆品的调湿剂。同时也是制备紫罗兰酮的原料。"


def test_parse_header_rejects_sentence_window():
    """编号行上方最近的 CJK 行是正文句子（含句读）→ 判不出中文名，不猜。"""
    assert parse_header(["黑色玻璃瓶中。置于阴凉处。"], "") is None
    # 最近 CJK 行是合法名称 + 拉丁尾段 → 拆出中文名/英文名
    assert parse_header([], "柠檬醛Citral") == ("柠檬醛", "Citral")
    # 中文名行尾粘连的 ASCII 垃圾被剥掉（「…甜菜碱1-」）
    assert parse_header(["羟乙基棕榈酸咪唑啉甜菜碱1-", "Hydroxyethyl imidazo-"], "line betaine") == (
        "羟乙基棕榈酸咪唑啉甜菜碱", "Hydroxyethyl imidazo- line betaine")


def test_page_gap_does_not_swallow_orphan_body():
    """页码断档：未闭合条目不得吞并跳页后的他人正文（抽样页运行场景）。"""
    pages = [
        {"pdf": "toy.pdf", "page": 1, "width": W, "height": H, "lines": [
            _row("按叶油Eucalyptus oil2-2-002"),
            _row("性质无色或淡黄色液体，有刺激性"),   # 条目跨页，下页缺失
        ]},
        {"pdf": "toy.pdf", "page": 5, "width": W, "height": H, "lines": [
            _row("用途调制花香型香精。"),             # 实际是 2-2-170 的正文（孤儿行）
            _row("柠檬醛Citral2-2-172"),
            _row("用途可调制花香型及柠檬型香精。"),
        ]},
    ]
    res = extract(pages)
    # 2-2-002 被断档关闭且无用途 → 跳过；孤儿用途句不被误挂到 2-2-002
    assert res["stats"]["skipped"] == {"no_purpose": 1}
    assert [r["entry_no"] for r in res["records"]] == ["2-2-172"]
    assert res["records"][0]["purpose"] == "可调制花香型及柠檬型香精。"
    assert res["stats"]["orphan_rows"] == 1


def test_number_gaps():
    assert number_gaps(["2-2-001", "2-2-002", "2-2-004"]) == [
        {"prefix": "2-2", "missing": ["2-2-003"]}]
    assert number_gaps(["2-2-001", "2-5-001"]) == []
