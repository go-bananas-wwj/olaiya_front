"""供应商资料加载器测试：降级通道措辞/强制 unknown/匹配通道/幂等/复配注明/散文跳过。

合成数据直喂 loader（不依赖 git 忽略的 xls 原件）；解析器侧只测纯函数
（split_components / split_efficacy_phrases），真实 xls 由人工跑批验证。
"""

import pytest

from app.models.evidence import EvidenceType
from app.models.ingredient import EfficacyAssertion, Ingredient
from data.loaders.supplier_loader import (
    Matcher, load_supplier, split_efficacy_phrases,
)
from data.tools.parse_supplier_xls import split_components


def _rec(sheet, product, inci_en, function_text, inci_cn="", category="",
         producer="测试厂"):
    return {"sheet": sheet, "product_name": product, "inci_en": inci_en,
            "inci_cn": inci_cn, "function_text": function_text,
            "category": category, "producer": producer, "dosage": "",
            "legal_limit": "",
            "components": split_components(inci_en)}


@pytest.fixture()
def db(session):
    session.add_all([
        Ingredient(inci_name="NIACINAMIDE", cn_name="烟酰胺"),
        Ingredient(inci_name="UBIQUINONE", cn_name="泛醌"),
        Ingredient(inci_name="GLYCERIN", cn_name="甘油"),
    ])
    session.commit()
    return session


def _data(records):
    sheets: dict[str, int] = {}
    for r in records:
        sheets[r["sheet"]] = sheets.get(r["sheet"], 0) + 1
    return {"source": {"file": "test", "nature": "test"},
            "stats": {"total_records": len(records),
                      "by_sheet": {k: {"rows": v, "with_function_text": v}
                                   for k, v in sheets.items()}},
            "records": records}


def test_split_components():
    assert split_components("WATER、BUTYLENE GLYCOL、NIACINAMIDE") == \
        ["WATER", "BUTYLENE GLYCOL", "NIACINAMIDE"]
    assert split_components("UBIQUINONE") == ["UBIQUINONE"]
    assert split_components("") == []
    assert split_components("丁二醇,1,2-戊二醇") == []  # 无拉丁字母的组分不收


def test_split_efficacy_phrases():
    phrases, skipped = split_efficacy_phrases(
        _rec("功效性活性成分", "x", "X", "抗氧化、抗老化", category="美白"))
    assert phrases == ["美白", "抗氧化", "抗老化"]  # 类别并入 + 文本切分
    assert skipped == 0
    # 长散文片段不切不猜
    phrases, skipped = split_efficacy_phrases(
        _rec("保湿剂", "x", "X", "滋润保湿，跟EG-1 1:1复配使用可降低粘腻感"))
    assert phrases == ["滋润保湿"]
    assert skipped == 1


def test_load_creates_supplier_assertions(db):
    data = _data([
        _rec("功效性活性成分", "辅酶Q10", "UBIQUINONE", "抗氧化、抗老化"),
        _rec("功效性活性成分", "烟酰胺精华", "NIACINAMIDE", "美白、淡斑"),
    ])
    stats = load_supplier(db, data)
    assert stats["assertions_new"] == 4
    rows = db.query(EfficacyAssertion).all()
    assert all(r.evidence.type == EvidenceType.SUPPLIER for r in rows)
    assert all(r.efficacy.startswith("原料商宣称：") for r in rows)
    assert all(r.evidence_level == "unknown" for r in rows)  # 强制 unknown 不升级
    assert all(r.evidence_strength == 0.2 for r in rows)
    assert all("未经同行评议" in r.note for r in rows)
    by_eff = {r.efficacy: r for r in rows}
    assert by_eff["原料商宣称：抗氧化"].efficacy_canonical == "抗氧化"


def test_blend_note_and_multi_component(db):
    data = _data([
        _rec("舒敏剂", "舒敏复配", "NIACINAMIDE、UBIQUINONE", "舒缓"),
    ])
    stats = load_supplier(db, data)
    assert stats["components_matched"] == 2
    rows = db.query(EfficacyAssertion).all()
    assert len(rows) == 2  # 两个组分各挂一条
    assert all("复配宣称" in r.note for r in rows)


def test_match_channels_and_unmatched(db):
    data = _data([
        _rec("保湿剂", "折叠形", " niacinamide ", "保湿"),      # 折叠/大小写命中
        _rec("保湿剂", "中文通道", "", "保湿", inci_cn="甘油"),   # 中文名命中
        _rec("保湿剂", "未知原料", "SOME UNKNOWN INCI", "保湿"),  # 不猜
    ])
    stats = load_supplier(db, data)
    assert stats["assertions_new"] == 2
    assert stats["components_unmatched"] == 1
    assert stats["unmatched"][0]["component"] == "SOME UNKNOWN INCI"


