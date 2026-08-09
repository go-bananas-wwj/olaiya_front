"""斜杠/括号双语成分名规范化测试（resolve_bilingual + run_cleanup 集成）。

规则要点（data/loaders/inci_cn_loader.py 模块 docstring）：
- 全名精确命中 IECIC 映射（共聚物 CAPRYLIC/CAPRIC ...）不动；
- 恰一段命中取命中段的 IECIC 规范键（含去括号派生键），两段都命中取非 CI 号段并记歧义；
- 护栏：混配（拉丁双名/≥3 段单命中）、同物种不同部位（共享物质词）、PEG/PPG 共聚物、
  多成分拼接括号一律保持原样。
"""

import pytest

from data.loaders.inci_cn_loader import InciResolver, resolve_bilingual, run_cleanup
from app.models.ingredient import Ingredient
from app.models.product import Product, ProductIngredient

SEED = {"map": {
    "PARFUM": {"cn_name": "香精", "iecic_serial": "00001"},
    "FRAGRANCE": {"cn_name": "（日用）香精", "iecic_serial": "00002"},
    "TITANIUM DIOXIDE": {"cn_name": "二氧化钛", "iecic_serial": "00003"},
    "CI 77891": {"cn_name": "CI 77891", "iecic_serial": "00004"},
    "CERA ALBA": {"cn_name": "白蜂蜡", "iecic_serial": "00005"},
    "BEESWAX": {"cn_name": "蜂蜡", "iecic_serial": "00006"},
    "YEAST EXTRACT": {"cn_name": "酵母提取物", "iecic_serial": "00007"},
    "WATER": {"cn_name": "水", "iecic_serial": "00008"},
    "CAPRYLIC/CAPRIC TRIGLYCERIDE": {"cn_name": "辛酸/癸酸甘油三酯", "iecic_serial": "00009"},
    "BUTYROSPERMUM PARKII (SHEA) BUTTER": {"cn_name": "牛油果树果脂", "iecic_serial": "00010"},
    "GALACTOMYCES FERMENT FILTRATE": {"cn_name": "半乳糖酵母样菌发酵产物滤液",
                                      "iecic_serial": "00011"},
    "ROYAL JELLY": {"cn_name": "蜂王浆", "iecic_serial": "00012"},
    "ROYAL JELLY EXTRACT": {"cn_name": "蜂王浆提取物", "iecic_serial": "00013"},
    "ACACIA SENEGAL GUM": {"cn_name": "阿拉伯胶树（ACACIA SENEGAL）胶", "iecic_serial": "00014"},
    "UNDARIA PINNATIFIDA EXTRACT": {"cn_name": "裙带菜提取物", "iecic_serial": "00015"},
    "MEL": {"cn_name": "蜂蜜", "iecic_serial": "00016"},
    "HONEY": {"cn_name": "蜂（Apis mellifera）蜜", "iecic_serial": "00017"},
}}

RESOLVER = InciResolver(SEED["map"])


@pytest.mark.parametrize("raw,expected,tag_prefix", [
    # —— 斜杠：恰一段命中（含去括号派生键） ——
    ("BUTYROSPERMUM PARKII BUTTER/SHEA BUTTER",
     "BUTYROSPERMUM PARKII (SHEA) BUTTER", "slash-one"),
    ("FAEX EXTRACT/YEAST EXTRACT", "YEAST EXTRACT", "slash-one"),
    # —— 斜杠：两段都命中，CI 号让位 INCI 名 ——
    ("CI 77891/TITANIUM DIOXIDE", "TITANIUM DIOXIDE", "slash-ambiguous"),
    ("TITANIUM DIOXIDE/CI 77891", "TITANIUM DIOXIDE", "slash-ambiguous"),  # 顺序无关
    # —— 斜杠：两段都命中且都非 CI，取首段并记歧义 ——
    ("PARFUM/FRAGRANCE", "PARFUM", "slash-ambiguous"),
    ("CERA ALBA / BEESWAX", "CERA ALBA", "slash-ambiguous"),
    # —— 斜杠：双段解析到同键（[NANO] 变体归一） ——
    ("TITANIUM DIOXIDE (NANO)/TITANIUM DIOXIDE", "TITANIUM DIOXIDE", "slash-same"),
    # —— 斜杠：≥3 段须 ≥2 命中（多语同物） ——
    ("CERA ALBA / BEESWAX / CIRE DABEILLE", "CERA ALBA", "slash-ambiguous"),
    ("MEL/HONEY/MIEL", "MEL", "slash-ambiguous"),
    # —— 括号 ——
    ("FRAGRANCE (PARFUM)", "FRAGRANCE", "paren-ambiguous"),       # 主段优先
    ("TITANIUM DIOXIDE (CI 77891)", "TITANIUM DIOXIDE", "paren-ambiguous"),
    ("TITANIUM DIOXIDE (NANO)", "TITANIUM DIOXIDE [NANO]", "paren-nano"),
    ("PITERA (GALACTOMYCES FERMENT FILTRATE)", "GALACTOMYCES FERMENT FILTRATE", "paren-inner"),
    ("BUTYROSPERMUM PARKII (SHEA BUTTER)", "BUTYROSPERMUM PARKII (SHEA) BUTTER", "paren-shift"),
    ("WATER (LA ROCHE-POSAY PREBIOTIC THERMAL WATER)", "WATER", "paren-main"),
])
def test_bilingual_normalized(raw, expected, tag_prefix):
    new_name, tag = resolve_bilingual(raw, RESOLVER)
    assert new_name == expected
    assert tag is not None and tag.startswith(tag_prefix)


