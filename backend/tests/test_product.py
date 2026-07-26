import datetime

from app.models.ingredient import Ingredient
from app.models.product import PricePoint, Product, ProductIngredient


def _product_with_ingredients(session):
    p = Product(name="测试精华", brand="测试牌", category="精华", price_current=199.0)
    water = Ingredient(inci_name="WATER", cn_name="水")
    nia = Ingredient(inci_name="NIACINAMIDE", cn_name="烟酰胺")
    pe = Ingredient(inci_name="PHENOXYETHANOL", cn_name="苯氧乙醇", legal_cap=1.0)
    session.add_all([p, water, nia, pe])
    session.commit()
    session.add_all([
        ProductIngredient(product_id=p.id, ingredient_id=water.id, position=1),
        ProductIngredient(product_id=p.id, ingredient_id=nia.id, position=2),
        ProductIngredient(product_id=p.id, ingredient_id=pe.id, position=3),
    ])
    session.commit()
    return p


def test_product_ingredient_ordering(session):
    p = _product_with_ingredients(session)
    rows = (session.query(ProductIngredient)
            .filter_by(product_id=p.id)
            .order_by(ProductIngredient.position).all())
    assert [r.ingredient.inci_name for r in rows] == ["WATER", "NIACINAMIDE", "PHENOXYETHANOL"]
    assert all(r.is_trace is False for r in rows)
    assert rows[0].conc_low is None  # 推断字段默认为空，等待计划 02


def test_price_point(session):
    p = _product_with_ingredients(session)
    pp = PricePoint(product_id=p.id, date=datetime.date(2026, 7, 26),
                    price=199.0, source="人工采样", is_manual=True)
    session.add(pp)
    session.commit()
    got = session.query(PricePoint).one()
    assert got.price == 199.0 and got.is_manual is True
