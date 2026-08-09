"""inci_cn_loader 测试：INCI 噪声清洗（[]/<N%/->/EXTRAIT 双语/空白）、撞名合并、cn_name 回填、幂等。"""

import pytest

from data.loaders.inci_cn_loader import normalize_inci, run_cleanup
from app.models.evidence import Evidence
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.models.product import Product, ProductIngredient

SEED = {"map": {
    "GLYCERIN": {"cn_name": "甘油", "iecic_serial": "02421"},
    "BUTYLENE GLYCOL": {"cn_name": "丁二醇", "iecic_serial": "01946"},
    "WATER": {"cn_name": "水", "iecic_serial": "06260"},
    "HORDEUM VULGARE EXTRACT": {"cn_name": "大麦（HORDEUM VULGARE）提取物", "iecic_serial": "00001"},
    "SALICYLIC ACID": {"cn_name": "水杨酸", "iecic_serial": "00002"},
    "CI 77491": {"cn_name": "CI 77491", "iecic_serial": "00003"},  # 着色剂官名即编号
}}


@pytest.mark.parametrize("raw,expected", [
    ("ACETYL GLUCOSAMINE []", "ACETYL GLUCOSAMINE"),          # 空括号后缀
    ("SALICYLIC ACID <2%", "SALICYLIC ACID"),                 # 浓度尾巴
    ("BUTYLENE GLYCOL ->", "BUTYLENE GLYCOL"),                # 箭头尾巴
    ("WATER\\AQUA\\EAU", "WATER"),                            # 英\拉丁\法 三语取英文
    ("WATER\\\\AQUA\\\\EAU", "WATER"),                        # 双反斜杠变体
    ("BEESWAX\\CERA ALBA\\CIRE D'ABEILLE", "BEESWAX"),        # 法语段含撇号
    ("PANTHENOL\\^*", "PANTHENOL"),                           # 垃圾尾巴段
    ("HORDEUM VULGARE EXTRACT\\EXTRAIT D'ORGE", "HORDEUM VULGARE EXTRACT"),
    ("FAEX EXTRACT / YEAST EXTRACT / EXTRAIT DE LEVURE", "FAEX EXTRACT"),   # EXTRAIT 斜杠双语
    ("HORDEUM VULGARE (BARLEY) EXTRACT\\EXTRAIT D'ORGE []",
     "HORDEUM VULGARE (BARLEY) EXTRACT"),                     # 双语 + 空括号叠加
    ("YEAST EXTRACT FAEX EXTRAIT DE LEVURE", "YEAST EXTRACT FAEX"),         # 无分隔 EXTRAIT 尾巴
    ("CI 77266 [NANO]", "CI 77266 [NANO]"),                   # [NANO] 是有效标识，保留
    ("CAPRYLIC/CAPRIC TRIGLYCERIDE", "CAPRYLIC/CAPRIC TRIGLYCERIDE"),       # 正常斜杠名不动
    ("LITHIUM MAGNESIUM SODIUM SILICATE [NANO] / LITHIUM MAGNESIUM",
     "LITHIUM MAGNESIUM SODIUM SILICATE [NANO] / LITHIUM MAGNESIUM"),       # 非 EXTRAIT 斜杠不动
    ("GLYCERIN", "GLYCERIN"),
    ("  DISODIUM   EDTA ", "DISODIUM EDTA"),                  # 空白归一
    ("NIACINAMIDE*", "NIACINAMIDE"),                          # 星号标记尾巴
    ("CAMELLIA SINENSIS LEAF EXTRACT^*", "CAMELLIA SINENSIS LEAF EXTRACT"),  # ^ 标记尾巴
    ("ALOE BARBADENSIS LEAF JUICE POWDER^****", "ALOE BARBADENSIS LEAF JUICE POWDER"),
    ("EXTRAIT D’ORGE\\HORDEUM VULGARE EXTRACT",
     "HORDEUM VULGARE EXTRACT"),                              # 法文在前时取英文段 + 弯引号
])
def test_normalize_inci(raw, expected):
    assert normalize_inci(raw) == expected


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


def test_backfill_cn_name_only_when_hit(session):
    session.add_all([
        Ingredient(inci_name="GLYCERIN", cn_name="GLYCERIN"),
        Ingredient(inci_name="XY-UNKNOWN", cn_name="XY-UNKNOWN"),
    ])
    session.flush()
    stats = run_cleanup(session, seed=SEED)
    session.commit()
    gly = session.query(Ingredient).filter_by(inci_name="GLYCERIN").one()
    assert gly.cn_name == "甘油"
    unk = session.query(Ingredient).filter_by(inci_name="XY-UNKNOWN").one()
    assert unk.cn_name == "XY-UNKNOWN"  # 未命中绝不猜测
    assert stats["backfilled"] == 1
    assert stats["unmapped"] == 1
    assert "XY-UNKNOWN" in stats["unmapped_names"]


