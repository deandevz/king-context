from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from king_context.research.config import ResearchConfig
from king_context.research.exa import (
    ExaBudgetError,
    ExaConfigError,
    ExaResult,
    ExaTransientError,
    search,
)
from king_context.scraper.config import ScraperConfig


class FakeExaError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


def make_config() -> ResearchConfig:
    return ResearchConfig(
        scraper=ScraperConfig(openrouter_api_key="fake"),
        exa_api_key="exa-fake",
    )


def make_fake_result(**overrides):
    mock = MagicMock()
    mock.url = overrides.get("url", "https://example.com/a")
    mock.title = overrides.get("title", "Sample")
    mock.text = overrides.get("text", "Sample content")
    mock.highlights = overrides.get("highlights", ["highlight"])
    mock.author = overrides.get("author", "Alice")
    mock.published_date = overrides.get("published_date", "2024-01-01")
    mock.score = overrides.get("score", 0.9)
    return mock


def make_fake_response(results):
    resp = MagicMock()
    resp.results = results
    return resp


async def test_search_success():
    config = make_config()
    results = [
        make_fake_result(url="https://a.example.com", title="A"),
        make_fake_result(
            url="https://b.example.com",
            title="B",
            text="Other text",
            highlights=[],
            author=None,
            published_date=None,
            score=0.5,
        ),
    ]
    fake_response = make_fake_response(results)

    with patch("king_context.research.exa.Exa") as mock_exa_cls:
        mock_exa_cls.return_value.search_and_contents.return_value = fake_response
        out = await search("hello world", config)

    assert len(out) == 2
    assert all(isinstance(r, ExaResult) for r in out)
    assert out[0].url == "https://a.example.com"
    assert out[0].title == "A"
    assert out[0].text == "Sample content"
    assert out[0].highlights == ["highlight"]
    assert out[0].author == "Alice"
    assert out[0].published_date == "2024-01-01"
    assert out[0].score == 0.9
    assert out[1].highlights == []
    assert out[1].author is None
    assert out[1].published_date is None


async def test_search_retries_on_transient_then_succeeds():
    config = make_config()
    results = [make_fake_result()]
    fake_response = make_fake_response(results)

    with patch("king_context.research.exa.Exa") as mock_exa_cls, patch(
        "king_context.research.exa.asyncio.sleep", AsyncMock()
    ) as mock_sleep:
        mock_exa_cls.return_value.search_and_contents.side_effect = [
            FakeExaError(429),
            fake_response,
        ]
        out = await search("retry test", config)

    assert len(out) == 1
    assert out[0].url == "https://example.com/a"
    assert mock_sleep.await_count == 1


async def test_search_budget_error_raises():
    config = make_config()
    with patch("king_context.research.exa.Exa") as mock_exa_cls, patch(
        "king_context.research.exa.asyncio.sleep", AsyncMock()
    ) as mock_sleep:
        mock_exa_cls.return_value.search_and_contents.side_effect = FakeExaError(402)
        with pytest.raises(ExaBudgetError):
            await search("budget test", config)
        assert mock_sleep.await_count == 0
        assert mock_exa_cls.return_value.search_and_contents.call_count == 1


async def test_search_config_error_raises():
    config = make_config()
    with patch("king_context.research.exa.Exa") as mock_exa_cls, patch(
        "king_context.research.exa.asyncio.sleep", AsyncMock()
    ):
        mock_exa_cls.return_value.search_and_contents.side_effect = FakeExaError(401)
        with pytest.raises(ExaConfigError):
            await search("config test", config)
        assert mock_exa_cls.return_value.search_and_contents.call_count == 1


async def test_search_unprocessable_returns_empty():
    config = make_config()
    with patch("king_context.research.exa.Exa") as mock_exa_cls, patch(
        "king_context.research.exa.asyncio.sleep", AsyncMock()
    ):
        mock_exa_cls.return_value.search_and_contents.side_effect = FakeExaError(422)
        out = await search("unprocessable test", config)

    assert out == []


async def test_search_retries_exhausted_raises_transient():
    config = make_config()
    with patch("king_context.research.exa.Exa") as mock_exa_cls, patch(
        "king_context.research.exa.asyncio.sleep", AsyncMock()
    ) as mock_sleep:
        mock_exa_cls.return_value.search_and_contents.side_effect = FakeExaError(503)
        with pytest.raises(ExaTransientError):
            await search("exhausted test", config)

    assert mock_sleep.await_count == 2
    assert mock_exa_cls.return_value.search_and_contents.call_count == 3


def test_exa_sdk_importable():
    import exa_py  # noqa: F401

    assert exa_py is not None
