"""product_dedup 测试：成分规范键、重复判据（含不误判）、合并改指完整性、幂等、品牌归一。"""

from datetime import date

import pytest
from sqlalchemy import text

from app.models.ingredient import Ingredient
from app.models.product import PricePoint, Product, ProductClaim, ProductIngredient
from data.loaders import product_dedup as pd

IECIC = {"WATER": "水", "GLYCERIN": "甘油", "ALCOHOL DENAT.": "变性乙醇",
         "NIACINAMIDE": "烟酰胺", "PANTHENOL": "泛醇", "CARBOMER": "卡波姆",
         "DIMETHICONE": "聚二甲基硅氧烷", "PHENOXYETHANOL": "苯氧乙醇",
         "TOCOPHEROL": "生育酚", "RETINOL": "视黄醇", "SQUALANE": "角鲨烷",
         "CERAMIDE NP": "神经酰胺 NP", "ASCORBIC ACID": "抗坏血酸",
         "XANTHAN GUM": "黄原胶", "CETEARYL ALCOHOL": "鲸蜡硬脂醇"}


def _ing(session, inci, cn=None):
    ing = session.query(Ingredient).filter_by(inci_name=inci).one_or_none()
    if ing is None:
        ing = Ingredient(inci_name=inci, cn_name=cn or inci)
        session.add(ing)
        session.flush()
    return ing


def _prod(session, name, brand, ings, positioned=True, url="", **kw):
    p = Product(name=name, brand=brand, source_url=url, **kw)
    session.add(p)
    session.flush()
    for i, ing in enumerate(ings, 1):
        session.add(ProductIngredient(product_id=p.id, ingredient_id=ing.id,
                                      position=i if positioned else None,
                                      is_trace=False))
    session.flush()
    return p


def _index(session):
    return pd.collect_product_index(session, IECIC)


class TestIngredientKey:
    def test_iecic_mapping_with_trailing_dot_variant(self):
        # 库里 INCI 不带结尾点，IECIC 键带点（ALCOHOL DENAT.），两边都要归一到变性乙醇
        assert pd.ingredient_key("ALCOHOL DENAT", "ALCOHOL DENAT", IECIC) == "变性乙醇"
        assert pd.ingredient_key("ALCOHOL DENAT.", "ALCOHOL DENAT.", IECIC) == "变性乙醇"

    def test_cn_stub_matches_inci_row(self):
        # 盖德中文 stub 行与 INCI 行规范键一致 → 中英文产品成分才能对齐
        assert pd.ingredient_key("甘油", "甘油", IECIC) == \
            pd.ingredient_key("GLYCERIN", "甘油", IECIC)

    def test_unknown_inci_fallback(self):
        assert pd.ingredient_key("XY-NEW", "XY-NEW", IECIC) == "INCI:XY-NEW"