def test_existing_chinese_cn_name_not_overwritten(session):
    """已有中文名（手工核实种子）不被映射表覆盖。"""
    session.add(Ingredient(inci_name="GLYCERIN", cn_name="丙三醇（手工）"))
    session.flush()
    stats = run_cleanup(session, seed=SEED)
    session.commit()
    ing = session.query(Ingredient).filter_by(inci_name="GLYCERIN").one()
    assert ing.cn_name == "丙三醇（手工）"
    assert stats["backfilled"] == 0


def test_noise_rows_cleaned_and_merged(session):
    """'BUTYLENE GLYCOL ->' 清洗后与既有 'BUTYLENE GLYCOL' 撞名：合并指向、删重复行。"""
    keep = Ingredient(inci_name="BUTYLENE GLYCOL", cn_name="BUTYLENE GLYCOL")
    dup = Ingredient(inci_name="BUTYLENE GLYCOL ->", cn_name="BUTYLENE GLYCOL ->")
    session.add_all([keep, dup])
    session.flush()
    p1 = _mk_product(session, "产品A", ["BUTYLENE GLYCOL"])
    p2 = _mk_product(session, "产品B", ["BUTYLENE GLYCOL ->"])
    stats = run_cleanup(session, seed=SEED)
    session.commit()
    ings = session.query(Ingredient).filter_by(inci_name="BUTYLENE GLYCOL").all()
    assert len(ings) == 1
    assert ings[0].cn_name == "丁二醇"  # 合并后顺带回填
    assert session.query(Ingredient).filter_by(inci_name="BUTYLENE GLYCOL ->").count() == 0
    links = session.query(ProductIngredient).filter_by(ingredient_id=keep.id).all()
    assert {l.product_id for l in links} == {p1.id, p2.id}
    assert stats["merged"] == 1
    assert any("BUTYLENE GLYCOL ->" in line for line in stats["merge_log"])


def test_merge_skips_existing_product_pair(session):
    """同一产品同时挂了重复行与保留行：改指撞 (product_id, ingredient_id) 时跳过并删除多余链接。"""
    keep = Ingredient(inci_name="WATER", cn_name="水")
    dup = Ingredient(inci_name="WATER\\AQUA\\EAU", cn_name="WATER\\AQUA\\EAU")
    session.add_all([keep, dup])
    session.flush()
    p = Product(name="产品C", brand="测试牌")
    session.add(p)
    session.flush()
    session.add_all([
        ProductIngredient(product_id=p.id, ingredient_id=keep.id, position=1, is_trace=False),
        ProductIngredient(product_id=p.id, ingredient_id=dup.id, position=2, is_trace=False),
    ])
    session.flush()
    stats = run_cleanup(session, seed=SEED)
    session.commit()
    assert session.query(Ingredient).count() == 1
    links = session.query(ProductIngredient).filter_by(product_id=p.id).all()
    assert len(links) == 1  # 重复链接被删除，不残留悬空引用
    assert links[0].ingredient_id == keep.id
    assert stats["merged"] == 1


def test_merge_repoints_efficacy_assertions(session):
    """合并时功效断言的 ingredient_id 也要改指保留行，不能悬空。"""
    keep = Ingredient(inci_name="SALICYLIC ACID", cn_name="SALICYLIC ACID")
    dup = Ingredient(inci_name="SALICYLIC ACID <2%", cn_name="SALICYLIC ACID <2%")
    ev = Evidence(type="paper", title="t", source="s", year=2020,
                  url="https://pubmed.ncbi.nlm.nih.gov/1/", excerpt="e")
    session.add_all([keep, dup, ev])
    session.flush()
    session.add(EfficacyAssertion(ingredient_id=dup.id, efficacy="祛痘", evidence_id=ev.id))
    session.flush()
    run_cleanup(session, seed=SEED)
    session.commit()
    a = session.query(EfficacyAssertion).one()
    assert a.ingredient_id == keep.id
    assert session.query(Ingredient).one().cn_name == "水杨酸"


def test_rename_without_merge_when_no_collision(session):
    """清洗后无撞名：直接改名，不删行。"""
    ing = Ingredient(inci_name="HORDEUM VULGARE EXTRACT\\EXTRAIT D'ORGE",
                     cn_name="HORDEUM VULGARE EXTRACT\\EXTRAIT D'ORGE")
    session.add(ing)
    session.flush()
    stats = run_cleanup(session, seed=SEED)
    session.commit()
    assert session.query(Ingredient).count() == 1
    assert ing.inci_name == "HORDEUM VULGARE EXTRACT"
    assert ing.cn_name == "大麦（HORDEUM VULGARE）提取物"
    assert stats["renamed"] == 1
    assert stats["merged"] == 0


