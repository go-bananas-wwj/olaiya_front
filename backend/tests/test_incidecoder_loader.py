"""incidecoder_loader 测试：position 真实降序、成分匹配（含水变体归一）、变体拆分、幂等。"""

from data.loaders.incidecoder_loader import load_product
from app.models.ingredient import Ingredient
from app.models.product import Product, ProductIngredient

SAMPLE = {
    "name": "CeraVe Moisturizing Cream",
    "brand": "适乐肤 CeraVe",  # 采集期旧字符串；loader 应按 brand_slug 归一到「适乐肤」
    "brand_slug": "cerave",
    "product_slug": "cerave-moisturizing-cream",
    "ingredients": [
        {"inci_name": "AQUA", "slug": "water", "position": 1},
        {"inci_name": "GLYCERIN", "slug": "glycerin", "position": 2},
        {"inci_name": "CETEARYL ALCOHOL", "slug": "cetearyl-alcohol", "position": 3},
        {"inci_name": "XY-UNKNOWN-NEW", "slug": "xy-unknown-new", "position": 4},
    ],
    "source": {"site": "incidecoder.com",
               "url": "https://incidecoder.com/products/cerave-moisturizing-cream",
               "collected_at": "2026-08-05 13:00:00",
               "note": "成分表为包装标签降序"},
}


def _variant(data, slug, ingredients):
    import copy
    d = copy.deepcopy(data)
    d["product_slug"] = slug
    d["ingredients"] = ingredients
    d["source"] = dict(data["source"], url=f"https://incidecoder.com/products/{slug}")
    return d


def test_load_product_positions_are_real(session):
    p = load_product(session, SAMPLE)
    session.commit()
    assert p.brand == "适乐肤"  # 按 brand_slug 归一到库内主名
    assert p.source_url == SAMPLE["source"]["url"]
    links = (session.query(ProductIngredient).filter_by(product_id=p.id)
             .order_by(ProductIngredient.position).all())
    assert [l.position for l in links] == [1, 2, 3, 4]  # 关键：真实降序位次，不得置 NULL
    assert links[0].ingredient.inci_name == "WATER"  # AQUA 归一到 WATER


def test_load_product_matches_existing_ingredient_case_insensitive(session):
    """库里已有 GLYCERIN（大写 INCI + 中文名）时直接复用，不新建 stub。"""
    session.add(Ingredient(inci_name="GLYCERIN", cn_name="甘油"))
    session.flush()
    load_product(session, SAMPLE)
    session.commit()
    gly = session.query(Ingredient).filter_by(inci_name="GLYCERIN").all()
    assert len(gly) == 1 and gly[0].cn_name == "甘油"


def test_water_variants_canonicalize(session):
    """AQUA / AQUA (WATER) / AQUA/WATER / AQUA/WATER/EAU 全部归一到已有 WATER，不新建 stub。"""
    session.add(Ingredient(inci_name="WATER", cn_name="水"))
    session.flush()
    for inci in ("AQUA", "AQUA (WATER)", "AQUA/WATER", "AQUA/WATER/EAU"):
        data = _variant(SAMPLE, f"cerave-p-{inci.count(' ') + inci.count('/')}",
                        [{"inci_name": inci, "slug": "water", "position": 1}])
        stats = {}
        load_product(session, data, stats=stats)
        assert stats.get("pending_cn", 0) == 0, inci
    session.commit()
    assert session.query(Ingredient).count() == 1
    assert session.query(Ingredient).one().inci_name == "WATER"


def test_non_water_slash_names_not_canonicalized(session):
    """CAPRYLIC/CAPRIC TRIGLYCERIDE 这类斜杠名不得误归一；ROSA ... WATER 也不得归一到 WATER。"""
    session.add(Ingredient(inci_name="WATER", cn_name="水"))
    session.flush()
    data = _variant(SAMPLE, "cerave-p-x", [
        {"inci_name": "CAPRYLIC/CAPRIC TRIGLYCERIDE", "slug": "caprylic-capric-triglyceride", "position": 1},
        {"inci_name": "ROSA DAMASCENA FLOWER WATER", "slug": "rosa-damascena-flower-water", "position": 2},
    ])
    load_product(session, data)
    session.commit()
    assert session.query(Ingredient).filter_by(inci_name="CAPRYLIC/CAPRIC TRIGLYCERIDE").count() == 1
    assert session.query(Ingredient).filter_by(inci_name="ROSA DAMASCENA FLOWER WATER").count() == 1


