from data.loaders.seed_loader import load_ordered_products, load_seed
from app.models.evidence import Evidence
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.models.product import Product, ProductIngredient


def test_load_seed_counts(session):
    load_seed(session)
    session.commit()
    assert session.query(Evidence).count() == 5
    # 5 个全字段成分 + 产品成分表自动补的 stub
    assert session.query(Ingredient).filter_by(inci_name="NIACINAMIDE").one().cn_name == "烟酰胺"
    assert session.query(Ingredient).filter_by(inci_name="ZINC PCA").count() == 1  # stub
    assert session.query(EfficacyAssertion).count() == 5
    assert session.query(Product).count() == 2
    ce = session.query(Product).filter_by(brand="修丽可 SkinCeuticals").one()
    first = (session.query(ProductIngredient).filter_by(product_id=ce.id)
             .order_by(ProductIngredient.position).first())
    assert first.ingredient.inci_name == "WATER" and first.position == 1


def test_load_seed_idempotent(session):
    load_seed(session)
    session.commit()
    load_seed(session)
    session.commit()
    assert session.query(Evidence).count() == 5
    assert session.query(Product).count() == 2
    assert session.query(EfficacyAssertion).count() == 5


def test_every_assertion_has_evidence(session):
    load_seed(session)
    session.commit()
    for a in session.query(EfficacyAssertion).all():
        assert a.evidence is not None and a.evidence.url


def _load_all(session):
    load_seed(session)
    load_ordered_products(session)
    session.commit()


def test_load_ordered_products_counts(session):
    _load_all(session)
    # 种子 2 个 + 降序产品集 8 个
    assert session.query(Product).count() == 10
    sk2 = session.query(Product).filter_by(brand="SK-II").one()
    assert sk2.source_url == "https://incidecoder.com/products/sk-ii-facial-treatment-essence"
    first = (session.query(ProductIngredient).filter_by(product_id=sk2.id)
             .order_by(ProductIngredient.position).first())
    assert first.ingredient.inci_name == "GALACTOMYCES FERMENT FILTRATE" and first.position == 1


def test_ordered_positions_strictly_increasing(session):
    _load_all(session)
    products = (session.query(Product)
                .filter(Product.source_url.isnot(None)).all())
    assert len(products) == 8  # 降序产品集均带 ingredient_source_url
    for p in products:
        rows = (session.query(ProductIngredient).filter_by(product_id=p.id)
                .order_by(ProductIngredient.position).all())
        assert rows, p.name
        positions = [r.position for r in rows]
        assert positions == list(range(1, len(rows) + 1))  # 1-based 严格递增
    # 微量段标记：OLAY 淡斑小白瓶 22 主段 + 9 微量段
    olay = session.query(Product).filter_by(brand="OLAY 玉兰油").one()
    rows = (session.query(ProductIngredient).filter_by(product_id=olay.id)
            .order_by(ProductIngredient.position).all())
    assert len(rows) == 31
    assert [r.is_trace for r in rows] == [False] * 22 + [True] * 9


def test_disclosed_conc_written(session):
    _load_all(session)

    def conc(product_name, inci):
        p = session.query(Product).filter_by(name=product_name).one()
        ing = session.query(Ingredient).filter_by(inci_name=inci).one()
        return (session.query(ProductIngredient)
                .filter_by(product_id=p.id, ingredient_id=ing.id).one().disclosed_conc)

    # 既有种子 5 个锚点
    assert conc("维生素CE复合修护精华液（CE Ferulic）", "ASCORBIC ACID") == 15.0
    assert conc("维生素CE复合修护精华液（CE Ferulic）", "TOCOPHEROL") == 1.0
    assert conc("维生素CE复合修护精华液（CE Ferulic）", "FERULIC ACID") == 0.5
    assert conc("烟酰胺10%+锌1%精华（Niacinamide 10% + Zinc 1%）", "NIACINAMIDE") == 10.0
    assert conc("烟酰胺10%+锌1%精华（Niacinamide 10% + Zinc 1%）", "ZINC PCA") == 1.0
    # 降序产品集 6 个锚点
    assert conc("神仙水（Facial Treatment Essence）", "GALACTOMYCES FERMENT FILTRATE") == 90.0
    assert conc("B5多效修复霜（Cicaplast Baume B5）", "PANTHENOL") == 5.0
    assert conc("黑绷带面霜（Re-Plasty Age Recovery Night）", "HYDROXYPROPYL TETRAHYDROPYRANTRIOL") == 30.0
    assert conc("紫米精华（H.A. Intensifier）", "HYDROXYPROPYL TETRAHYDROPYRANTRIOL") == 10.0
    assert conc("紫米精华（H.A. Intensifier）", "DIPOTASSIUM GLYCYRRHIZATE") == 2.0
    assert conc("紫米精华（H.A. Intensifier）", "ORYZA SATIVA (RICE) EXTRACT") == 0.2
    # 未披露的成分锚点为 NULL
    assert conc("神仙水（Facial Treatment Essence）", "BUTYLENE GLYCOL") is None


def test_total_disclosed_anchors_at_least_8(session):
    _load_all(session)
    anchors = (session.query(ProductIngredient)
               .filter(ProductIngredient.disclosed_conc.isnot(None)).count())
    assert anchors >= 8  # 种子 5 点 + 降序集 6 点 = 11


def test_load_ordered_products_idempotent(session):
    _load_all(session)
    load_ordered_products(session)
    session.commit()
    assert session.query(Product).count() == 10
    anchors = (session.query(ProductIngredient)
               .filter(ProductIngredient.disclosed_conc.isnot(None)).count())
    assert anchors == 11
    total_pi = session.query(ProductIngredient).count()
    load_seed(session)
    load_ordered_products(session)
    session.commit()
    assert session.query(ProductIngredient).count() == total_pi