def test_rename_syncs_placeholder_cn_name(session):
    """改名时 cn_name 是旧脏占位名（无中文）：同步为清洗后的 inci_name，不残留 */[] 尾巴。"""
    session.add_all([
        Ingredient(inci_name="PEPTIDES**", cn_name="PEPTIDES**"),
        Ingredient(inci_name="CALOPHYLLUM INOPHYLLUM (TAMANU) SEED OIL []",
                   cn_name="CALOPHYLLUM INOPHYLLUM (TAMANU) SEED OIL []"),
    ])
    session.flush()
    stats = run_cleanup(session, seed=SEED)
    session.commit()
    rows = {r.inci_name: r.cn_name for r in session.query(Ingredient).all()}
    assert rows["PEPTIDES"] == "PEPTIDES"
    assert (rows["CALOPHYLLUM INOPHYLLUM (TAMANU) SEED OIL"]
            == "CALOPHYLLUM INOPHYLLUM (TAMANU) SEED OIL")
    assert stats["cn_synced"] == 2


def test_stale_placeholder_cn_resynced_to_clean_inci(session):
    """历史残留态（inci 已干净、cn 还是旧脏占位，含 EXTRAIT 双语尾巴）：对齐到干净 inci。"""
    ing = Ingredient(inci_name="FAEX", cn_name="FAEX/YEAST EXTRACT/EXTRAIT DE LEVURE")
    session.add(ing)
    session.flush()
    stats = run_cleanup(session, seed=SEED)
    session.commit()
    assert ing.cn_name == "FAEX"
    assert stats["cn_synced"] == 1


def test_chinese_cn_tail_cleaned(session):
    """含中文但带 */^ 尾巴的 cn_name 去尾（如 氢化植物油* → 氢化植物油），不算回填。"""
    ing = Ingredient(inci_name="氢化植物油*", cn_name="氢化植物油*")
    session.add(ing)
    session.flush()
    stats = run_cleanup(session, seed=SEED)
    session.commit()
    assert ing.inci_name == "氢化植物油"
    assert ing.cn_name == "氢化植物油"
    assert stats["cn_tail_cleaned"] == 1
    assert stats["backfilled"] == 0


def test_clean_hand_curated_cn_untouched(session):
    """干净的手工中文名（无尾巴噪声）完全不动。"""
    ing = Ingredient(inci_name="XY-UNKNOWN", cn_name="未知成分（手工核实）")
    session.add(ing)
    session.flush()
    stats = run_cleanup(session, seed=SEED)
    session.commit()
    assert ing.cn_name == "未知成分（手工核实）"
    assert stats["cn_tail_cleaned"] == 0
    assert stats["cn_synced"] == 0


def test_merge_transfers_chinese_cn_from_dup(session):
    """合并守卫：dup 有中文名而 keeper 没有时，dup 的中文名转移给 keeper 再删 dup。"""
    keep = Ingredient(inci_name="BUTYLENE GLYCOL", cn_name="BUTYLENE GLYCOL")
    dup = Ingredient(inci_name="BUTYLENE GLYCOL ->", cn_name="丁二醇（手工核实）")
    session.add_all([keep, dup])
    session.flush()
    stats = run_cleanup(session, seed=SEED)
    session.commit()
    assert session.query(Ingredient).count() == 1
    assert keep.cn_name == "丁二醇（手工核实）"  # 手工名转移过来，不被映射表覆盖
    assert stats["backfilled"] == 0  # 已是中文名，阶段二跳过


def test_merge_keeps_keeper_cn_when_both_chinese(session):
    """keeper 已有中文名时，不取 dup 的中文名（保住 keeper 的手工核实值）。"""
    keep = Ingredient(inci_name="BUTYLENE GLYCOL", cn_name="丁二醇")
    dup = Ingredient(inci_name="BUTYLENE GLYCOL ->", cn_name="丁二醇（另一写法）")
    session.add_all([keep, dup])
    session.flush()
    run_cleanup(session, seed=SEED)
    session.commit()
    assert keep.cn_name == "丁二醇"


def test_run_cleanup_idempotent(session):
    session.add_all([
        Ingredient(inci_name="GLYCERIN", cn_name="GLYCERIN"),
        Ingredient(inci_name="GLYCERIN []", cn_name="GLYCERIN []"),
        Ingredient(inci_name="XY-UNKNOWN", cn_name="XY-UNKNOWN"),
        Ingredient(inci_name="CI 77491", cn_name="CI 77491"),  # 官名即编号：值不变不算回填
    ])
    session.flush()
    s1 = run_cleanup(session, seed=SEED)
    session.commit()
    s2 = run_cleanup(session, seed=SEED)
    session.commit()
    assert (s1["backfilled"], s1["merged"]) == (1, 1)
    assert (s2["backfilled"], s2["merged"], s2["renamed"]) == (0, 0, 0)
    assert (s2["cn_synced"], s2["cn_tail_cleaned"]) == (0, 0)
    assert session.query(Ingredient).count() == 3
    assert session.query(Ingredient).filter_by(inci_name="GLYCERIN").one().cn_name == "甘油"
