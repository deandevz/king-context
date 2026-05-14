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
    chunks = [make_chunk(f"Section {i}", content=f"Body {i}") for i in range(12)]

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


def test_enrich_retries_transient_provider_error():
    config = ScraperConfig(
        openrouter_api_key="test-key",
        enrichment_batch_size=5,
    )
    chunk = make_chunk("Auth Section")
    provider_error = ProviderError(
        "timeout",
        transient=True,
        message="timeout",
        provider="openrouter",
    )
    client = FakeLLMClient(responses=[provider_error, make_valid_enrichment()])

    with patch(
        "king_context.scraper.enrich.get_stage_clients",
        return_value=fake_stage_clients(client),
    ):
        result = asyncio.run(enrich_chunks([chunk], config))

    assert len(result) == 1
    assert len(client.calls) == 2


def test_enrich_drops_chunk_after_transient_retries_exhausted():
    """Per-chunk failure must not abort the batch (#47).

    With no schema fallback configured, three transient errors leave the
    chunk unrecovered. New contract: ``enrich_chunks`` returns a list with
    that chunk omitted; no exception escapes.
    """
    config = ScraperConfig(
        openrouter_api_key="test-key",
        enrichment_batch_size=5,
    )
    chunk = make_chunk("Auth Section")
    provider_errors = [
        ProviderError(
            "timeout",
            transient=True,
            message="timeout",
            provider="openrouter",
        )
        for _ in range(3)
    ]
    client = FakeLLMClient(responses=provider_errors)

    with patch(
        "king_context.scraper.enrich.get_stage_clients",
        return_value=fake_stage_clients(client),
    ):
        result = asyncio.run(enrich_chunks([chunk], config))

    assert result == []
    assert len(client.calls) == 3


def test_enrich_respects_fallback_provider_concurrency():
    config = ScraperConfig(
        openrouter_api_key="test-key",
        enrichment_batch_size=3,
    )
    chunks = [make_chunk(f"Section {i}") for i in range(3)]
    in_flight = 0
    max_in_flight = 0

    async def fail_primary(prompt, *, system=None, json_mode=True):
        raise ProviderError(
            "timeout",
            transient=True,
            message="timeout",
            provider="ollama",
        )

    async def fallback_complete(prompt, *, system=None, json_mode=True):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        try:
            await asyncio.sleep(0.01)
            return make_valid_enrichment()
        finally:
            in_flight -= 1

    fallback = FakeLLMClient(
        name="openrouter",
        concurrency=1,
        side_effect=fallback_complete,
    )
    client = FallbackClient(
        primary=FakeLLMClient(
            name="ollama",
            concurrency=3,
            side_effect=fail_primary,
        ),
        fallback=fallback,
        stage="enrich",
    )

    with patch(
        "king_context.scraper.enrich.get_stage_clients",
        return_value=fake_stage_clients(client, fallback),
    ):
        result = asyncio.run(enrich_chunks(chunks, config))

    assert len(result) == 3
    assert max_in_flight == 1


def test_enrich_drops_chunk_when_fallback_client_also_fails():
    """A FallbackClient whose both legs throw must not abort the batch."""
    config = ScraperConfig(
        openrouter_api_key="test-key",
        enrichment_batch_size=5,
    )
    chunk = make_chunk("Auth Section")
    primary_errors = [
        ProviderError(
            "timeout",
            transient=True,
            message="timeout",
            provider="ollama",
        )
        for _ in range(3)
    ]
    fallback_errors = [
        ProviderError(
            "rate_limit",
            transient=True,
            message="limited",
            provider="openrouter",
        )
        for _ in range(3)
    ]
    client = FallbackClient(
        primary=FakeLLMClient(responses=primary_errors, name="ollama"),
        fallback=FakeLLMClient(responses=fallback_errors, name="openrouter"),
        stage="enrich",
    )

    with patch(
        "king_context.scraper.enrich.get_stage_clients",
        return_value=fake_stage_clients(client),
    ):
        result = asyncio.run(enrich_chunks([chunk], config))

    assert result == []