class TestFindDuplicateEdges:
    def test_cross_lang_duplicate_detected(self, session):
        base = [_ing(session, i) for i in
                ["WATER", "GLYCERIN", "NIACINAMIDE", "PANTHENOL", "CARBOMER",
                 "DIMETHICONE", "PHENOXYETHANOL", "TOCOPHEROL", "SQUALANE",
                 "XANTHAN GUM", "CETEARYL ALCOHOL"]]
        cn_row = _prod(session, "某品牌修护精华乳", "适乐肤", base, positioned=False)
        en_row = _prod(session, "CeraVe Repair Serum", "适乐肤", base,
                       url="https://incidecoder.com/products/x")
        edges = pd.find_duplicate_edges(_index(session))
        kinds = {(e.a, e.b) for e in edges}
        assert (cn_row.id, en_row.id) in kinds
        assert all(e.kind == "cross_lang" for e in edges)

    def test_similar_but_different_products_not_merged(self, session):
        """同系列不同产品（配方基底重合但 J<0.9 且名称无对应）不得报重复。"""
        shared = [_ing(session, i) for i in
                  ["WATER", "GLYCERIN", "NIACINAMIDE", "PANTHENOL", "CARBOMER",
                   "DIMETHICONE", "PHENOXYETHANOL", "TOCOPHEROL"]]
        extra_a = [_ing(session, i) for i in ["SQUALANE", "RETINOL", "CERAMIDE NP"]]
        extra_b = [_ing(session, i) for i in ["ASCORBIC ACID", "XANTHAN GUM",
                                              "CETEARYL ALCOHOL"]]
        _prod(session, "某牌抗老精华", "理肤泉", shared + extra_a, positioned=False)
        _prod(session, "La Roche-Posay Vitamin C Serum", "理肤泉", shared + extra_b)
        # J = 8/14 ≈ 0.57，不应产生任何边
        assert pd.find_duplicate_edges(_index(session)) == []

    def test_short_formula_collision_not_merged(self, session):
        """短配方（<11 成分）即使全同也不合并：同系列洁面短配方易撞车。"""
        base = [_ing(session, i) for i in ["WATER", "GLYCERIN", "CARBOMER"]]
        _prod(session, "某洁面", "理肤泉", base, positioned=False)
        _prod(session, "La Roche-Posay Cleanser", "理肤泉", base)
        assert pd.find_duplicate_edges(_index(session)) == []

    def test_mutual_best_only(self, session):
        """两个中文行争同一个英文行时，只接受分数最高的一对。"""
        shared = [_ing(session, i) for i in
                  ["WATER", "GLYCERIN", "NIACINAMIDE", "PANTHENOL", "CARBOMER",
                   "DIMETHICONE", "PHENOXYETHANOL", "TOCOPHEROL", "SQUALANE",
                   "XANTHAN GUM", "CETEARYL ALCOHOL"]]
        en = _prod(session, "La Roche-Posay Micellar Water", "理肤泉", shared)
        cn1 = _prod(session, "理肤泉修护卸妆液", "理肤泉", shared, positioned=False)
        extra = _ing(session, "RETINOL")
        cn2 = _prod(session, "理肤泉补水卸妆液", "理肤泉", shared + [extra],
                    positioned=False)  # 多一个成分 → J 更低
        edges = pd.find_duplicate_edges(_index(session))
        assert [(e.a, e.b) for e in edges] == [(cn1.id, en.id)]

    def test_en_en_relist_detected_but_shade_variant_not(self, session):
        """换 slug/笔误重收录合并；(Rose Gold) vs (Pure Gold) 色号不同不合并。"""
        f1 = [_ing(session, i) for i in
              ["WATER", "GLYCERIN", "NIACINAMIDE", "PANTHENOL", "CARBOMER",
               "DIMETHICONE", "PHENOXYETHANOL", "TOCOPHEROL", "SQUALANE",
               "XANTHAN GUM", "CETEARYL ALCOHOL", "RETINOL"]]
        f2 = [_ing(session, i) for i in
              ["WATER", "GLYCERIN", "NIACINAMIDE", "PANTHENOL", "CARBOMER",
               "DIMETHICONE", "PHENOXYETHANOL", "TOCOPHEROL", "SQUALANE",
               "XANTHAN GUM", "CETEARYL ALCOHOL", "ASCORBIC ACID"]]
        _prod(session, "Shiseido Illuminator (Rose Gold)", "资生堂", f1)
        _prod(session, "Shiseido Illuminator (Pure Gold)", "资生堂", f1)
        a = _prod(session, "La Roche-Posay Effaclar Medicated Acne Face Wash",
                  "理肤泉", f2)
        b = _prod(session, "La Roche-Posay Effaclear Medicated Acne Face Wash",
                  "理肤泉", f2)
        edges = pd.find_duplicate_edges(_index(session))
        assert [(e.a, e.b) for e in edges] == [(a.id, b.id)]
        assert edges[0].kind == "same_lang"

    def test_same_product_name_rules(self):
        assert pd.same_product_name("CeraVe Cream（cerave-cream-2）", "CeraVe Cream")
        assert pd.same_product_name("Effaclar Effaclar Gel", "Effaclar Gel")  # 词重复
        assert pd.same_product_name("CeraVe Mosturising Cream",
                                    "CeraVe Moisturizing Cream")  # 笔误 ed=2
        assert not pd.same_product_name("Illuminator (Rose Gold)",
                                        "Illuminator (Pure Gold)")
        assert not pd.same_product_name("Day Cream Normal Skin", "Day Cream Dry Skin")
        assert not pd.same_product_name("Lotion Intense Moist", "Lotion Fresh Moist")
        assert not pd.same_product_name("Firming Cream", "Firming Cream Enriched")
        # (Europe) 无连字符不是 slug，是地区版语义标注 → 不合并（v1 曾误剥，见模块 docstring）
        assert not pd.same_product_name("CeraVe Moisturising Cream (Europe)",
                                        "CeraVe Moisturizing Cream")
        # 含连字符的地区 slug 仍是 slug，剥掉后名称一致
        assert pd.same_product_name(
            "CeraVe Moisturizing Lotion（cerave-feuchtigkeitslotion-eu-version）",
            "CeraVe Moisturizing Lotion")


