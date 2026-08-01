"""视觉 sidecar（vision_service.app）测试：dependency override 注入假分数，不触真模型/torch。

sidecar 模块对 torch 为惰性依赖，主 venv（无 torch）可直接 import 跑本测试。
"""

import pytest
from fastapi.testclient import TestClient

from vision_service.app import app, get_scorer, verdict_for

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-image-bytes"


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _override_score(value):
    app.dependency_overrides[get_scorer] = lambda: (lambda content: value)


def _upload(client, content=PNG_BYTES):
    return client.post("/detect", files={"file": ("x.png", content, "image/png")})


@pytest.mark.parametrize("score,verdict", [
    (0.95, "ai"),
    (0.71, "ai"),
    (0.5, "uncertain"),
    (0.7, "uncertain"),   # 阈值边界：>0.7 才判 ai
    (0.3, "uncertain"),   # 阈值边界：<0.3 才判 real
    (0.29, "real"),
    (0.1, "real"),
])
def test_detect_verdict_mapping(client, score, verdict):
    _override_score(score)
    r = _upload(client)
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == verdict
    assert body["score"] == score
    assert body["threshold"] == 0.7
    assert "估计" in body["note"]


def test_detect_scorer_error_400(client):
    """打分函数抛异常（如图片无法解码）：400 而非 500。"""
    def boom(content):
        raise ValueError("cannot identify image file")

    app.dependency_overrides[get_scorer] = lambda: boom
    r = _upload(client)
    assert r.status_code == 400
    assert "解码" in r.json()["detail"]


def test_detect_empty_file_400(client):
    _override_score(0.9)
    r = _upload(client, content=b"")
    assert r.status_code == 400


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["model_loaded"] is False  # 测试不触真模型


def test_verdict_for_boundaries():
    assert verdict_for(0.7) == "uncertain"
    assert verdict_for(0.7001) == "ai"
    assert verdict_for(0.3) == "uncertain"
    assert verdict_for(0.2999) == "real"
