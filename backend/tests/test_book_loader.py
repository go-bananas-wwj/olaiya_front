"""工具书加载器测试：四道护栏/白名单只命中核实项/幂等/去重/强制 unknown+0.3/
canonical 用完整句/表格碎片截断。

合成玩具数据直喂 loader（不依赖 git 忽略的 OCR 原件与 PDF）。
"""

import pytest

from app.models.evidence import Evidence, EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from data.loaders.book_loader import (
    BOOK_STRENGTH, EVIDENCE_TITLE, apply_name_whitelist, clean_purpose,
    load_book, normalize_entry_no, split_alias_candidates, strip_cn_latin,
)


def _rec(entry_no, cn_name, en_name, purpose, alias=None, page=1):
    return {"entry_no": entry_no, "cn_name": cn_name, "en_name": en_name,
            "alias": alias, "purpose": purpose, "page": page}


@pytest.fixture()
def db(session):
    session.add_all([
        Ingredient(inci_name="EUCALYPTUS GLOBULUS LEAF OIL", cn_name="桉叶油"),
        Ingredient(inci_name="RICINUS COMMUNIS (CASTOR) SEED OIL", cn_name="蓖麻油"),
        Ingredient(inci_name="CASTOR OIL", cn_name="蓖麻籽油脂"),
        Ingredient(inci_name="SESAMUM INDICUM (SESAME) SEED OIL", cn_name="芝麻油"),
        Ingredient(inci_name="SANTALUM ALBUM (SANDALWOOD) OIL", cn_name="檀香油"),
        Ingredient(inci_name="GLYCYRRHIZA INFLATA ROOT EXTRACT", cn_name="甘草提取物"),
        Ingredient(inci_name="GLYCERIN", cn_name="甘油"),
    ])
    session.commit()
    return session


def _data(records):
    return {"source": {"file": "test", "nature": "test"},
            "stats": {"total_records": len(records)},
            "records": records}


# ---------- 护栏 1：entry_no 前缀归一化 ----------

def test_normalize_entry_no():
    assert normalize_entry_no("02-1-112") == ("2-1-112", True)
    assert normalize_entry_no("01-3-018") == ("1-3-018", True)
    assert normalize_entry_no("1-1-001") == ("1-1-001", False)
    # 其他畸形前缀不猜，原样保留
    assert normalize_entry_no("72-3-009") == ("72-3-009", False)


def test_guard1_odd_prefix_kept_in_note(db):
    stats = load_book(db, _data([
        _rec("72-3-009", "桉叶油", "EUCALYPTUS GLOBULUS LEAF OIL", "用作香精。")]))
    assert stats["assertions_new"] == 1
    assert stats["entry_no_normalized"] == 0
    row = db.query(EfficacyAssertion).one()
    assert "72-3-009" in row.note  # 畸形前缀原样保留在 note
    assert stats["odd_entry_nos"] == [{"entry_no": "72-3-009", "cn_name": "桉叶油",
                                       "page": 1}]


# ---------- 护栏 2：用途句清洗 ----------

def test_guard2_table_fragment_truncation():
    # 表格碎片标记处截断（JSCI / FAO/WHO / GB<数字> / 指标名称）
    for marker in ("JSCI—II99.5", "FAO/WHO,1977", "GB 2760—86名称", "指标名称微晶纤维素"):
        text, flags = clean_purpose(f"用作化妆品防腐剂。{marker}乱码")
        assert flags["table_truncated"] is True
        assert text == "用作化妆品防腐剂。"
    # 连续 4 段以上大写拉丁碎片（化学式残片）
    text, flags = clean_purpose("增强其他活性物HCCOOHHCHHCHHCH3在防晒方面的疗效。")
    assert flags["table_truncated"] is True
    assert text is None  # 截断处不在句读后 → 整条跳过


def test_guard2_tail_strip_and_skip():
    # 末句句读后混入下一条目名+英文名 → 剥离
    text, flags = clean_purpose("在化妆品中可用于唇膏产品。氢化羊毛脂Hydrogenated lanolin")
    assert flags["tail_stripped"] is True
    assert text == "在化妆品中可用于唇膏产品。"
    # 章节头尾巴
    text, flags = clean_purpose("可作乳霜原料。（二）动物系油质原料")
    assert flags["tail_stripped"] is True
    assert text == "可作乳霜原料。"
    # 清洗后不以句读结尾 → 整条跳过
    text, _ = clean_purpose("食用红色素。化妆品用色素。按我国标准（")
    assert text is None


