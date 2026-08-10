from sqlalchemy import inspect, text

from app.db import engine, ensure_additive_columns


def test_init_db_creates_tables(session):
    # init_db 已由 fixture 调用；models 注册后这些表必须存在
    tables = set(inspect(engine).get_table_names())
    assert {"evidence", "ingredients", "efficacy_assertions", "products", "product_ingredients", "product_claims", "price_points", "market_snapshots"} <= tables


def test_ensure_additive_columns_backfills_buy_url(session):
    """既有库缺 buy_url 列时幂等补列（create_all 不加列，靠 ALTER TABLE 迁移）。"""
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE products DROP COLUMN buy_url"))  # 模拟旧库
    assert "buy_url" not in {c["name"] for c in inspect(engine).get_columns("products")}
    ensure_additive_columns()
    assert "buy_url" in {c["name"] for c in inspect(engine).get_columns("products")}
    ensure_additive_columns()  # 第二次执行不报错（幂等）
