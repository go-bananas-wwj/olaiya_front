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


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """建表。延迟导入 models 以完成表注册，避免循环导入。"""
    from . import models  # noqa: F401

    Base.metadata.create_all(engine)