def test_load_product_new_ingredient_pending_cn(session):
    """匹配不到的新成分：inci_name 如实填（大写归一），cn_name 暂以 INCI 填充并计数待中文化。"""
    stats = {}
    load_product(session, SAMPLE, stats=stats)
    session.commit()
    stub = session.query(Ingredient).filter_by(inci_name="XY-UNKNOWN-NEW").one()
    assert stub.cn_name == "XY-UNKNOWN-NEW"  # 不机翻，后续专门任务补中文化
    assert stats["pending_cn"] >= 1
    assert "XY-UNKNOWN-NEW" in stats["pending_cn_names"]


def test_load_product_idempotent(session):
    load_product(session, SAMPLE)
    session.commit()
    load_product(session, SAMPLE)
    session.commit()
    assert session.query(Product).filter_by(brand="适乐肤").count() == 1
    assert session.query(ProductIngredient).count() == 4
    assert session.query(Ingredient).filter_by(inci_name="WATER").count() == 1


def test_load_product_dedupes_existing_product_by_normalized_name(session):
    """已有同品牌同名（大小写/空白差异）且无来源页的产品：跨源合并，补写 source_url。"""
    ing = Ingredient(inci_name="WATER", cn_name="水")
    existing = Product(name="cerave moisturizing cream", brand="适乐肤")
    session.add_all([ing, existing])
    session.flush()
    session.add(ProductIngredient(product_id=existing.id, ingredient_id=ing.id,
                                  position=None, is_trace=False))
    session.commit()
    p = load_product(session, SAMPLE)
    session.commit()
    assert p.id == existing.id
    assert p.source_url == SAMPLE["source"]["url"]  # 原本为空 → 补写
    assert session.query(Product).count() == 1


def test_variants_become_separate_products(session):
    """同名不同 slug 的配方变体：分别建档，成分表与 source_url 必须同源一致。"""
    base_ings = [{"inci_name": "WATER", "slug": "water", "position": 1},
                 {"inci_name": "GLYCERIN", "slug": "glycerin", "position": 2},
                 {"inci_name": "CARBOMER", "slug": "carbomer", "position": 3}]
    v5_ings = [{"inci_name": "WATER", "slug": "water", "position": 1},
               {"inci_name": "NIACINAMIDE", "slug": "niacinamide", "position": 2}]
    base = _variant(SAMPLE, "cerave-acne-control-cleanser", base_ings)
    base["name"] = "CeraVe Acne Control Cleanser"
    v5 = _variant(base, "cerave-acne-control-cleanser-5", v5_ings)

    p_base = load_product(session, base)
    session.commit()
    p_v5 = load_product(session, v5)  # 后到的变体不得合并进 base 行
    session.commit()

    assert p_v5.id != p_base.id
    assert session.query(Product).count() == 2
    # base 行：27 成分版的 url + 3 条 base 成分
    assert p_base.source_url.endswith("/cerave-acne-control-cleanser")
    base_links = session.query(ProductIngredient).filter_by(product_id=p_base.id).count()
    assert base_links == 3
    # 变体行：名字带 slug 后缀可辨识，url 指向变体页，成分是自己的 2 条
    assert "cerave-acne-control-cleanser-5" in p_v5.name
    assert p_v5.source_url.endswith("/cerave-acne-control-cleanser-5")
    v5_links = (session.query(ProductIngredient).filter_by(product_id=p_v5.id)
                .order_by(ProductIngredient.position).all())
    assert [l.ingredient.inci_name for l in v5_links] == ["WATER", "NIACINAMIDE"]
    # 幂等：重跑两边都不增生、不改写
    load_product(session, base)
    load_product(session, v5)
    session.commit()
    assert session.query(Product).count() == 2
    assert session.query(ProductIngredient).count() == 5


def test_variant_url_never_overwrites_other_variant(session):
    """既有行已有指向某变体的 source_url 时，另一变体的加载不得改写它。"""
    v5 = _variant(SAMPLE, "cerave-acne-control-cleanser-5",
                  [{"inci_name": "WATER", "slug": "water", "position": 1}])
    v5["name"] = "CeraVe Acne Control Cleanser"
    p_v5 = load_product(session, v5)
    session.commit()
    base = _variant(SAMPLE, "cerave-acne-control-cleanser",
                    [{"inci_name": "WATER", "slug": "water", "position": 1},
                     {"inci_name": "GLYCERIN", "slug": "glycerin", "position": 2}])
    base["name"] = "CeraVe Acne Control Cleanser"
    load_product(session, base)
    session.commit()
    # v5 行的 url 仍是 v5 页；base 行是独立新行
    session.refresh(p_v5)
    assert p_v5.source_url.endswith("-5")
    assert session.query(Product).count() == 2
