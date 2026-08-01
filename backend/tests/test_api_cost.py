"""每起效成本接入浓度 API（总纲 I3 高潮数字）：estimates 条目级 cost + 产品级 price/spec。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_db
from data.loaders.price_loader import load_prices
from data.loaders.seed_loader import load_seed
from data.tools.run_inference import run_inference


@pytest.fixture()
def client(session):
    load_seed(session)
    load_prices(session)  # 真实 price_specs.json：CE 1720/30ml、TO 59/30ml
    run_inference(session)
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def _product_id(client, brand):
    return [p for p in client.get("/api/products").json() if p["brand"] == brand][0]["id"]


def test_to_niacinamide_cost(client):
    """TO 烟酰胺：59 元/30ml，披露锚点 10%，起效线 2% → 59/30×2/10 ≈ 0.39 元/天。"""
    pid = _product_id(client, "The Ordinary")
    body = client.get(f"/api/products/{pid}/concentration").json()
    assert body["inferred"] is True
    assert body["price"] == 59.0 and body["spec"] == "30ml"
    nia = [e for e in body["estimates"] if e["inci_name"] == "NIACINAMIDE"]
    assert len(nia) == 1
    cost = nia[0]["cost_per_effective_dose"]
    assert cost == pytest.approx(59.0 / 30.0 * 2.0 / 10.0, abs=1e-9)
    assert cost == pytest.approx(0.39, abs=0.01)
    assert nia[0]["cost_note"] == "按 1ml 日用量折算，估计值"


def test_ce_ascorbic_acid_cost(client):
    """修丽可 CE：1720 元/30ml，VC 披露 15%，起效线 8% → 1720/30×8/15 ≈ 30.58 元/天。"""
    pid = _product_id(client, "修丽可 SkinCeuticals")
    body = client.get(f"/api/products/{pid}/concentration").json()
    assert body["price"] == 1720.0 and body["spec"] == "30ml"
    aa = [e for e in body["estimates"] if e["inci_name"] == "ASCORBIC ACID"]
    assert len(aa) == 1
    assert aa[0]["cost_per_effective_dose"] == pytest.approx(1720.0 / 30.0 * 8.0 / 15.0, abs=1e-9)


def test_entries_without_effective_line_have_none_cost(client):
    """无起效浓度断言的成分（如水）：cost 字段为 None，不报错。"""
    pid = _product_id(client, "The Ordinary")
    body = client.get(f"/api/products/{pid}/concentration").json()
    water = [e for e in body["estimates"] if e["inci_name"] == "WATER"]
    assert len(water) == 1
    assert water[0]["cost_per_effective_dose"] is None
    assert water[0]["cost_note"] is None
    # 所有条目都带 cost 键（可为 None），结构一致
    for e in body["estimates"]:
        assert "cost_per_effective_dose" in e and "cost_note" in e


def test_product_without_price_has_none_cost(client, session):
    """产品有推断浓度但无价格/规格：条目 cost=None，产品级 price/spec 为 None。"""
    from app.models.product import Product, ProductIngredient
    from app.models.ingredient import Ingredient

    ing = session.query(Ingredient).filter_by(inci_name="NIACINAMIDE").one()
    p = Product(name="无价测试精华", brand="TEST")
    session.add(p)
    session.flush()
    session.add(ProductIngredient(product_id=p.id, ingredient_id=ing.id,
                                  position=1, conc_low=9.0, conc_high=11.0))
    session.commit()
    body = client.get(f"/api/products/{p.id}/concentration").json()
    assert body["inferred"] is True
    assert body["price"] is None and body["spec"] is None
    assert body["estimates"][0]["cost_per_effective_dose"] is None
    assert body["estimates"][0]["cost_note"] is None


def test_product_detail_exposes_spec(client):
    """产品详情 API 带 spec，供头部价格/规格展示。"""
    pid = _product_id(client, "The Ordinary")
    body = client.get(f"/api/products/{pid}").json()
    assert body["spec"] == "30ml"
    assert body["price_current"] == 59.0
