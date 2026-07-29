"""LLM 双通道网关测试：mock openai 客户端，不依赖真实 LLM 服务。"""

from types import SimpleNamespace

import pytest

from app.services.llm_gateway import (
    DEFAULT_CLOUD_BASE_URL,
    DEFAULT_CLOUD_MODEL,
    LOCAL_BASE_URL,
    LOCAL_MODEL,
    LLMGateway,
    LLMUnavailableError,
)


class _FakeCompletions:
    """记录 create 调用参数，按构造时给定内容/异常返回。"""

    def __init__(self, content="你好", exc=None):
        self.calls = []
        self._content = content
        self._exc = exc

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))]
        )


class _FakeModels:
    def __init__(self, ids=("m1",), exc=None):
        self._ids = ids
        self._exc = exc

    def list(self):
        if self._exc is not None:
            raise self._exc
        return SimpleNamespace(data=[SimpleNamespace(id=i) for i in self._ids])


def make_client(content="你好", chat_exc=None, model_ids=("m1",), models_exc=None):
    return SimpleNamespace(
        chat=SimpleNamespace(completions=_FakeCompletions(content, chat_exc)),
        models=_FakeModels(model_ids, models_exc),
    )


@pytest.fixture(autouse=True)
def clean_llm_env(monkeypatch):
    """每个用例默认清掉 LLM 相关环境变量，避免本机环境污染。"""
    for var in ("CFZ_LLM_CHANNEL", "CFZ_CLOUD_BASE_URL", "CFZ_CLOUD_MODEL", "CFZ_CLOUD_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def test_default_channel_is_local():
    gw = LLMGateway(client=make_client())
    assert gw.channel == "local"
    assert gw.base_url == LOCAL_BASE_URL
    assert gw.model == LOCAL_MODEL


def test_channel_switches_to_cloud_via_env(monkeypatch):
    monkeypatch.setenv("CFZ_LLM_CHANNEL", "cloud")
    monkeypatch.setenv("CFZ_CLOUD_API_KEY", "sk-test")
    gw = LLMGateway(client=make_client())
    assert gw.channel == "cloud"
    assert gw.base_url == DEFAULT_CLOUD_BASE_URL
    assert gw.model == DEFAULT_CLOUD_MODEL


def test_cloud_base_url_and_model_overridable(monkeypatch):
    monkeypatch.setenv("CFZ_LLM_CHANNEL", "cloud")
    monkeypatch.setenv("CFZ_CLOUD_API_KEY", "sk-test")
    monkeypatch.setenv("CFZ_CLOUD_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("CFZ_CLOUD_MODEL", "qwen-max")
    gw = LLMGateway(client=make_client())
    assert gw.base_url == "https://example.com/v1"
    assert gw.model == "qwen-max"


def test_invalid_channel_raises():
    with pytest.raises(ValueError, match="通道"):
        LLMGateway(channel="mars", client=make_client())


def test_chat_assembles_request_and_returns_text():
    client = make_client(content="成分党是看配料表护肤的人")
    gw = LLMGateway(client=client)
    messages = [{"role": "user", "content": "什么是成分党"}]
    out = gw.chat(messages, temperature=0.7, max_tokens=128,
                  response_format={"type": "json_object"})
    assert out == "成分党是看配料表护肤的人"
    (call,) = client.chat.completions.calls
    assert call["model"] == LOCAL_MODEL
    assert call["messages"] == messages
    assert call["temperature"] == 0.7
    assert call["max_tokens"] == 128
    assert call["response_format"] == {"type": "json_object"}


def test_chat_defaults():
    client = make_client()
    gw = LLMGateway(client=client)
    gw.chat([{"role": "user", "content": "hi"}])
    (call,) = client.chat.completions.calls
    assert call["temperature"] == 0.3
    assert call["max_tokens"] == 2048
    assert "response_format" not in call


def test_chat_unreachable_raises_with_channel_info():
    client = make_client(chat_exc=ConnectionError("refused"))
    gw = LLMGateway(client=client)
    with pytest.raises(LLMUnavailableError, match="local"):
        gw.chat([{"role": "user", "content": "hi"}])


def test_cloud_without_key_fails_gracefully(monkeypatch):
    """cloud 通道缺 key：chat 报 LLMUnavailableError 提示，不抛裸异常。"""
    monkeypatch.setenv("CFZ_LLM_CHANNEL", "cloud")
    gw = LLMGateway()  # 不注入客户端，走真实初始化路径
    with pytest.raises(LLMUnavailableError, match="CFZ_CLOUD_API_KEY"):
        gw.chat([{"role": "user", "content": "hi"}])


def test_available_reachable():
    client = make_client(model_ids=(LOCAL_MODEL,))
    gw = LLMGateway(client=client)
    info = gw.available()
    assert info["channel"] == "local"
    assert info["reachable"] is True
    assert LOCAL_MODEL in info["detail"]


def test_available_unreachable():
    client = make_client(models_exc=ConnectionError("refused"))
    gw = LLMGateway(client=client)
    info = gw.available()
    assert info["channel"] == "local"
    assert info["reachable"] is False
    assert "refused" in info["detail"]


def test_available_cloud_without_key(monkeypatch):
    monkeypatch.setenv("CFZ_LLM_CHANNEL", "cloud")
    gw = LLMGateway()
    info = gw.available()
    assert info["channel"] == "cloud"
    assert info["reachable"] is False
    assert "CFZ_CLOUD_API_KEY" in info["detail"]
