"""配方典型用量加载器测试：聚合口径/回填/已有值不覆盖/幂等/未命中不猜。"""

import pytest

from app.models.ingredient import Ingredient
from data.loaders.formula_loader import aggregate_by_ingredient, load_formula_dose
from data.tools.parse_formula_xlsx import parse_pct


def test_parse_pct():
    assert parse_pct("3") == (3.0, 3.0)
    assert parse_pct("0.5-1.0") == (0.5, 1.0)
    assert parse_pct("1.0~2") == (1.0, 2.0)
    assert parse_pct("=100-SUM(E4:E11)") is None  # Excel 公式不猜
    assert parse_pct("") is None


def test_aggregate():
    agg = aggregate_by_ingredient([
        {"formulation": "爽肤水", "inci_name": "甘油", "pct_low": 3.0, "pct_high": 3.0},
        {"formulation": "面霜", "inci_name": "甘油", "pct_low": 5.0, "pct_high": 8.0},
        {"formulation": "面霜", "inci_name": "卡波姆", "pct_low": 0.2, "pct_high": 0.2},
    ])
    assert agg["甘油"]["low"] == 3.0 and agg["甘油"]["high"] == 8.0
    assert agg["甘油"]["formulations"] == {"爽肤水", "面霜"}


@pytest.fixture()
def db(session):
    session.add_all([
        Ingredient(inci_name="GLYCERIN", cn_name="甘油"),
        Ingredient(inci_name="CARBOMER", cn_name="卡波姆"),
    ])
    session.commit()
    return session


def _data(records):
    return {"source": {"file": "t", "nature": "t"},
            "stats": {"total_records": len(records), "by_sheet": {}},
            "records": records}


def test_load_formula_dose(db):
    data = _data([
        {"formulation": "爽肤水", "inci_name": "甘油", "pct_low": 3.0,
         "pct_high": 3.0, "purpose": "保湿剂"},
        {"formulation": "面霜", "inci_name": "甘油", "pct_low": 5.0,
         "pct_high": 8.0, "purpose": "保湿剂"},
        {"formulation": "面霜", "inci_name": "不存在的成分", "pct_low": 1.0,
         "pct_high": 1.0, "purpose": ""},
    ])
    stats = load_formula_dose(db, data)
    assert stats["updated"] == 1
    assert stats["ingredients_unmatched"] == 1
    gly = db.query(Ingredient).filter_by(inci_name="GLYCERIN").one()
    assert gly.typical_use_low == 3.0 and gly.typical_use_high == 8.0


def test_existing_value_not_overwritten(db):
    gly = db.query(Ingredient).filter_by(inci_name="GLYCERIN").one()
    gly.typical_use_low, gly.typical_use_high = 1.0, 2.0
    db.commit()
    data = _data([{"formulation": "面霜", "inci_name": "甘油", "pct_low": 5.0,
                   "pct_high": 8.0, "purpose": ""}])
    stats = load_formula_dose(db, data)
    assert stats["skipped_existing"] == 1
    db.refresh(gly)
    assert gly.typical_use_low == 1.0  # 不被覆盖


def test_idempotent(db):
    data = _data([{"formulation": "爽肤水", "inci_name": "甘油", "pct_low": 3.0,
                   "pct_high": 3.0, "purpose": ""}])
    load_formula_dose(db, data)
    db.commit()
    stats = load_formula_dose(db, data)
    assert stats["unchanged"] == 1 and stats["updated"] == 0
