import asyncio
from unittest.mock import patch

import pytest

from conftest import FakeLLMClient, fake_stage_clients
from king_context.scraper.chunk import Chunk
from king_context.scraper.config import ScraperConfig
from king_context.scraper.enrich import (
    EnrichedChunk,
    enrich_chunks,
    estimate_cost,
    validate_enrichment,
)
from llm_providers.base import ProviderError
from llm_providers.fallback import FallbackClient


def make_chunk(title: str = "Test Section", content: str = "Some content here.") -> Chunk:
    return Chunk(
        title=title,
        breadcrumb=title,
        content=content,
        source_url="https://docs.example.com/page",
        path="/page/test-section",
        token_count=10,
    )


def make_valid_enrichment() -> dict:
    return {
        "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
        "use_cases": ["Use when authenticating users", "Configure when setting up OAuth"],
        "tags": ["authentication"],
        "priority": 8,
    }


def test_enrich_batch_processing():
    config = ScraperConfig(
        openrouter_api_key="test-key",
        enrichment_batch_size=5,
    )
    chunks = [make_chunk(f"Section {i}") for i in range(12)]

    call_count = 0

    async def mock_complete(prompt, *, system=None, json_mode=True):
        nonlocal call_count
        call_count += 1
        return make_valid_enrichment()

    client = FakeLLMClient(side_effect=mock_complete)
    with patch(
        "king_context.scraper.enrich.get_stage_clients",
        return_value=fake_stage_clients(client),
    ):
        result = asyncio.run(enrich_chunks(chunks, config))

    assert len(result) == 12
    assert call_count == 12  # one call per chunk


def test_enrich_validation_valid():
    enrichment = make_valid_enrichment()
    errors = validate_enrichment(enrichment)
    assert errors == []


def test_enrich_validation_invalid():
    enrichment = {
        "keywords": ["only", "four", "items", "here"],  # < 5 — invalid
        "use_cases": ["Use when needed", "Configure when required"],
        "tags": ["api"],
        "priority": 5,
    }
    errors = validate_enrichment(enrichment)
    assert len(errors) == 1
    assert "keywords" in errors[0]


def test_enrich_retry_on_validation_fail():
    config = ScraperConfig(
        openrouter_api_key="test-key",
        enrichment_batch_size=5,
    )
    chunk = make_chunk("Auth Section")

    attempt = {"count": 0}
    invalid = {
        "keywords": ["one", "two"],  # too few
        "use_cases": ["Use when needed", "Configure it"],
        "tags": ["auth"],
        "priority": 7,
    }
    valid = make_valid_enrichment()

    async def mock_complete(prompt, *, system=None, json_mode=True):
        attempt["count"] += 1
        if attempt["count"] == 1:
            return invalid
        return valid

    client = FakeLLMClient(side_effect=mock_complete)
    with patch(
        "king_context.scraper.enrich.get_stage_clients",
        return_value=fake_stage_clients(client),
    ):
        result = asyncio.run(enrich_chunks([chunk], config))

    assert len(result) == 1
    assert attempt["count"] == 2  # failed once, succeeded on retry
    assert len(result[0].keywords) == 5


def test_enrich_surfaces_provider_error_from_fallback_client():
    config = ScraperConfig(
        openrouter_api_key="test-key",
        enrichment_batch_size=5,
    )
    chunk = make_chunk("Auth Section")
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

    with patch(
        "king_context.scraper.enrich.get_stage_clients",
        return_value=fake_stage_clients(client),
    ):
        with pytest.raises(ProviderError) as exc:
            asyncio.run(enrich_chunks([chunk], config))

    assert exc.value.primary_error is primary_error
    assert exc.value.fallback_error is fallback_error


def test_estimate_cost():
    config = ScraperConfig(
        enrichment_model="openai/gpt-4o-mini",
        enrichment_batch_size=5,
    )
    chunks = [make_chunk(content=" ".join(["word"] * 100)) for _ in range(10)]
    # Each chunk has token_count=10 (from make_chunk default)

    cost = estimate_cost(chunks, config)

    assert cost["total_chunks"] == 10
    assert cost["total_batches"] == 2  # 10 chunks / batch_size 5 = 2 batches
    assert cost["model"] == "openai/gpt-4o-mini"
    assert "estimated_input_tokens" in cost
    assert "estimated_output_tokens" in cost
    assert "estimated_cost" in cost
    assert cost["estimated_cost"] >= 0
    # Output tokens: 10 chunks * 150 = 1500
    assert cost["estimated_output_tokens"] == 1500
