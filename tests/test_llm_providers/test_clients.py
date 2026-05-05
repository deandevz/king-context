import json

import httpx
import pytest

from llm_providers.config import ResolvedConfig
from llm_providers.ollama import OllamaClient
from llm_providers.openrouter import OpenRouterClient


def _config(
    *,
    provider: str,
    model: str = "test-model",
    mode: str = "openai",
    base_url: str = "http://localhost:11434/v1",
    openrouter_key: str | None = "or-key",
    ollama_key: str | None = None,
) -> ResolvedConfig:
    return ResolvedConfig(
        stage="enrich",
        provider=provider,
        model=model,
        concurrency=2,
        openrouter_api_key=openrouter_key,
        ollama_api_mode=mode,
        ollama_base_url=base_url,
        ollama_api_key=ollama_key,
        fallback_enabled=False,
        fallback_model="fallback-model",
    )


def _patch_async_client(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        return original_async_client(
            transport=transport,
            timeout=kwargs.get("timeout"),
        )

    monkeypatch.setattr(httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_openrouter_request_shape(monkeypatch):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok": true}'}}]},
        )

    _patch_async_client(monkeypatch, handler)
    client = OpenRouterClient(_config(provider="openrouter"))

    result = await client.complete("hello", system="sys")

    assert result == {"ok": True}
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer or-key"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["messages"][0] == {"role": "system", "content": "sys"}


@pytest.mark.asyncio
async def test_ollama_openai_request_shape(monkeypatch):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok": true}'}}]},
        )

    _patch_async_client(monkeypatch, handler)
    client = OllamaClient(
        _config(provider="ollama", mode="openai", ollama_key="ollama-key")
    )

    result = await client.complete("hello")

    assert result == {"ok": True}
    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer ollama-key"
    assert captured["body"]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_ollama_native_request_shape(monkeypatch):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"message": {"content": '{"ok": true}'}},
        )

    _patch_async_client(monkeypatch, handler)
    client = OllamaClient(
        _config(provider="ollama", mode="native", base_url="https://ollama.com")
    )

    result = await client.complete("hello")

    assert result == {"ok": True}
    assert captured["url"] == "https://ollama.com/api/chat"
    assert captured["body"]["stream"] is False
    assert captured["body"]["format"] == "json"
