from data.loaders.seed_loader import load_seed
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
    assert session.query(EfficacyAssertion).count() == 4
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
    assert session.query(EfficacyAssertion).count() == 4


def test_every_assertion_has_evidence(session):
    load_seed(session)
    session.commit()
    for a in session.query(EfficacyAssertion).all():
        assert a.evidence is not None and a.evidence.url
