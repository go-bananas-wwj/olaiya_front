"""POST /api/detect-image 代理端点测试：转发 / 降级 / 错误透传（不触真 sidecar）。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import vision_detect

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-image-bytes"


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _upload(client, content=PNG_BYTES, filename="x.png", content_type="image/png"):
    return client.post("/api/detect-image", files={"file": (filename, content, content_type)})


def test_forward_success(client, monkeypatch):
    """sidecar 200：结果原样透传，且文件内容/文件名/类型如实转发。"""
    seen = {}

    def fake_detect(content, filename, content_type):
        seen.update(content=content, filename=filename, content_type=content_type)
        return 200, {"score": 0.95, "verdict": "ai", "threshold": 0.7, "note": "检测为模型估计，仅供演示"}

    monkeypatch.setattr(vision_detect, "detect_image", fake_detect)
    r = _upload(client)
    assert r.status_code == 200
    assert r.json() == {"score": 0.95, "verdict": "ai", "threshold": 0.7, "note": "检测为模型估计，仅供演示"}
    assert seen == {"content": PNG_BYTES, "filename": "x.png", "content_type": "image/png"}


def test_sidecar_unreachable_503(client, monkeypatch):
    """sidecar 不可达：503 诚实降级，detail 如实说明。"""
    def fake_detect(content, filename, content_type):
        raise vision_detect.VisionUnavailableError("视觉检测服务未启动或不可达（http://127.0.0.1:8101）")

    monkeypatch.setattr(vision_detect, "detect_image", fake_detect)
    r = _upload(client)
    assert r.status_code == 503
    assert "不可达" in r.json()["detail"]


def test_sidecar_error_relayed(client, monkeypatch):
    """sidecar 400（图片无法解码）：状态码与 detail 透传。"""
    monkeypatch.setattr(vision_detect, "detect_image",
                        lambda *a: (400, {"detail": "图片无法解码或格式不支持"}))
    r = _upload(client)
    assert r.status_code == 400
    assert r.json()["detail"] == "图片无法解码或格式不支持"


def test_empty_file_400(client, monkeypatch):
    """空文件直接 400，不触 sidecar。"""
    called = []
    monkeypatch.setattr(vision_detect, "detect_image", lambda *a: called.append(a))
    r = _upload(client, content=b"")
    assert r.status_code == 400
    assert called == []