@pytest.mark.parametrize("raw", [
    # 全名精确命中：共聚物/合法斜杠名单条映射，不动
    "CAPRYLIC/CAPRIC TRIGLYCERIDE",
    # ≥3 段且 <2 命中：藻类混配/多单体共聚物，不动
    "EUCHEUMA SERRA/SACCHARINA ANGUSTATA/UNDARIA PINNATIFIDA EXTRACT",
    "CAPRYLIC/CAPRIC/MYRISTIC/STEARIC TRIGLYCERIDE",
    # 非命中段疑似拉丁双名（另一物种混配），不动
    "SACCHARINA ANGUSTATA/UNDARIA PINNATIFIDA EXTRACT",
    # 非命中段是命中键的词级前缀（通用名/具体名），不动
    "ACACIA SENEGAL/ACACIA SENEGAL GUM",
    # 两段都命中但共享物质词：同物种不同形态（蜂王浆 vs 蜂王浆提取物），不动
    "ROYAL JELLY / ROYAL JELLY EXTRACT",
    # PEG/PPG 段是共聚物命名，不是双语
    "PPG-7/PEG-30 PHYTOSTEROL",
    # 括号主段含拼接符：多成分串，不动
    "IRON OXIDES (CI 77491),IRON OXIDES (CI 77492)",
    # 括号两段都查不到且移位也不命中，不动
    "ANTHEMIS NOBILIS (CHAMOMILE)",
    # 未映射单名，不动
    "AVOBENZONE",
])
def test_undecidable_untouched(raw):
    new_name, tag = resolve_bilingual(raw, RESOLVER)
    assert tag is None
    assert new_name == raw


def test_derived_key_ambiguity_excluded():
    """去括号派生键多条目中文名不一致时弃用，绝不猜。"""
    mapping = {
        "HYDROGENATED POLY(C6-14 OLEFIN)": {"cn_name": "氢化聚（C6-14 烯烃）"},
        "HYDROGENATED POLY(C6-20 OLEFIN)": {"cn_name": "氢化聚（C6-20 烯烃）"},
        "TITANIUM DIOXIDE": {"cn_name": "二氧化钛"},
    }
    r = InciResolver(mapping)
    assert r.resolve("HYDROGENATED POLY") is None
    assert r.resolve("HYDROGENATED POLY(C6-20 OLEFIN)") == "HYDROGENATED POLY(C6-20 OLEFIN)"


def test_trailing_period_variant():
    """结尾句点变体命中 IECIC 键（ALCOHOL DENAT -> ALCOHOL DENAT.），不造翻译。"""
    r = InciResolver({"ALCOHOL DENAT.": {"cn_name": "变性乙醇"}})
    assert r.resolve("ALCOHOL DENAT") == "ALCOHOL DENAT."
    assert r.resolve("ALCOHOL DENAT.") == "ALCOHOL DENAT."
    assert r.resolve("XY-UNKNOWN") is None


def _mk_product(session, name, inci_list):
    p = Product(name=name, brand="测试牌")
    session.add(p)
    session.flush()
    for i, inci in enumerate(inci_list, 1):
        ing = session.query(Ingredient).filter_by(inci_name=inci).one()
        session.add(ProductIngredient(product_id=p.id, ingredient_id=ing.id,
                                      position=i, is_trace=False))
    session.flush()
    return p


def test_slash_dual_renamed_merged_and_backfilled(session):
    """PARFUM/FRAGRANCE 规范化为 PARFUM 后与既有 PARFUM 行撞名合并，顺带回填中文名。"""
    keep = Ingredient(inci_name="PARFUM", cn_name="PARFUM")
    dup = Ingredient(inci_name="PARFUM/FRAGRANCE", cn_name="PARFUM/FRAGRANCE")
    session.add_all([keep, dup])
    session.flush()
    p1 = _mk_product(session, "产品A", ["PARFUM"])
    p2 = _mk_product(session, "产品B", ["PARFUM/FRAGRANCE"])
    stats = run_cleanup(session, seed=SEED)
    session.commit()
    ings = session.query(Ingredient).filter_by(inci_name="PARFUM").all()
    assert len(ings) == 1
    assert ings[0].cn_name == "香精"
    assert session.query(Ingredient).filter_by(inci_name="PARFUM/FRAGRANCE").count() == 0
    links = session.query(ProductIngredient).filter_by(ingredient_id=keep.id).all()
    assert {l.product_id for l in links} == {p1.id, p2.id}
    assert stats["merged"] == 1
    assert stats["bilingual"] == 1
    assert any(line.startswith("slash-ambiguous") for line in stats["merge_log"])


