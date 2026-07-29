"""LLM 双通道网关：统一封装本地 vLLM 与云端 API，供 Agent/RAG 调用。

通道由环境变量 CFZ_LLM_CHANNEL 控制（"local" | "cloud"，默认 local）：
- local：OpenAI 兼容客户端连本地 vLLM（http://127.0.0.1:8100/v1，
  模型 data/models/llm/Qwen2.5-14B-Instruct，启动命令见 docs/npu-inference-setup.md）。
- cloud：OpenAI 兼容客户端连 CFZ_CLOUD_BASE_URL（默认阿里云百炼兼容端点），
  模型 CFZ_CLOUD_MODEL（默认 qwen-plus），key 读 CFZ_CLOUD_API_KEY；
  无 key 时 cloud 通道调用报 LLMUnavailableError 提示，不崩。
"""

from __future__ import annotations

import os

from openai import OpenAI

LOCAL_BASE_URL = "http://127.0.0.1:8100/v1"
LOCAL_MODEL = "data/models/llm/Qwen2.5-14B-Instruct"
DEFAULT_CLOUD_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_CLOUD_MODEL = "qwen-plus"

# 本地 NPU 推理首 token 较慢，超时放宽
_TIMEOUT = 120.0


class LLMUnavailableError(RuntimeError):
    """LLM 通道不可用（服务未启动/网络不通/缺 key），消息带通道信息。"""


class LLMGateway:
    """LLM 双通道网关。channel: "local" | "cloud"（环境变量 CFZ_LLM_CHANNEL 控制，默认 local）。"""

    def __init__(self, channel: str | None = None, client=None):
        self.channel = (channel or os.environ.get("CFZ_LLM_CHANNEL") or "local").strip().lower()
        if self.channel not in ("local", "cloud"):
            raise ValueError(f"未知 LLM 通道: {self.channel!r}（应为 local 或 cloud）")
        if self.channel == "local":
            self.base_url = LOCAL_BASE_URL
            self.model = LOCAL_MODEL
            # 本地 vLLM 不校验 key，但 OpenAI SDK 要求非空
            self._api_key = "EMPTY"
        else:
            self.base_url = os.environ.get("CFZ_CLOUD_BASE_URL") or DEFAULT_CLOUD_BASE_URL
            self.model = os.environ.get("CFZ_CLOUD_MODEL") or DEFAULT_CLOUD_MODEL
            self._api_key = os.environ.get("CFZ_CLOUD_API_KEY")
        self._client = client

    def _get_client(self):
        if self._client is None:
            if not self._api_key:
                raise LLMUnavailableError(
                    "cloud 通道缺少 CFZ_CLOUD_API_KEY，请配置后重试（或改回 CFZ_LLM_CHANNEL=local）"
                )
            self._client = OpenAI(base_url=self.base_url, api_key=self._api_key, timeout=_TIMEOUT)
        return self._client

    def chat(self, messages: list[dict], *, temperature: float = 0.3,
             max_tokens: int = 2048, response_format: dict | None = None) -> str:
        """返回助手文本。本地/云端不可达时抛 LLMUnavailableError（带通道信息）。"""
        kwargs = dict(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if response_format is not None:
            kwargs["response_format"] = response_format
        try:
            resp = self._get_client().chat.completions.create(**kwargs)
        except LLMUnavailableError:
            raise
        except Exception as e:
            raise LLMUnavailableError(f"{self.channel} 通道调用失败: {e}") from e
        return resp.choices[0].message.content

    def available(self) -> dict:
        """健康检查：列模型探测通道是否可达。返回 {channel, reachable, detail}。"""
        try:
            client = self._get_client()
        except LLMUnavailableError as e:
            return {"channel": self.channel, "reachable": False, "detail": str(e)}
        try:
            ids = [m.id for m in client.models.list().data]
        except Exception as e:
            return {"channel": self.channel, "reachable": False, "detail": str(e)}
        return {"channel": self.channel, "reachable": True, "detail": f"models: {ids}"}
