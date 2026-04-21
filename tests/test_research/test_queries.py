import json

import httpx
import pytest
import respx

from king_context.research.config import ResearchConfig
from king_context.research.queries import (
    QueryGenerationError,
    SourceSummary,
    _RETRY_DELAYS,
    _normalize,
    generate_queries,
)
from king_context.scraper.config import ScraperConfig


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def make_config() -> ResearchConfig:
    return ResearchConfig(
        scraper=ScraperConfig(
            openrouter_api_key="fake-or-key",
            enrichment_model="test-model",
        ),
        exa_api_key="exa-fake",
    )


def openrouter_payload(queries: list[str]) -> dict:
    return {
        "choices": [
            {"message": {"content": json.dumps({"queries": queries})}}
        ]
    }


def openrouter_raw(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


@pytest.mark.asyncio
@respx.mock
async def test_initial_generation_returns_requested_count():
    config = make_config()
    respx.post(OPENROUTER_URL).mock(
        return_value=httpx.Response(
            200, json=openrouter_payload(["q1", "q2", "q3"])
        )
    )

    result = await generate_queries("semantic search", 3, config)

    assert result == ["q1", "q2", "q3"]


@pytest.mark.asyncio
@respx.mock
async def test_followup_dedupes_against_previous_queries():
    config = make_config()
    respx.post(OPENROUTER_URL).mock(
        return_value=httpx.Response(
            200,
            json=openrouter_payload(
                ["new angle A", "Semantic Search Basics.", "new angle B"]
            ),
        )
    )

    previous = ["semantic search basics"]
    result = await generate_queries(
        "semantic search",
        5,
        config,
        previous_queries=previous,
    )

    assert "new angle A" in result
    assert "new angle B" in result
    assert len(result) == 2
    for r in result:
        assert _normalize(r) != "semantic search basics"


@pytest.mark.asyncio
@respx.mock
async def test_malformed_llm_output_raises():
    config = make_config()
    respx.post(OPENROUTER_URL).mock(
        return_value=httpx.Response(200, json=openrouter_raw("not-json {"))
    )

    with pytest.raises(QueryGenerationError):
        await generate_queries("topic", 3, config)


@pytest.mark.asyncio
@respx.mock
async def test_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr(
        "king_context.research.queries._RETRY_DELAYS", [0.0, 0.0]
    )
    config = make_config()

    route = respx.post(OPENROUTER_URL).mock(
        side_effect=[
            httpx.Response(429, json={"error": "rate limited"}),
            httpx.Response(200, json=openrouter_payload(["a", "b"])),
        ]
    )

    result = await generate_queries("topic", 2, config)

    assert result == ["a", "b"]
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_fails_fast_on_401():
    config = make_config()
    route = respx.post(OPENROUTER_URL).mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )

    with pytest.raises(QueryGenerationError):
        await generate_queries("topic", 3, config)

    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_handles_markdown_wrapped_json():
    config = make_config()
    wrapped = "```json\n" + json.dumps({"queries": ["x", "y"]}) + "\n```"
    respx.post(OPENROUTER_URL).mock(
        return_value=httpx.Response(200, json=openrouter_raw(wrapped))
    )

    result = await generate_queries("topic", 2, config)

    assert result == ["x", "y"]


@pytest.mark.asyncio
@respx.mock
async def test_bare_list_response_accepted():
    config = make_config()
    respx.post(OPENROUTER_URL).mock(
        return_value=httpx.Response(
            200, json=openrouter_raw(json.dumps(["only", "list"]))
        )
    )

    result = await generate_queries("topic", 5, config)

    assert result == ["only", "list"]


@pytest.mark.asyncio
@respx.mock
async def test_caps_returned_list_to_count():
    config = make_config()
    respx.post(OPENROUTER_URL).mock(
        return_value=httpx.Response(
            200, json=openrouter_payload(["a", "b", "c", "d", "e"])
        )
    )

    result = await generate_queries("topic", 2, config)

    assert result == ["a", "b"]


@pytest.mark.asyncio
@respx.mock
async def test_previous_results_included_in_prompt():
    config = make_config()
    captured: dict = {}

    def capture(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=openrouter_payload(["followup1"]))

    respx.post(OPENROUTER_URL).mock(side_effect=capture)

    summaries = [
        SourceSummary(title="Paper A", top_highlight="Key insight about X"),
    ]
    result = await generate_queries(
        "topic", 1, config, previous_results=summaries
    )

    assert result == ["followup1"]
    user_msg = captured["body"]["messages"][-1]["content"]
    assert "Paper A" in user_msg
    assert "Key insight about X" in user_msg


def test_retry_delays_module_constant_exists():
    assert _RETRY_DELAYS == [1.0, 2.0]
