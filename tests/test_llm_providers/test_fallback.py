import pytest

from conftest import FakeLLMClient
from king_context.scraper.config import ConfigError
from llm_providers.base import ProviderError
from llm_providers.fallback import FallbackClient


@pytest.mark.asyncio
async def test_fallback_calls_openrouter_once(capsys):
    primary = FakeLLMClient(
        responses=[
            ProviderError(
                "connection_refused",
                transient=True,
                message="down",
                provider="ollama",
            )
        ],
        name="ollama",
        model="qwen2.5:7b",
    )
    fallback = FakeLLMClient(
        responses=[{"ok": True}],
        name="openrouter",
        model="google/gemini-3-flash-preview",
    )
    client = FallbackClient(primary=primary, fallback=fallback, stage="enrich")

    result = await client.complete("hello")

    assert result == {"ok": True}
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1
    assert "reason: connection_refused" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_fallback_surfaces_both_errors():
    primary_error = ProviderError(
        "timeout",
        transient=True,
        message="timeout",
        provider="ollama",
    )
    fallback_error = ProviderError(
        "rate_limit",
        transient=True,
        message="limited",
        provider="openrouter",
    )
    client = FallbackClient(
        primary=FakeLLMClient(responses=[primary_error], name="ollama"),
        fallback=FakeLLMClient(responses=[fallback_error], name="openrouter"),
        stage="enrich",
    )

    with pytest.raises(ProviderError) as exc:
        await client.complete("hello")

    assert exc.value.primary_error is primary_error
    assert exc.value.fallback_error is fallback_error


@pytest.mark.asyncio
async def test_fallback_combined_error_uses_fallback_transience():
    primary_error = ProviderError(
        "timeout",
        transient=True,
        message="timeout",
        provider="ollama",
    )
    fallback_error = ProviderError(
        "auth_error",
        transient=False,
        message="unauthorized",
        provider="openrouter",
    )
    client = FallbackClient(
        primary=FakeLLMClient(responses=[primary_error], name="ollama"),
        fallback=FakeLLMClient(responses=[fallback_error], name="openrouter"),
        stage="enrich",
    )

    with pytest.raises(ProviderError) as exc:
        await client.complete("hello")

    assert exc.value.transient is False
    assert exc.value.primary_error is primary_error
    assert exc.value.fallback_error is fallback_error


def test_rejects_reverse_fallback():
    with pytest.raises(ConfigError):
        FallbackClient(
            primary=FakeLLMClient(name="openrouter"),
            fallback=FakeLLMClient(name="ollama"),
            stage="enrich",
        )
