"""成分名清洗第二轮测试：营销符号/隐形字符剥除、音调折叠、折叠形唯一命中、
CL→CI 拼写修正与 CI 双段、别名折叠形命中、merge-conflict 日志。"""

import pytest

from data.loaders.inci_cn_loader import InciResolver, normalize_inci, run_cleanup
from app.models.ingredient import Ingredient
from app.models.product import Product, ProductIngredient

SEED = {"map": {
    "GLYCERIN": {"cn_name": "甘油", "iecic_serial": "02421"},
    "PROPYLENE GLYCOL": {"cn_name": "丙二醇", "iecic_serial": "01047"},
    "TRIDECETH-3": {"cn_name": "十三烷醇聚醚-3", "iecic_serial": "00031"},
    "TRIDECETH-12": {"cn_name": "十三烷醇聚醚-12", "iecic_serial": "00032"},
    "1,2-HEXANEDIOL": {"cn_name": "1,2-己二醇", "iecic_serial": "00033"},
    "TITANIUM DIOXIDE": {"cn_name": "二氧化钛", "iecic_serial": "00034"},
    "CRITHMUM MARITIMUM EXTRACT": {"cn_name": "海茴香提取物", "iecic_serial": "00035"},
    "PPG-1 TRIDECETH-6": {"cn_name": "PPG-1 十三醇聚醚-6", "iecic_serial": "00831"},
    "CI 42090": {"cn_name": "CI 42090", "iecic_serial": "00295"},
    "BLUE 1": {"cn_name": "蓝 1", "iecic_serial": "04250"},
    "BLUE 1 LAKE": {"cn_name": "蓝 1 色淀", "iecic_serial": "04251"},
    "CERAMIDE AP": {"cn_name": "神经酰胺 AP", "iecic_serial": "06018"},
}}

ALIASES = {"CERAMIDE 6 II": "CERAMIDE AP"}


# —— normalize_inci：营销符号 / 隐形字符 / 连字符变体 / 音调折叠 ——

@pytest.mark.parametrize("raw,expected", [
    ("⚫ GLYCERIN", "GLYCERIN"),                       # 前导营销圆点
    ("GLYCERIN ⚫", "GLYCERIN"),                       # 尾部营销圆点
    ("⚫PROPYLENE GLYCOL⚫", "PROPYLENE GLYCOL"),       # 前后夹击无空格
    ("XANTHAN GUM⚫", "XANTHAN GUM"),
    ("PITERA™", "PITERA"),                            # 商标符号
    ("ECAMSULE (MEXORYL® SX)", "ECAMSULE (MEXORYL SX)"),  # 括号内 ®
    ("TOCOPHEROL Ⓒ", "TOCOPHEROL"),                   # 圈 C（© OCR 变体）
    ("PPG-\xad1 \xadTRIDECETH-\xad6", "PPG-1 TRIDECETH-6"),  # 软连字符
    ("BEHENETH\xad‐20", "BEHENETH-20"),               # 软连字符 + U+2010 连字符变体
    ("TITANÏUM DIOXIDE", "TITANIUM DIOXIDE"),         # 分音符折叠
    ("CETEARYL GLUCOSIDÉ", "CETEARYL GLUCOSIDE"),     # 尖音符折叠
    ("\U00100001CRITHMUM MARITIMUM EXTRACT", "CRITHMUM MARITIMUM EXTRACT"),  # 私用区垃圾
    ("POLYQUATERNIUM-7°", "POLYQUATERNIUM-7°"),       # ° 不在剥除白名单：拿不准不动
    ("Α-OLEFIN OLIGOMER", "Α-OLEFIN OLIGOMER"),       # 希腊字母不折叠
    ("甘油", "甘油"),                                  # 中文不动
])
def test_normalize_inci_round2(raw, expected):
    assert normalize_inci(raw) == expected


# —— resolver 折叠形匹配（末档） ——

def test_resolver_punct_collapse():
    r = InciResolver(SEED["map"])
    assert r.resolve("TRIDECETH 3") == "TRIDECETH-3"      # 空格 vs 连字符
    assert r.resolve("TRIDECETH 12") == "TRIDECETH-12"    # 数字保留：-3 与 -12 不误并
    assert r.resolve("1.2-HEXANEDIOL") == "1,2-HEXANEDIOL"  # 句点 vs 逗号
    assert r.resolve("1 2-HEXANEDIOL") == "1,2-HEXANEDIOL"
    assert r.resolve("1-2-HEXANEDIOL") == "1,2-HEXANEDIOL"
    assert r.resolve("TRIDECETH 99") is None              # 无此键不归一
    assert r.resolve("XY-UNKNOWN") is None


