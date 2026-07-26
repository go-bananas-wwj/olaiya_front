from sqlalchemy import inspect

from app.db import engine


def test_init_db_creates_tables(session):
    # init_db 已由 fixture 调用；models 注册后这些表必须存在
    tables = set(inspect(engine).get_table_names())
    assert {"evidence", "ingredients", "efficacy_assertions", "products", "product_ingredients", "product_claims", "price_points"} <= tables
