"""AI 生图检测代理：转发到视觉 sidecar（vision_service，独立 torch 进程）。

主 venv 无 torch 不能进程内跑模型，检测由 sidecar 承载（默认 127.0.0.1:8101，
可用 CFZ_VISION_URL 覆盖）；sidecar 不可达时抛 VisionUnavailableError 诚实降级。
"""

import os

import httpx

VISION_URL = os.environ.get("CFZ_VISION_URL", "http://127.0.0.1:8101")
TIMEOUT = 30.0  # CPU 单图 ~1s，留足模型首次加载余量


class VisionUnavailableError(Exception):
    """sidecar 不可达/超时。"""


def detect_image(content: bytes, filename: str, content_type: str) -> tuple[int, dict]:
    """转发图片到 sidecar /detect，返回 (status_code, payload)。

    sidecar 非 200（如 400 图片无法解码）原样回传，由调用方透传语义；
    连接失败/超时抛 VisionUnavailableError。
    """
    try:
        resp = httpx.post(
            f"{VISION_URL}/detect",
            files={"file": (filename, content, content_type)},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as e:
        raise VisionUnavailableError(f"视觉检测服务未启动或不可达（{VISION_URL}）") from e
    try:
        payload = resp.json()
    except ValueError:
        payload = {"detail": f"sidecar 返回非 JSON（HTTP {resp.status_code}）"}
    return resp.status_code, payload