def test_idempotent(db):
    data = _data([_rec("功效性活性成分", "辅酶Q10", "UBIQUINONE", "抗氧化")])
    s1 = load_supplier(db, data)
    db.commit()
    s2 = load_supplier(db, data)
    assert s1["assertions_new"] == 1
    assert s2["assertions_new"] == 0
    assert s2["assertions_existing"] == 1
    assert db.query(EfficacyAssertion).count() == 1


def test_in_run_dedup(db):
    """同次运行内多条记录命中同成分同功效：只建一条（autoflush=False，靠本地留痕）。"""
    data = _data([
        _rec("功效性活性成分", "产品甲", "UBIQUINONE", "抗氧化"),
        _rec("功效性活性成分", "产品乙", "UBIQUINONE", "抗氧化"),
        _rec("功效性活性成分", "产品丙", " ubiquinone ", "抗氧化"),
    ])
    stats = load_supplier(db, data)
    assert stats["assertions_new"] == 1
    assert stats["assertions_existing"] == 2
    assert db.query(EfficacyAssertion).count() == 1


def test_process_type_category_rejected(db):
    """「水包油」等工艺类型落「其他」族，不当功效断言（canonicalize 拦截）。"""
    phrases, _ = split_efficacy_phrases(
        _rec("乳化剂", "Span20", "SORBITAN LAURATE", "助乳化", category="水包油"))
    assert "水包油" not in phrases


def test_prose_only_record_creates_nothing(db):
    data = _data([
        _rec("常用油酯", "ABIL", "DIMETHICONE", "硅油可改善油脂的腻感，以及涂抹时的丝滑体验"),
    ])
    stats = load_supplier(db, data)
    assert stats["assertions_new"] == 0
    assert stats["prose_skipped"] == 2  # 两个逗号片段都是散文，如实计数
    assert stats["records_no_function"] == 1


def test_matcher_fold_unique_only(db):
    m = Matcher(db)
    assert m.match_en("niacinamide") == db.query(Ingredient).filter_by(
        inci_name="NIACINAMIDE").one().id
    assert m.match_cn("甘油") is not None
    assert m.match_cn("不存在的成分") is None


def test_matcher_usan_alias_channel(db):
    """USAN 别名通道：AVOBENZONE（USAN 名）→ BUTYL METHOXYDIBENZOYLMETHANE。"""
    db.add(Ingredient(inci_name="BUTYL METHOXYDIBENZOYLMETHANE",
                      cn_name="丁基甲氧基二苯甲酰基甲烷"))
    db.commit()
    m = Matcher(db)
    assert m.match_en("avobenzone") is not None  # 大小写无关
    assert m.match_en("AVOBENZONE") == m.match_en("BUTYL METHOXYDIBENZOYLMETHANE")


def test_matcher_iecic_reverse_channel(db):
    """IECIC 中文名唯一反查：库内成分中文名与 IECIC 不同时仍能命中。"""
    db.add(Ingredient(inci_name="BUTYLENE GLYCOL", cn_name="1,3-丁二醇（旧称）"))
    db.commit()
    m = Matcher(db)
    # 「丁二醇」不在库内 cn_name 中，走 IECIC 反查 → BUTYLENE GLYCOL
    assert m.match_cn("丁二醇") == db.query(Ingredient).filter_by(
        inci_name="BUTYLENE GLYCOL").one().id


def test_supplier_excluded_from_fingerprint(db):
    """原料商宣称不进功效指纹（降级通道 purity），但仍入 detail 如实标注。"""
    from app.models.product import Product, ProductIngredient
    from app.services.fingerprint import compute_fingerprint
    p = Product(name="p", brand="b")
    db.add(p)
    db.flush()
    niac = db.query(Ingredient).filter_by(inci_name="NIACINAMIDE").one()
    db.add(ProductIngredient(product_id=p.id, ingredient_id=niac.id, position=1))
    db.commit()
    load_supplier(db, _data([
        _rec("功效性活性成分", "烟酰胺精华", "NIACINAMIDE", "美白")]))
    fp = compute_fingerprint(db, p.id)
    assert fp["fingerprint"] == {}
    assert fp["coverage"]["excluded_count"] == 1
    assert "原料商宣称" in fp["detail"][0]["exclude_reason"]


def test_backfill_keeps_supplier_unknown(db):
    """回填工具不得把 supplier 断言升级出 unknown（note 含「动物」关键词也不升级）。"""
    from data.tools.backfill_evidence_level import backfill_session
    load_supplier(db, _data([
        _rec("功效性活性成分", "辅酶Q10", "UBIQUINONE", "抗氧化", producer="动物实验厂")]))
    db.commit()
    backfill_session(db)
    row = db.query(EfficacyAssertion).filter_by(efficacy="原料商宣称：抗氧化").one()
    assert row.evidence_level == "unknown"
    assert row.evidence_strength == 0.2