class TestMergeProducts:
    def _fixture(self, session):
        inci = {n: _ing(session, n) for n in
                ["WATER", "GLYCERIN", "NIACINAMIDE", "PANTHENOL"]}
        cn_stub = _ing(session, "甘油", "甘油")  # 盖德中文 stub，与 GLYCERIN 规范键相同
        keeper = _prod(session, "CeraVe Vitamin C Serum", "适乐肤",
                       [inci["WATER"], inci["GLYCERIN"], inci["NIACINAMIDE"]],
                       url="https://incidecoder.com/products/cerave-vc")
        dup = _prod(session, "适乐肤VC精华乳", "适乐肤",
                    [inci["WATER"], cn_stub, inci["NIACINAMIDE"], inci["PANTHENOL"]],
                    positioned=False, nmpa_id="国妆网备进字（沪）2021000001",
                    category="精华")
        session.add(ProductClaim(product_id=dup.id, claim="提亮"))
        session.add(PricePoint(product_id=dup.id, date=date(2026, 1, 1),
                               price=99.0, source="manual", is_manual=True))
        session.flush()
        return keeper, dup, inci["PANTHENOL"]

    def test_merge_moves_fk_and_fills_fields(self, session):
        keeper, dup, panthenol = self._fixture(session)
        detail = pd.merge_products(session, keeper.id, dup.id, 1.0, IECIC)
        session.commit()
        assert detail["filled_fields"]["nmpa_id"] == "国妆网备进字（沪）2021000001"
        assert detail["filled_fields"]["category"] == "精华"
        assert detail["fk_moved"]["product_claims"] == 1
        assert detail["fk_moved"]["price_points"] == 1
        # dup 独有的 PANTHENOL 不搬入 keeper，计数记日志
        assert detail["dup_only_ingredients_dropped"] == 1
        k_nmpa = session.execute(text(
            "SELECT nmpa_id FROM products WHERE id=:i"),
            dict(i=keeper.id)).scalar_one()
        assert k_nmpa == "国妆网备进字（沪）2021000001"
        assert session.execute(text("SELECT COUNT(*) FROM products WHERE id=:i"),
                               dict(i=dup.id)).scalar_one() == 0
        q = lambda t: session.execute(text(
            f"SELECT COUNT(*) FROM {t} WHERE product_id=:i"),
            dict(i=keeper.id)).scalar_one()
        assert q("product_claims") == 1 and q("price_points") == 1
        assert session.execute(text(
            "SELECT COUNT(*) FROM product_ingredients WHERE product_id=:i"),
            dict(i=dup.id)).scalar_one() == 0
        # keeper 成分表不变（3 条，未混入中文 stub）
        assert session.execute(text(
            "SELECT COUNT(*) FROM product_ingredients WHERE product_id=:i"),
            dict(i=keeper.id)).scalar_one() == 3
        # merge_log 落了一条可审计记录
        row = session.execute(text(
            "SELECT kind, keeper_id, dup_id, dup_name FROM merge_log")).one()
        assert row == ("merge", keeper.id, dup.id, "适乐肤VC精华乳")

    def test_merge_conflict_keeps_keeper(self, session):
        keeper, dup, _ = self._fixture(session)
        keeper.nmpa_id = "国妆网备进字（沪）2099999999"
        session.flush()
        detail = pd.merge_products(session, keeper.id, dup.id, 1.0, IECIC)
        session.commit()
        assert session.execute(text("SELECT nmpa_id FROM products WHERE id=:i"),
                               dict(i=keeper.id)).scalar_one() == \
            "国妆网备进字（沪）2099999999"
        assert "nmpa_id" in detail["conflicts"]

    def test_merge_fills_conc_and_profile_columns(self, session):
        """conc_*（浓度推断）与盖德画像列（safety_risk/is_active/purpose）：
        keeper 空则补，冲突保留 keeper（v2 修复，v1 曾随删行静默丢失）。"""
        w = _ing(session, "WATER")
        g = _ing(session, "GLYCERIN", "甘油")
        g_cn = _ing(session, "甘油", "甘油")
        keeper = _prod(session, "CeraVe Serum", "适乐肤", [w, g])
        dup = _prod(session, "适乐肤精华", "适乐肤", [w, g_cn], positioned=False)
        krow_w, krow_g = session.query(ProductIngredient).filter_by(
            product_id=keeper.id).order_by(ProductIngredient.id).all()
        drow_w, drow_g = session.query(ProductIngredient).filter_by(
            product_id=dup.id).order_by(ProductIngredient.id).all()
        # keeper 的 WATER 行已有一个推断值 → 冲突保留；GLYCERIN 行全空 → 从 dup 补
        krow_w.conc_low = 40.0
        drow_w.conc_low, drow_w.conc_high = 35.0, 55.0
        drow_g.conc_low, drow_g.conc_high, drow_g.conc_confidence = 10.0, 20.0, 0.9
        drow_g.safety_risk, drow_g.is_active, drow_g.purpose = "1", True, "保湿剂"
        session.flush()
        detail = pd.merge_products(session, keeper.id, dup.id, 1.0, IECIC)
        session.commit()
        filled = {(f["keeper_pi_id"], f["field"]): f["value"]
                  for f in detail["pi_filled"]}
        assert (krow_g.id, "conc_low") in filled
        assert (krow_w.id, "conc_low") not in filled       # 冲突不补
        assert (krow_w.id, "conc_high") in filled          # keeper 空的仍补
        assert detail["pi_conflicts"] == 1
        rows = session.execute(text(
            "SELECT id, conc_low, conc_high, conc_confidence, safety_risk,"
            " is_active, purpose FROM product_ingredients WHERE product_id=:k"
            " ORDER BY id"), dict(k=keeper.id)).all()
        by_id = {r.id: r for r in rows}
        assert by_id[krow_w.id].conc_low == 40.0           # keeper 原值保留
        assert by_id[krow_w.id].conc_high == 55.0
        assert by_id[krow_g.id].conc_low == 10.0
        assert by_id[krow_g.id].conc_confidence == 0.9
        assert by_id[krow_g.id].safety_risk == "1"
        assert by_id[krow_g.id].purpose == "保湿剂"


    def test_merge_idempotent(self, session):
        keeper, dup, _ = self._fixture(session)
        assert pd.merge_products(session, keeper.id, dup.id, 1.0, IECIC) is not None
        session.commit()
        # 第二次：dup 已进 merge_log，跳过；即便产品行已删也不报错
        assert pd.merge_products(session, keeper.id, dup.id, 1.0, IECIC) is None
        assert session.execute(text(
            "SELECT COUNT(*) FROM merge_log WHERE kind='merge'")).scalar_one() == 1

    def test_merge_reassigns_ingredients_when_keeper_empty(self, session):
        ing = _ing(session, "WATER")
        keeper = _prod(session, "CeraVe Toner", "适乐肤", [])
        dup = _prod(session, "适乐肤化妆水", "适乐肤", [ing], positioned=False)
        detail = pd.merge_products(session, keeper.id, dup.id, 1.0, IECIC)
        session.commit()
        assert detail["fk_moved"]["product_ingredients"] == 1
        assert session.execute(text(
            "SELECT COUNT(*) FROM product_ingredients WHERE product_id=:i"),
            dict(i=keeper.id)).scalar_one() == 1

    def test_dry_run_writes_nothing(self, session):
        keeper, dup, _ = self._fixture(session)
        session.commit()  # fixture 落库，dry-run 后便于校验零写入
        detail = pd.merge_products(session, keeper.id, dup.id, 1.0, IECIC,
                                   dry_run=True)
        assert detail is not None
        assert session.get(Product, dup.id) is not None
        assert session.get(Product, keeper.id).nmpa_id is None
        assert session.execute(text(
            "SELECT COUNT(*) FROM merge_log WHERE kind='merge'")).scalar_one() == 0


