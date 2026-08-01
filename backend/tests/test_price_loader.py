"""价格规格加载器：match 模糊匹配 + 「有序产品优先 + brand」消歧 + 幂等。"""

import datetime
import json

import pytest

from app.models.ingredient import Ingredient
from app.models.product import PricePoint, Product, ProductIngredient
from data.loaders.price_loader import load_prices
from data.loaders.seed_loader import load_ordered_products, load_seed


def _write_price_file(tmp_path, items):
    f = tmp_path / "prices.json"
    f.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
    return f


@pytest.fixture()
def price_file(tmp_path):
    return _write_price_file(tmp_path, [
        {"match": "维生素CE复合修护", "brand": "修丽可 SkinCeuticals", "price": 1720.0,
         "spec": "30ml", "price_note": "官方标价", "source_url": "https://example.com/ce"},
        {"match": "烟酰胺10%+锌1%", "brand": "The Ordinary", "price": 59.0,
         "spec": "30ml", "price_note": "参考价", "source_url": "https://example.com/to"},
        {"match": "绝不存在的产品xyz", "brand": "X", "price": 1.0,
         "spec": "1ml", "price_note": "", "source_url": "https://example.com/x"},
    ])


def test_load_prices_writes_price_spec_and_point(session, price_file):
    load_seed(session)
    session.commit()
    stats = load_prices(session, path=price_file)
    session.commit()
    ce = session.query(Product).filter_by(brand="修丽可 SkinCeuticals").one()
    assert ce.price_current == 1720.0  # 覆盖种子旧价 1490（官网已涨）
    assert ce.spec == "30ml"
    to = session.query(Product).filter_by(brand="The Ordinary").one()
    assert to.price_current == 59.0 and to.spec == "30ml"
    points = session.query(PricePoint).filter_by(product_id=ce.id).all()
    assert len(points) == 1
    assert points[0].price == 1720.0
    assert points[0].source == "https://example.com/ce"
    assert points[0].is_manual is True
    assert points[0].date == datetime.date.today()
    assert stats["items"] == 3
    assert stats["matched"] == 2
    assert stats["unmatched"] == ["绝不存在的产品xyz"]
    assert stats["price_points_added"] == 2


def test_load_prices_idempotent(session, price_file):
    load_seed(session)
    session.commit()
    load_prices(session, path=price_file)
    session.commit()
    n_points = session.query(PricePoint).count()
    stats = load_prices(session, path=price_file)
    session.commit()
    assert session.query(PricePoint).count() == n_points  # 同日同源不重复插点
    assert stats["price_points_added"] == 0
    assert stats["price_points_updated"] == 2
    to = session.query(Product).filter_by(brand="The Ordinary").one()
    assert to.price_current == 59.0


def test_disambiguation_ordered_product_wins(session, tmp_path):
    """理肤泉 B5：无序 stub「理肤泉新B5多效修复霜」也含 match 串，须命中有位次的有序产品。"""
    load_seed(session)
    load_ordered_products(session)
    stub_ing = Ingredient(inci_name="TEST ING B5", cn_name="测试成分")
    session.add(stub_ing)
    session.flush()
    stub = Product(name="理肤泉新B5多效修复霜", brand="理肤泉")
    session.add(stub)
    session.flush()
    session.add(ProductIngredient(product_id=stub.id, ingredient_id=stub_ing.id, position=None))
    session.commit()
    f = _write_price_file(tmp_path, [
        {"match": "B5多效修复霜", "brand": "理肤泉 La Roche-Posay", "price": 62.67,
         "spec": "40ml", "price_note": "参考价", "source_url": "https://example.com/b5"},
    ])
    stats = load_prices(session, path=f)
    session.commit()
    ordered = session.query(Product).filter_by(brand="理肤泉 La Roche-Posay").one()
    assert "Cicaplast" in ordered.name  # 有序产品（有位次关联）
    assert ordered.price_current == 62.67 and ordered.spec == "40ml"
    session.expire_all()
    assert session.get(Product, stub.id).price_current is None  # 无序同名产品未被误写
    assert stats["matched"] == 1
    assert stats["unmatched"] == []


def test_disambiguation_by_brand_when_no_ordered(session, tmp_path):
    """两个无序同名产品：有序优先不适用时按 brand 消歧。"""
    ing = Ingredient(inci_name="TEST ING BRAND", cn_name="测试成分")
    session.add(ing)
    session.flush()
    a = Product(name="净透测试精华", brand="品牌甲")
    b = Product(name="净透测试精华 Pro", brand="品牌乙")
    session.add_all([a, b])
    session.flush()
    for p in (a, b):
        session.add(ProductIngredient(product_id=p.id, ingredient_id=ing.id, position=None))
    session.commit()
    f = _write_price_file(tmp_path, [
        {"match": "净透测试精华", "brand": "品牌乙", "price": 100.0,
         "spec": "50ml", "price_note": "", "source_url": "https://example.com/b"},
    ])
    stats = load_prices(session, path=f)
    session.commit()
    session.expire_all()
    assert session.get(Product, a.id).price_current is None
    assert session.get(Product, b.id).price_current == 100.0
    assert stats["matched"] == 1


def test_ambiguous_without_brand_match_reported(session, tmp_path):
    """无法消歧（brand 也不匹配）时不猜写，计入 unmatched。"""
    ing = Ingredient(inci_name="TEST ING AMB", cn_name="测试成分")
    session.add(ing)
    session.flush()
    for name in ("焕亮测试精华 A", "焕亮测试精华 B"):
        p = Product(name=name, brand="无关品牌")
        session.add(p)
        session.flush()
        session.add(ProductIngredient(product_id=p.id, ingredient_id=ing.id, position=None))
    session.commit()
    f = _write_price_file(tmp_path, [
        {"match": "焕亮测试精华", "brand": "不存在的品牌", "price": 1.0,
         "spec": "1ml", "price_note": "", "source_url": "https://example.com/amb"},
    ])
    stats = load_prices(session, path=f)
    session.commit()
    assert stats["matched"] == 0
    assert stats["unmatched"] == ["焕亮测试精华"]
    assert session.query(PricePoint).count() == 0
