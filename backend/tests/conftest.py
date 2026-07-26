import os
import tempfile

# 必须在导入 app 之前设置：测试用独立临时文件库，避免污染开发库
_db_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.close(_db_fd)
os.environ["CFZ_DATABASE_URL"] = f"sqlite:///{_db_path}"

import pytest

from app.db import Base, SessionLocal, engine, init_db


@pytest.fixture()
def session():
    """每个测试用例得到一张空表环境。"""
    Base.metadata.drop_all(engine)
    init_db()
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