class TestNormalizeBrands:
    def test_dual_name_normalized_to_majority(self, session):
        _prod(session, "理肤泉 B5 霜", "理肤泉 La Roche-Posay", [])
        for i in range(3):
            _prod(session, f"理肤泉产品{i}", "理肤泉", [])
        actions = pd.normalize_brands(session)
        session.commit()
        assert actions[0]["brand_to"] == "理肤泉"
        brands = {b for (b,) in session.execute(text("SELECT brand FROM products"))}
        assert brands == {"理肤泉"}
        # 幂等：再跑一次无动作
        assert pd.normalize_brands(session) == []

    def test_dual_name_without_majority_untouched(self, session):
        _prod(session, "OLAY 小白瓶", "OLAY 玉兰油", [])
        _prod(session, "SK-II 神仙水", "SK-II", [])
        assert pd.normalize_brands(session) == []


class TestRepairFromBackup:
    """--repair 补救：从备份库把已合并 dup 丢失的 conc_*/画像列补回 keeper，幂等。"""

    def _backup_db(self, tmp_path, dup_id=900):
        import sqlite3
        path = tmp_path / "backup.db"
        con = sqlite3.connect(path)
        con.executescript("""
        CREATE TABLE ingredients (id INTEGER PRIMARY KEY, inci_name, cn_name);
        CREATE TABLE product_ingredients (
            id INTEGER PRIMARY KEY, product_id, ingredient_id, position, is_trace,
            disclosed_conc, conc_low, conc_high, conc_confidence,
            safety_risk, is_active, purpose);
        INSERT INTO ingredients VALUES (1, 'GLYCERIN', '甘油');
        INSERT INTO product_ingredients
            (id, product_id, ingredient_id, position, is_trace, disclosed_conc,
             conc_low, conc_high, conc_confidence, safety_risk, is_active, purpose)
        VALUES (1, %d, 1, NULL, 0, NULL, 10.0, 20.0, 0.9, '1', 1, '保湿剂');
        """ % dup_id)
        con.commit()
        con.close()
        return path

    def test_repair_fills_and_is_idempotent(self, session, tmp_path):
        g = _ing(session, "GLYCERIN", "甘油")
        g_cn = _ing(session, "甘油", "甘油")  # dup 侧中文 stub，规范键相同
        keeper = _prod(session, "CeraVe Serum", "适乐肤", [g])
        session.execute(text(
            "INSERT INTO merge_log (kind, keeper_id, dup_id, dup_name, created_at)"
            " VALUES ('merge', :k, 900, '适乐肤精华', '2026-08-09T00:00:00')"),
            dict(k=keeper.id))
        session.commit()
        backup = self._backup_db(tmp_path)
        krow_id = session.execute(text(
            "SELECT id FROM product_ingredients WHERE product_id=:k"),
            dict(k=keeper.id)).scalar_one()

        report = pd.repair_from_backup(session, backup, IECIC)
        session.commit()
        assert report == [{"dup_id": 900, "keeper_id": keeper.id, "skipped": False,
                           "fills": 6, "conflicts": 0}]
        row = session.execute(text(
            "SELECT conc_low, conc_high, conc_confidence, safety_risk, is_active,"
            " purpose FROM product_ingredients WHERE id=:i"),
            dict(i=krow_id)).one()
        assert row == (10.0, 20.0, 0.9, "1", 1, "保湿剂")
        assert session.execute(text(
            "SELECT COUNT(*) FROM merge_log WHERE kind='repair'")).scalar_one() == 1

        # 幂等：重跑跳过，数据不变
        report2 = pd.repair_from_backup(session, backup, IECIC)
        assert report2[0]["skipped"] and report2[0]["fills"] == 0
        assert session.execute(text(
            "SELECT COUNT(*) FROM merge_log WHERE kind='repair'")).scalar_one() == 1

    def test_repair_dry_run_writes_nothing(self, session, tmp_path):
        g = _ing(session, "GLYCERIN", "甘油")
        keeper = _prod(session, "CeraVe Serum", "适乐肤", [g])
        session.execute(text(
            "INSERT INTO merge_log (kind, keeper_id, dup_id, dup_name, created_at)"
            " VALUES ('merge', :k, 900, '适乐肤精华', '2026-08-09T00:00:00')"),
            dict(k=keeper.id))
        session.commit()
        report = pd.repair_from_backup(session, self._backup_db(tmp_path), IECIC,
                                       dry_run=True)
        assert report[0]["fills"] == 6
        assert session.execute(text(
            "SELECT conc_low FROM product_ingredients WHERE product_id=:k"),
            dict(k=keeper.id)).scalar_one() is None
        assert session.execute(text(
            "SELECT COUNT(*) FROM merge_log WHERE kind='repair'")).scalar_one() == 0


@pytest.mark.parametrize("a,b,expect", [
    ("适乐肤", "适乐肤", True),
])
def test_brand_group(a, b, expect):
    assert (pd.brand_group(a) == pd.brand_group(b)) is expect