def test_enrich_drops_chunk_on_non_transient_fallback_error():
    """Non-transient fallback errors are absorbed; the batch keeps going."""
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
        "auth_error",
        transient=False,
        message="unauthorized",
        provider="openrouter",
    )
    primary = FakeLLMClient(responses=[primary_error], name="ollama")
    fallback = FakeLLMClient(responses=[fallback_error], name="openrouter")
    client = FallbackClient(
        primary=primary,
        fallback=fallback,
        stage="enrich",
    )

    with patch(
        "king_context.scraper.enrich.get_stage_clients",
        return_value=fake_stage_clients(client, fallback),
    ):
        result = asyncio.run(enrich_chunks([chunk], config))

    assert result == []
    assert len(primary.calls) == 1
    # The schema_fallback is identity-equal to the FallbackClient's inner
    # fallback leg (after _SemaphoredClient unwrapping), so enrich_chunks
    # dedupes it: the fallback client is called exactly once, by
    # FallbackClient's internal step. Without the dedupe, _enrich_one
    # would call it again as a schema-fallback retry and waste a request.
    assert len(fallback.calls) == 1


def test_enrich_drops_chunk_when_schema_fallback_returns_invalid_metadata():
    """Schema fallback returning invalid metadata is absorbed; chunk dropped."""
    config = ScraperConfig(
        openrouter_api_key="test-key",
        enrichment_batch_size=5,
    )
    chunk = make_chunk("Auth Section")
    invalid = {
        "keywords": ["one"],
        "use_cases": ["Use when needed", "Configure when required"],
        "tags": ["auth"],
        "priority": 7,
    }
    primary = FakeLLMClient(responses=[invalid, invalid, invalid], name="ollama")
    fallback = FakeLLMClient(responses=[invalid], name="openrouter")

    with patch(
        "king_context.scraper.enrich.get_stage_clients",
        return_value=fake_stage_clients(primary, fallback),
    ):
        result = asyncio.run(enrich_chunks([chunk], config))

    assert result == []
    assert len(primary.calls) == 3
    assert len(fallback.calls) == 1


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


def test_enrich_schema_fallback_success_does_not_poison_primary_cache(tmp_path):
    """Schema fallback's output must not be cached under the primary's key.

    If it were, a subsequent run with the primary healthy would short-
    circuit at the cache check and serve the previous fallback's output
    as if it were primary content. The fix in #47 caches only successful
    primary responses.
    """
    config = ScraperConfig(
        openrouter_api_key="test-key",
        enrichment_batch_size=5,
    )
    chunk = make_chunk("Auth Section", content="this content needs enrichment")

    async def primary_fails(prompt, *, system=None, json_mode=True):
        raise ProviderError(
            "invalid_response",
            transient=False,
            message="LLM response was not parseable JSON",
            provider="openrouter",
        )

    primary = FakeLLMClient(side_effect=primary_fails, name="openrouter")
    fallback = FakeLLMClient(
        responses=[make_valid_enrichment()], name="openrouter-fallback"
    )

    with patch(
        "king_context.scraper.enrich.get_stage_clients",
        return_value=fake_stage_clients(primary, fallback),
    ):
        first = asyncio.run(enrich_chunks([chunk], config))

    assert len(first) == 1  # fallback succeeded

    # Now check the cache: the primary's cache key MUST NOT carry the
    # fallback's enrichment, otherwise the contract is broken.
    from king_context.scraper import enrich_cache as cache
    from king_context.scraper.enrich import PROMPT_VERSION
    primary_cache_key = cache.make_key(chunk.content, "test-model", PROMPT_VERSION)
    cached = cache.get(primary_cache_key)
    assert cached is None, (
        "schema fallback's enrichment leaked into the primary's cache key; "
        "next run with the primary healthy would serve fallback content."
    )


def test_enrich_one_bad_chunk_does_not_abort_batch(capsys):
    """The #47 repro: one chunk with non-transient ProviderError, others succeed.

    Pre-fix, a single non-transient ProviderError raised by ``_enrich_one``
    would propagate through ``asyncio.gather`` and cancel every other chunk
    in flight. After the fix, the failing chunk is dropped and the batch
    completes with the surviving chunks.
    """
    config = ScraperConfig(
        openrouter_api_key="test-key",
        enrichment_batch_size=5,
    )
    chunks = [
        make_chunk("Good 1", content="good content one"),
        make_chunk("Bad", content="bad content"),
        make_chunk("Good 2", content="good content two"),
    ]
    valid = make_valid_enrichment()
    bad_error = ProviderError(
        "invalid_response",
        transient=False,
        message="LLM response was not parseable JSON",
        provider="openrouter",
    )

    async def mock_complete(prompt, *, system=None, json_mode=True):
        if "bad content" in prompt:
            raise bad_error
        return valid

    client = FakeLLMClient(side_effect=mock_complete)
    with patch(
        "king_context.scraper.enrich.get_stage_clients",
        return_value=fake_stage_clients(client),
    ):
        result = asyncio.run(enrich_chunks(chunks, config))

    # Two surviving chunks; the bad one is dropped, no exception raised.
    assert len(result) == 2
    titles = {e.title for e in result}
    assert titles == {"Good 1", "Good 2"}


