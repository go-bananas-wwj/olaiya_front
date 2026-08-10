"""数据库连接。开发期 SQLite；换 PostgreSQL 只改 CFZ_DATABASE_URL。"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args)


# SQLite 默认不启用外键约束，必须逐连接打开，否则 ForeignKey 形同虚设
@event.listens_for(engine, "connect")
def _enable_sqlite_fk(dbapi_conn, _):
    if settings.database_url.startswith("sqlite"):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")


# create_all 只建新表、不给既有表加列；新增的可空列在这里幂等补登（SQLite/PostgreSQL 通用）
_ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "products": {"buy_url": "VARCHAR(500)"},
}


def ensure_additive_columns() -> None:
    """既有库补加新可空列（幂等）：先查表结构，缺列才 ALTER TABLE ADD COLUMN。

    反射与 ALTER 共用同一条连接（inspect(conn)），不为反射另取连接——
    池内连接数变化会打乱「rollback 后再 execute 仍落在同一物理连接」的
    既有隐式依赖（如 product_dedup.repair_from_backup 的 ATTACH/DETACH）。
    """
    from sqlalchemy import inspect, text

    with engine.begin() as conn:
        insp = inspect(conn)
        existing_tables = set(insp.get_table_names())
        for table, cols in _ADDITIVE_COLUMNS.items():
            if table not in existing_tables:  # 表不存在时由 create_all 建（含新列），跳过
                continue
            existing_cols = {c["name"] for c in insp.get_columns(table)}
            for col, ddl in cols.items():
                if col not in existing_cols:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """建表 + 补加新列。延迟导入 models 以完成表注册，避免循环导入。"""
    from . import models  # noqa: F401

    Base.metadata.create_all(engine)
    ensure_additive_columns()
