from unittest.mock import AsyncMock, patch

import httpx
import pytest

from king_context.research.config import ResearchConfig
from king_context.research.exa import ExaResult
from king_context.research.fetch import (
    MIN_CONTENT_CHARS,
    SourceDoc,
    fetch_for_query,
)
from king_context.research.jina import (
    FetchResult,
    JinaPermanentError,
    JinaTransientError,
)
from king_context.scraper.config import ScraperConfig


def make_config() -> ResearchConfig:
    return ResearchConfig(
        scraper=ScraperConfig(openrouter_api_key="fake", concurrency=5),
        exa_api_key="exa-fake",
        jina_api_key="jina-fake",
    )


def make_exa_result(url: str, text_len: int = 700) -> ExaResult:
    return ExaResult(
        url=url,
        title="T",
        text="x" * text_len,
        highlights=[],
        author="Alice",
        published_date="2024-01-01",
        score=0.9,
    )


def make_jina_result(url: str, title: str = "Jina Title") -> FetchResult:
    content = "word " * 200
    return FetchResult(
        url=url, title=title, content=content, word_count=200
    )


async def test_all_exa_sufficient_no_jina_called():
    results = [make_exa_result(f"https://ex.com/{i}", 700) for i in range(3)]
    async with httpx.AsyncClient() as client:
        with patch(
            "king_context.research.fetch.exa_search",
            new_callable=AsyncMock,
            return_value=results,
        ), patch(
            "king_context.research.fetch.jina_fetch", new_callable=AsyncMock
        ) as mock_jina:
            docs = await fetch_for_query("q", 0, make_config(), client)

    assert len(docs) == 3
    assert all(isinstance(d, SourceDoc) for d in docs)
    assert all(d.fetch_path == "exa" for d in docs)
    assert all(d.query == "q" for d in docs)
    assert all(d.discovery_iteration == 0 for d in docs)
    assert docs[0].domain == "ex.com"
    mock_jina.assert_not_called()


async def test_some_exa_short_jina_called_for_those():
    long_1 = make_exa_result("https://ex.com/long1", text_len=MIN_CONTENT_CHARS)
    long_2 = make_exa_result("https://ex.com/long2", text_len=MIN_CONTENT_CHARS + 50)
    short = make_exa_result("https://ex.com/short", text_len=100)
    results = [long_1, short, long_2]

    jina_result = make_jina_result("https://ex.com/short", title="Short Page")

    async with httpx.AsyncClient() as client:
        with patch(
            "king_context.research.fetch.exa_search",
            new_callable=AsyncMock,
            return_value=results,
        ), patch(
            "king_context.research.fetch.jina_fetch",
            new_callable=AsyncMock,
            return_value=jina_result,
        ) as mock_jina:
            docs = await fetch_for_query("query", 1, make_config(), client)

    assert len(docs) == 3
    mock_jina.assert_called_once()
    call_args = mock_jina.call_args
    assert call_args.args[0] == "https://ex.com/short"

    exa_docs = [d for d in docs if d.fetch_path == "exa"]
    jina_docs = [d for d in docs if d.fetch_path == "jina"]
    assert len(exa_docs) == 2
    assert len(jina_docs) == 1
    assert jina_docs[0].url == "https://ex.com/short"
    assert jina_docs[0].title == "Short Page"
    assert jina_docs[0].author == "Alice"
    assert jina_docs[0].published_date == "2024-01-01"
    assert jina_docs[0].score == 0.9
    assert jina_docs[0].discovery_iteration == 1


async def test_jina_permanent_failure_drops_url_others_continue():
    long_1 = make_exa_result("https://ex.com/ok1", text_len=700)
    long_2 = make_exa_result("https://ex.com/ok2", text_len=800)
    short = make_exa_result("https://ex.com/bad", text_len=50)
    results = [long_1, short, long_2]

    async def raising_fetch(*args, **kwargs):
        raise JinaPermanentError("HTTP 404")

    async with httpx.AsyncClient() as client:
        with patch(
            "king_context.research.fetch.exa_search",
            new_callable=AsyncMock,
            return_value=results,
        ), patch(
            "king_context.research.fetch.jina_fetch",
            side_effect=raising_fetch,
        ):
            docs = await fetch_for_query("q", 0, make_config(), client)

    assert len(docs) == 2
    assert all(d.fetch_path == "exa" for d in docs)
    urls = {d.url for d in docs}
    assert urls == {"https://ex.com/ok1", "https://ex.com/ok2"}


async def test_empty_exa_returns_empty_list():
    async with httpx.AsyncClient() as client:
        with patch(
            "king_context.research.fetch.exa_search",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "king_context.research.fetch.jina_fetch", new_callable=AsyncMock
        ) as mock_jina:
            docs = await fetch_for_query("q", 0, make_config(), client)

    assert docs == []
    mock_jina.assert_not_called()


async def test_jina_transient_after_retries_drops_url():
    short = make_exa_result("https://ex.com/short", text_len=50)
    results = [short]

    async def raising_fetch(*args, **kwargs):
        raise JinaTransientError("HTTP 503")

    async with httpx.AsyncClient() as client:
        with patch(
            "king_context.research.fetch.exa_search",
            new_callable=AsyncMock,
            return_value=results,
        ), patch(
            "king_context.research.fetch.jina_fetch",
            side_effect=raising_fetch,
        ):
            docs = await fetch_for_query("q", 0, make_config(), client)

    assert docs == []
