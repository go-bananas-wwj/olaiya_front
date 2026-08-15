"""成分搜索折叠匹配：忽略大小写/空格/连字符（解码页逐成分查询依赖，v2.2 方案 P0）。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_db
from app.models.ingredient import Ingredient


@pytest.fixture()
def client(session):
    session.add_all([
        Ingredient(inci_name="NIACINAMIDE", cn_name="烟酰胺"),
        Ingredient(inci_name="HYALURONIC ACID", cn_name="透明质酸"),
    ])
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def test_fold_case_space(client):
    r = client.get("/api/ingredients", params={"q": "niacin amide"}).json()
    assert [i["cn_name"] for i in r] == ["烟酰胺"]


def test_fold_hyphen(client):
    r = client.get("/api/ingredients", params={"q": "hyaluronic-acid"}).json()
    assert [i["cn_name"] for i in r] == ["透明质酸"]


def test_cn_name_unchanged(client):
    r = client.get("/api/ingredients", params={"q": "烟酰"}).json()
    assert [i["cn_name"] for i in r] == ["烟酰胺"]
