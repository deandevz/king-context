import json

import pytest

from conftest import FakeLLMClient
from king_context.research.config import ResearchConfig
from king_context.research.queries import (
    QueryGenerationError,
    SourceSummary,
    _RETRY_DELAYS,
    _extract_queries,
    _normalize,
    generate_queries,
)
from king_context.scraper.config import ScraperConfig
from llm_providers.base import ProviderError


def make_config() -> ResearchConfig:
    return ResearchConfig(
        scraper=ScraperConfig(
            openrouter_api_key="fake-or-key",
            enrichment_model="test-model",
        ),
        exa_api_key="exa-fake",
    )


def _patch_client(monkeypatch, client: FakeLLMClient) -> None:
    monkeypatch.setattr(
        "king_context.research.queries.get_client",
        lambda *args, **kwargs: client,
    )


@pytest.mark.asyncio
async def test_initial_generation_returns_requested_count(monkeypatch):
    client = FakeLLMClient(responses=[{"queries": ["q1", "q2", "q3"]}])
    _patch_client(monkeypatch, client)

    result = await generate_queries("semantic search", 3, make_config())

    assert result == ["q1", "q2", "q3"]


@pytest.mark.asyncio
async def test_followup_dedupes_against_previous_queries(monkeypatch):
    client = FakeLLMClient(
        responses=[{"queries": ["new angle A", "Semantic Search Basics.", "new angle B"]}]
    )
    _patch_client(monkeypatch, client)

    previous = ["semantic search basics"]
    result = await generate_queries(
        "semantic search",
        5,
        make_config(),
        previous_queries=previous,
    )

    assert "new angle A" in result
    assert "new angle B" in result
    assert len(result) == 2
    for r in result:
        assert _normalize(r) != "semantic search basics"


@pytest.mark.asyncio
async def test_malformed_llm_output_raises(monkeypatch):
    client = FakeLLMClient(responses=[{"not_queries": ["x"]}])
    _patch_client(monkeypatch, client)

    with pytest.raises(QueryGenerationError):
        await generate_queries("topic", 3, make_config())


@pytest.mark.asyncio
async def test_retries_on_transient_provider_error_then_succeeds(monkeypatch):
    monkeypatch.setattr(
        "king_context.research.queries._RETRY_DELAYS", [0.0, 0.0]
    )
    client = FakeLLMClient(
        responses=[
            ProviderError(
                "rate_limit",
                transient=True,
                message="limited",
                provider="openrouter",
            ),
            {"queries": ["a", "b"]},
        ]
    )
    _patch_client(monkeypatch, client)

    result = await generate_queries("topic", 2, make_config())

    assert result == ["a", "b"]
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_fails_fast_on_non_transient_provider_error(monkeypatch):
    client = FakeLLMClient(
        responses=[
            ProviderError(
                "auth_error",
                transient=False,
                message="unauthorized",
                provider="openrouter",
            )
        ]
    )
    _patch_client(monkeypatch, client)

    with pytest.raises(QueryGenerationError):
        await generate_queries("topic", 3, make_config())

    assert len(client.calls) == 1


def test_handles_markdown_wrapped_json():
    wrapped = "```json\n" + json.dumps({"queries": ["x", "y"]}) + "\n```"

    result = _extract_queries(wrapped)

    assert result == ["x", "y"]


def test_bare_list_response_accepted_by_extractor():
    assert _extract_queries(json.dumps(["only", "list"])) == ["only", "list"]


@pytest.mark.asyncio
async def test_caps_returned_list_to_count(monkeypatch):
    client = FakeLLMClient(responses=[{"queries": ["a", "b", "c", "d", "e"]}])
    _patch_client(monkeypatch, client)

    result = await generate_queries("topic", 2, make_config())

    assert result == ["a", "b"]


@pytest.mark.asyncio
async def test_previous_results_included_in_prompt(monkeypatch):
    client = FakeLLMClient(responses=[{"queries": ["followup1"]}])
    _patch_client(monkeypatch, client)

    summaries = [
        SourceSummary(title="Paper A", top_highlight="Key insight about X"),
    ]
    result = await generate_queries(
        "topic", 1, make_config(), previous_results=summaries
    )

    assert result == ["followup1"]
    user_msg = client.calls[0]["prompt"]
    assert "Paper A" in user_msg
    assert "Key insight about X" in user_msg


def test_retry_delays_module_constant_exists():
    assert _RETRY_DELAYS == [1.0, 2.0]