def test_enrich_non_transient_primary_error_falls_through_to_schema_fallback():
    """Non-transient primary errors must reach the schema fallback (#47).

    The schema fallback exists precisely to absorb malformed JSON from the
    primary. Pre-fix, a non-transient ``ProviderError`` from the primary
    raised on the first attempt and never reached the fallback path.
    """
    config = ScraperConfig(
        openrouter_api_key="test-key",
        enrichment_batch_size=5,
    )
    chunk = make_chunk("Auth Section")

    async def primary_fails(prompt, *, system=None, json_mode=True):
        raise ProviderError(
            "invalid_response",
            transient=False,
            message="LLM response was not parseable JSON",
            provider="openrouter",
        )

    primary = FakeLLMClient(side_effect=primary_fails, name="openrouter")
    fallback = FakeLLMClient(
        responses=[make_valid_enrichment()], name="openrouter-fallback"
    )

    with patch(
        "king_context.scraper.enrich.get_stage_clients",
        return_value=fake_stage_clients(primary, fallback),
    ):
        result = asyncio.run(enrich_chunks([chunk], config))

    assert len(result) == 1
    # Primary should have been tried only once (non-transient breaks the
    # retry loop early). Fallback runs once and succeeds.
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1


def test_enrich_gather_return_exceptions_keeps_other_chunks_alive(capsys):
    """Defensive guard: even if ``_enrich_one`` ever raises, gather absorbs it.

    ``_enrich_one`` is contract-bound to never raise, but ``return_exceptions``
    on the gather call protects against future regressions and against
    asyncio cancellation surfacing through unrelated code paths.
    """
    config = ScraperConfig(
        openrouter_api_key="test-key",
        enrichment_batch_size=5,
    )
    chunks = [
        make_chunk("a", content="alpha"),
        make_chunk("b", content="bravo"),
    ]

    async def mock_complete(prompt, *, system=None, json_mode=True):
        return make_valid_enrichment()

    client = FakeLLMClient(side_effect=mock_complete)

    # Patch _enrich_one itself so the first call raises a synthetic
    # exception. Without return_exceptions=True the second chunk's task
    # would be cancelled when gather propagates the exception.
    from king_context.scraper.enrich import _enrich_one as real_enrich_one

    call_count = {"n": 0}

    async def flaky_enrich_one(chunk, primary_client, schema_fallback=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("synthetic explosion")
        return await real_enrich_one(chunk, primary_client, schema_fallback)

    with patch(
        "king_context.scraper.enrich.get_stage_clients",
        return_value=fake_stage_clients(client),
    ), patch(
        "king_context.scraper.enrich._enrich_one",
        side_effect=flaky_enrich_one,
    ):
        result = asyncio.run(enrich_chunks(chunks, config))

    # Only the second chunk should make it through; the first is logged
    # as a warning and skipped.
    assert len(result) == 1
    err = capsys.readouterr().err
    assert "synthetic explosion" in err
    assert "RuntimeError" in err
    # Per-batch summary line lands on stderr too.
    assert "1 enriched, 1 dropped" in err


def test_enrich_per_chunk_cancellation_does_not_abort_batch(capsys):
    """A child task's CancelledError returned by gather is treated as a drop."""
    config = ScraperConfig(
        openrouter_api_key="test-key",
        enrichment_batch_size=5,
    )
    chunks = [
        make_chunk("a", content="alpha"),
        make_chunk("b", content="bravo"),
    ]

    async def mock_complete(prompt, *, system=None, json_mode=True):
        return make_valid_enrichment()

    client = FakeLLMClient(side_effect=mock_complete)
    from king_context.scraper.enrich import _enrich_one as real_enrich_one

    async def cancelling_enrich_one(chunk, primary_client, schema_fallback=None):
        if chunk.title == "a":
            raise asyncio.CancelledError("simulated per-task cancel")
        return await real_enrich_one(chunk, primary_client, schema_fallback)

    with patch(
        "king_context.scraper.enrich.get_stage_clients",
        return_value=fake_stage_clients(client),
    ), patch(
        "king_context.scraper.enrich._enrich_one",
        side_effect=cancelling_enrich_one,
    ):
        result = asyncio.run(enrich_chunks(chunks, config))

    assert len(result) == 1
    err = capsys.readouterr().err
    assert "cancelled" in err.lower()