def test_resolver_corrupt_key_not_collapse_target():
    """损坏 IECIC 键（PDF 换行残空格）不做折叠形归一目标；精确命中仍可用。"""
    m = {"AMMONIUM ACRYLOYLDIMETHYLTAURATE/BEH ENETH-25 METHACRYLATE CROSSPOLYMER":
         {"cn_name": "某聚合物", "iecic_serial": "00001"}}
    r = InciResolver(m)
    assert r.resolve("AMMONIUM ACRYLOYLDIMETHYLTAURATE/BEHENETH-25 METHACRYLATE CROSSPOLYMER") is None
    assert (r.resolve("AMMONIUM ACRYLOYLDIMETHYLTAURATE/BEH ENETH-25 METHACRYLATE CROSSPOLYMER")
            == "AMMONIUM ACRYLOYLDIMETHYLTAURATE/BEH ENETH-25 METHACRYLATE CROSSPOLYMER")


def test_resolver_collapse_keeps_cjk():
    """折叠形必须保留 CJK：中文 INCI 名（EDTA 二钠）不得被吞成英文键 EDTA。"""
    m = {"EDTA": {"cn_name": "EDTA", "iecic_serial": "00001"}}
    r = InciResolver(m)
    assert r.resolve("EDTA 二钠") is None
    assert r.resolve("EDTA") == "EDTA"


def test_resolver_collapse_ambiguous_cn_rejected():
    """两个 IECIC 键折叠形相同但中文名不同：弃用，不猜。"""
    m = {
        "X-1 Y": {"cn_name": "甲", "iecic_serial": "00001"},
        "X1Y": {"cn_name": "乙", "iecic_serial": "00002"},
    }
    r = InciResolver(m)
    assert r.resolve("X 1 Y") is None


def test_resolver_collapse_same_cn_accepted():
    """折叠形多键但中文名一致：无歧义，取其一。"""
    m = {
        "CI 15850": {"cn_name": "CI 15850", "iecic_serial": "00001"},
        "CI 15850:1": {"cn_name": "CI 15850", "iecic_serial": "00002"},
    }
    r = InciResolver(m)
    assert r.resolve("CI 15850") == "CI 15850"  # 精确键优先
    assert r.resolve("CI-15850") in {"CI 15850", "CI 15850:1"}


# —— CL→CI 拼写修正 + CI 双段 ——

def test_cl_typo_ci_dual_merged_into_name_key(session):
    """CL 42090 BLUE 1：CL 改写 CI 后全名仍非键，CI 号段与俗名段都精确命中取俗名段。"""
    keep = Ingredient(inci_name="BLUE 1", cn_name="蓝 1")
    dup = Ingredient(inci_name="CL 42090 BLUE 1", cn_name="CL 42090 BLUE 1")
    session.add_all([keep, dup])
    session.flush()
    stats = run_cleanup(session, seed=SEED, aliases=ALIASES)
    session.commit()
    assert session.query(Ingredient).count() == 1
    assert keep.cn_name == "蓝 1"
    log = " ".join(stats["merge_log"])
    assert "cl-typo" in log and "ci-dual" in log


def test_cl_typo_ci_dual_rename_without_collision(session):
    session.add(Ingredient(inci_name="CL 42090 BLUE 1 LAKE", cn_name="CL 42090 BLUE 1 LAKE"))
    session.flush()
    stats = run_cleanup(session, seed=SEED, aliases=ALIASES)
    session.commit()
    row = session.query(Ingredient).one()
    assert row.inci_name == "BLUE 1 LAKE"
    assert row.cn_name == "蓝 1 色淀"
    assert stats["renamed"] == 1


def test_cl_typo_unmapped_stays(session):
    """CL 改写后仍无命中：保持原样（拿不准不动）。"""
    session.add(Ingredient(inci_name="CL 99999 FOO", cn_name="CL 99999 FOO"))
    session.flush()
    stats = run_cleanup(session, seed=SEED, aliases=ALIASES)
    session.commit()
    assert session.query(Ingredient).one().inci_name == "CL 99999 FOO"
    assert not any("ci-dual" in line for line in stats["merge_log"])


def test_ci_dual_requires_both_segments_hit(session):
    """CI 号段命中但俗名段未命中：不动（防吞未知变体）。"""
    session.add(Ingredient(inci_name="CI 42090 MYSTERY", cn_name="CI 42090 MYSTERY"))
    session.flush()
    run_cleanup(session, seed=SEED, aliases=ALIASES)
    session.commit()
    assert session.query(Ingredient).one().inci_name == "CI 42090 MYSTERY"


# —— 别名折叠形命中 ——