def test_guard2_superscript_suspect_kept(db):
    stats = load_book(db, _data([
        _rec("2-2-003", "桉叶油", "EUCALYPTUS GLOBULUS LEAF OIL",
             "用于香精配制。直接用量（1～3）×10-6，调配用量0.5%～1%。")]))
    assert stats["superscript_suspect"] == 1
    assert stats["assertions_new"] == 1  # suspect 只统计，保留入库


def test_guard2_skip_counted(db):
    stats = load_book(db, _data([
        _rec("2-3-006", "未知物", "UNKNOWN XYZ", "食用红色素。化妆品用色素。按")]))
    assert stats["skipped_no_endpunc"] == 1
    assert stats["assertions_new"] == 0


# ---------- 护栏 3：窄白名单订正 + alias 截断 ----------

def test_guard3_whitelist_only_verified_items(db):
    # 核实项：按叶油→桉叶油（p150 核对）命中库内「桉叶油」
    stats = load_book(db, _data([
        _rec("2-2-002", "按叶油", "Eucalyptus oil", "用于调配香精。")]))
    assert stats["matched_cn"] == 1
    assert stats["whitelist_applied"] == 1
    # 未核实形近字不订正（「按树油」不在白名单，保持原样不猜 → 未命中）
    stats = load_book(db, _data([
        _rec("9-9-999", "按树油", "SOMETHING OIL XYZ", "用于调配香精。")]))
    assert stats["whitelist_applied"] == 0
    assert stats["assertions_new"] == 0
    assert len(stats["unmatched"]) == 1


def test_guard3_castor_context_gated(db):
    # 麻油→蓖麻油 只在 en_name 含 Castor 时订正（p8 条目 1-1-003 核实）
    stats = load_book(db, _data([
        _rec("1-1-003", "麻油", "Castor oil", "用作化妆品原料。")]))
    assert stats["whitelist_applied"] == 1
    assert stats["matched_cn"] == 1
    # 芝麻油义项（Sesame oil）不动
    assert apply_name_whitelist("麻油", "Sesame oil", {"whitelist_applied": 0}) == "麻油"


def test_guard3_alias_label_truncation():
    assert split_alias_candidates("麻籽油组成脂肪酸三甘油酯，其脂肪酸组分") == ["麻籽油"]
    assert split_alias_candidates("巴旦杏仁油；扁桃仁油") == ["巴旦杏仁油", "扁桃仁油"]
    assert split_alias_candidates("本品为马科动物") == []  # 截空则 alias 弃用
    assert split_alias_candidates(None) == []


def test_guard3_alias_match_channel(db):
    # alias 订正后走匹配（廿草→甘草，p307 核实）
    stats = load_book(db, _data([
        _rec("2-6-006", "甘草酸X", "SOME UNRELATED NAME QQQ",
             "用作化妆品添加剂。", alias="廿草甜素；廿草提取物组成见原文")]))
    assert stats["matched_alias"] == 1
    assert stats["whitelist_applied"] == 2  # 「廿草甜素」「廿草提取物」两条候选各订正一次
    assert stats["assertions_new"] == 1


# ---------- 护栏 4：cn_name 拉丁剥离 ----------

def test_guard4_cn_latin_strip(db):
    stats = load_book(db, _data([
        _rec("2-2-081", "檀香油Sandalwoodoil（yellow）", "UNRELATED XYZ OIL",
             "用于调配香精。")]))
    assert stats["cn_latin_stripped"] == 1
    assert stats["matched_cn"] == 1
    assert stats["assertions_new"] == 1


def test_guard4_no_clean_cn_skipped(db):
    stats = load_book(db, _data([
        _rec("2-1-006", "盐Sodium Ci2 ~", "SODIUM SOMETHING QQQ", "用作原料。")]))
    assert stats["skipped_cn_latin"] == 1
    assert stats["assertions_new"] == 0


def test_strip_cn_latin_pure():
    assert strip_cn_latin("桉叶油") == ("桉叶油", None)  # 无拉丁不触发
    clean, latin = strip_cn_latin("苍术硬脂Atractylodes oil;")
    assert clean == "苍术硬脂"
    assert latin == "Atractylodes oil"