def test_slash_one_rename_to_iecic_canonical_key(session):
    """恰一段命中：采用 IECIC 规范键（含括号全名）为新 inci_name 并回填。"""
    ing = Ingredient(inci_name="BUTYROSPERMUM PARKII BUTTER/SHEA BUTTER",
                     cn_name="BUTYROSPERMUM PARKII BUTTER/SHEA BUTTER")
    session.add(ing)
    session.flush()
    stats = run_cleanup(session, seed=SEED)
    session.commit()
    assert ing.inci_name == "BUTYROSPERMUM PARKII (SHEA) BUTTER"
    assert ing.cn_name == "牛油果树果脂"
    assert stats["renamed"] == 1 and stats["merged"] == 0


def test_copolymer_full_hit_untouched(session):
    """共聚物全名命中映射：不改名不合并，只回填中文名。"""
    ing = Ingredient(inci_name="CAPRYLIC/CAPRIC TRIGLYCERIDE",
                     cn_name="CAPRYLIC/CAPRIC TRIGLYCERIDE")
    session.add(ing)
    session.flush()
    stats = run_cleanup(session, seed=SEED)
    session.commit()
    assert ing.inci_name == "CAPRYLIC/CAPRIC TRIGLYCERIDE"
    assert ing.cn_name == "辛酸/癸酸甘油三酯"
    assert stats["renamed"] == 0 and stats["merged"] == 0 and stats["bilingual"] == 0


def test_guard_rows_untouched_and_unmapped(session):
    """护栏拦截的形态（混配/同物种不同部位/拼接串）保持原样且仍计未映射。"""
    names = ["SACCHARINA ANGUSTATA/UNDARIA PINNATIFIDA EXTRACT",
             "ROYAL JELLY / ROYAL JELLY EXTRACT",
             "IRON OXIDES (CI 77491),IRON OXIDES (CI 77492)"]
    session.add_all([Ingredient(inci_name=n, cn_name=n) for n in names])
    session.flush()
    stats = run_cleanup(session, seed=SEED)
    session.commit()
    assert session.query(Ingredient).count() == 3
    for n in names:
        row = session.query(Ingredient).filter_by(inci_name=n).one()
        assert row.cn_name == n  # 未命中不猜测
    assert stats["renamed"] == 0 and stats["bilingual"] == 0
    assert stats["unmapped"] == 3


def test_merge_cn_transfer_guard_with_bilingual(session):
    """双语规范化后撞名合并：dup 有手工中文名而 keeper 没有时转移，不丢手工核实名。"""
    keep = Ingredient(inci_name="PARFUM", cn_name="PARFUM")
    dup = Ingredient(inci_name="PARFUM/FRAGRANCE", cn_name="香精（手工核实）")
    session.add_all([keep, dup])
    session.flush()
    stats = run_cleanup(session, seed=SEED)
    session.commit()
    assert session.query(Ingredient).count() == 1
    assert keep.cn_name == "香精（手工核实）"
    assert stats["backfilled"] == 0


def test_bilingual_cleanup_idempotent(session):
    session.add_all([
        Ingredient(inci_name="PARFUM/FRAGRANCE", cn_name="PARFUM/FRAGRANCE"),
        Ingredient(inci_name="CI 77891/TITANIUM DIOXIDE", cn_name="CI 77891/TITANIUM DIOXIDE"),
        Ingredient(inci_name="TITANIUM DIOXIDE (NANO)", cn_name="TITANIUM DIOXIDE (NANO)"),
        Ingredient(inci_name="CI 77891 [NANO]", cn_name="CI 77891 [NANO]"),
        Ingredient(inci_name="AVOBENZONE", cn_name="AVOBENZONE"),
    ])
    session.flush()
    s1 = run_cleanup(session, seed=SEED)
    session.commit()
    s2 = run_cleanup(session, seed=SEED)
    session.commit()
    assert s1["renamed"] == 3 and s1["bilingual"] == 3
    assert (s2["renamed"], s2["merged"], s2["bilingual"], s2["backfilled"]) == (0, 0, 0, 0)
    assert (s2["cn_synced"], s2["cn_tail_cleaned"]) == (0, 0)
    names = {r.inci_name for r in session.query(Ingredient).all()}
    assert names == {"PARFUM", "TITANIUM DIOXIDE", "TITANIUM DIOXIDE [NANO]",
                     "CI 77891 [NANO]", "AVOBENZONE"}
    cn = {r.inci_name: r.cn_name for r in session.query(Ingredient).all()}
    assert cn["PARFUM"] == "香精"
    assert cn["TITANIUM DIOXIDE"] == "二氧化钛"
    assert cn["TITANIUM DIOXIDE [NANO]"] == "二氧化钛"  # [NANO] 形态经去括号回填
    assert cn["CI 77891 [NANO]"] == "CI 77891"  # 官名即编号：回填后不震荡
    assert cn["AVOBENZONE"] == "AVOBENZONE"  # USAN 名未映射，保持原样