def test_alias_collapse_hyphen_variant(session):
    """别名键的连字符/空格变体（CERAMIDE 6-II）折叠形唯一命中别名键。"""
    keep = Ingredient(inci_name="CERAMIDE AP", cn_name="CERAMIDE AP")
    dup = Ingredient(inci_name="CERAMIDE 6-II", cn_name="CERAMIDE 6-II")
    session.add_all([keep, dup])
    session.flush()
    stats = run_cleanup(session, seed=SEED, aliases=ALIASES)
    session.commit()
    rows = session.query(Ingredient).all()
    assert len(rows) == 1
    assert rows[0].inci_name == "CERAMIDE AP"
    assert rows[0].cn_name == "神经酰胺 AP"
    assert any("usan-alias-collapse" in line for line in stats["merge_log"])


# —— 营销符号剥除全链路：改名 + 撞名合并 + 回填 ——

def test_marketing_dot_stripped_merged_backfilled(session):
    keep = Ingredient(inci_name="GLYCERIN", cn_name="甘油")
    dup = Ingredient(inci_name="⚫ GLYCERIN", cn_name="⚫ GLYCERIN")
    solo = Ingredient(inci_name="⚫PROPYLENE GLYCOL⚫", cn_name="⚫PROPYLENE GLYCOL⚫")
    session.add_all([keep, dup, solo])
    session.flush()
    stats = run_cleanup(session, seed=SEED, aliases=ALIASES)
    session.commit()
    rows = {r.inci_name: r.cn_name for r in session.query(Ingredient).all()}
    assert rows == {"GLYCERIN": "甘油", "PROPYLENE GLYCOL": "丙二醇"}
    assert stats["merged"] == 1 and stats["renamed"] == 1


# —— 斜杠在括号内：混配不拆 ——

def test_slash_inside_parens_not_split(session):
    """(PALMITIC ACID/ETHYLHEXANOIC ACID) DEXTRIN：斜杠在括号内是混配酯，不拆成 PALMITIC ACID。"""
    session.add(Ingredient(inci_name="(PALMITIC ACID/ETHYLHEXANOIC ACID) DEXTRIN",
                           cn_name="(PALMITIC ACID/ETHYLHEXANOIC ACID) DEXTRIN"))
    session.flush()
    stats = run_cleanup(session, seed={"map": {
        "PALMITIC ACID": {"cn_name": "棕榈酸", "iecic_serial": "00041"}}}, aliases={})
    session.commit()
    row = session.query(Ingredient).one()
    assert row.inci_name == "(PALMITIC ACID/ETHYLHEXANOIC ACID) DEXTRIN"
    assert not any("slash-one" in line for line in stats["merge_log"])


# —— merge-conflict 日志（上轮审查 minor 修复） ——

def test_merge_conflict_link_deletion_logged(session):
    """同一产品同时挂了重复行与保留行：多余链接删除必须记 merge-conflict 日志。"""
    keep = Ingredient(inci_name="GLYCERIN", cn_name="甘油")
    dup = Ingredient(inci_name="⚫ GLYCERIN", cn_name="⚫ GLYCERIN")
    session.add_all([keep, dup])
    session.flush()
    p = Product(name="产品X", brand="测试牌")
    session.add(p)
    session.flush()
    session.add_all([
        ProductIngredient(product_id=p.id, ingredient_id=keep.id, position=1, is_trace=False),
        ProductIngredient(product_id=p.id, ingredient_id=dup.id, position=2, is_trace=False),
    ])
    session.flush()
    stats = run_cleanup(session, seed=SEED, aliases=ALIASES)
    session.commit()
    links = session.query(ProductIngredient).filter_by(product_id=p.id).all()
    assert len(links) == 1 and links[0].ingredient_id == keep.id
    assert stats["merge_conflicts"] == 1
    line = next(l for l in stats["merge_log"] if "merge-conflict" in l)
    assert f"#{dup.id}" in line and f"#{keep.id}" in line and f"product_id={p.id}" in line


def test_round2_idempotent(session):
    """第二轮规则幂等：跑两遍，第二遍零改动。"""
    session.add_all([
        Ingredient(inci_name="⚫ GLYCERIN", cn_name="⚫ GLYCERIN"),
        Ingredient(inci_name="TRIDECETH 3", cn_name="TRIDECETH 3"),
        Ingredient(inci_name="CERAMIDE 6-II", cn_name="CERAMIDE 6-II"),
        Ingredient(inci_name="CL 42090 BLUE 1", cn_name="CL 42090 BLUE 1"),
    ])
    session.flush()
    s1 = run_cleanup(session, seed=SEED, aliases=ALIASES)
    session.commit()
    s2 = run_cleanup(session, seed=SEED, aliases=ALIASES)
    session.commit()
    assert (s1["renamed"], s1["merged"]) == (4, 0)
    assert (s2["renamed"], s2["merged"], s2["backfilled"]) == (0, 0, 0)
    assert (s2["cn_synced"], s2["cn_tail_cleaned"], s2["bilingual"]) == (0, 0, 0)