# ---------- 断言字段口径 ----------

def test_book_channel_wording_and_forced_unknown(db):
    load_book(db, _data([
        _rec("2-2-002", "桉叶油", "EUCALYPTUS GLOBULUS LEAF OIL",
             "用于调配香精，体外试验记载。")]))
    row = db.query(EfficacyAssertion).one()
    assert row.evidence.type == EvidenceType.BOOK
    assert row.evidence.title == EVIDENCE_TITLE
    assert row.efficacy.startswith("工具书记载：")
    assert row.evidence_level == "unknown"  # 强制 unknown（note 含「体外」也不升级）
    assert row.evidence_strength == BOOK_STRENGTH == 0.3
    assert "条目编号：2-2-002" in row.note
    assert "页码：" in row.note
    assert "用途原文（verbatim）：用于调配香精，体外试验记载。" in row.note
    assert "行业参考工具书记载，非原始研究证据" in row.note
    assert "用途句为 OCR 原文未核订，可能含形近字/上下标丢失" in row.note


def test_efficacy_truncation_and_canonical_full_sentence(db):
    filler = "滋润" * 48  # 96 字，加前缀超 100 → 截断以「…」结尾
    purpose = filler + "有美白作用。"  # 102 字用途句
    load_book(db, _data([
        _rec("2-2-002", "桉叶油", "EUCALYPTUS GLOBULUS LEAF OIL", purpose)]))
    row = db.query(EfficacyAssertion).one()
    assert len(row.efficacy) <= 100
    assert row.efficacy.endswith("…")  # 截断标记
    # canonical 用完整用途句：「美白」在被截断的尾部仍命中美白族
    assert "美白" not in row.efficacy
    assert row.efficacy_canonical == "美白"


# ---------- 幂等 / 去重 / 单证据 ----------

def test_idempotent_and_dedup(db):
    data = _data([
        _rec("2-2-002", "桉叶油", "EUCALYPTUS GLOBULUS LEAF OIL", "用于调配香精。"),
        _rec("2-2-003", "按叶油", "EUCALYPTUS GLOBULUS LEAF OIL", "用于调配香精。"),  # 白名单→桉叶油，同 efficacy 去重
    ])
    stats = load_book(db, data)
    assert stats["assertions_new"] == 1  # 同成分同 efficacy 同证据 → 去重
    assert stats["assertions_existing"] == 1
    stats2 = load_book(db, data)  # 重跑 0 新增
    assert stats2["assertions_new"] == 0
    assert stats2["assertions_existing"] == 2
    assert db.query(EfficacyAssertion).count() == 1
    assert db.query(Evidence).count() == 1  # 整书一条证据


def test_same_ingredient_multiple_entries(db):
    stats = load_book(db, _data([
        _rec("2-2-002", "桉叶油", "EUCALYPTUS GLOBULUS LEAF OIL", "用于调配香精。"),
        _rec("2-2-099", "按叶油", "EUCALYPTUS GLOBULUS LEAF OIL", "有杀菌止痒作用。"),
    ]))
    assert stats["assertions_new"] == 2  # 同成分多条目各自成断言
    assert db.query(EfficacyAssertion).count() == 2


# ---------- 指纹口径：BOOK 计入（与 supplier 排除相反，铁律 11） ----------

def test_book_counts_in_fingerprint(db):
    """工具书断言计入功效指纹（低强度 0.3 参与相似度信号）。
    回归测试：若未来 BOOK 被误加进排除列表（fingerprint.py/similar_levels.py），本测试必须红。"""
    from app.models.product import Product, ProductIngredient
    from app.services.fingerprint import compute_fingerprint
    from app.services.similar_levels import _batch_fingerprints
    p = Product(name="p", brand="b")
    db.add(p)
    db.flush()
    gly = db.query(Ingredient).filter_by(inci_name="GLYCERIN").one()
    db.add(ProductIngredient(product_id=p.id, ingredient_id=gly.id, position=1))
    db.commit()
    load_book(db, _data([_rec("2-6-006", "甘油", "GLYCERIN", "有保湿作用。")]))
    fp = compute_fingerprint(db, p.id)
    assert fp["fingerprint"] == {"保湿": pytest.approx(0.3)}  # 剂量因子 1.0 × 强度 0.3
    assert _batch_fingerprints(db)[p.id] == {"保湿": 0.3}  # 批量路径同口径
