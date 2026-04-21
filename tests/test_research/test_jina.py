import json

import httpx
import pytest

from king_context.research.jina import (
    FetchResult,
    JinaPermanentError,
    JinaTransientError,
    fetch,
)


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setattr("king_context.research.jina._RETRY_DELAYS", [0.0, 0.0])


def _good_content_response(word_count: int = 100, title: str = "T") -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": {"title": title, "content": " ".join(["word"] * word_count)}},
    )


async def test_fetch_200_with_good_content():
    responses = [_good_content_response(word_count=100, title="Hello")]

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await fetch("https://example.com/a", "", client)

    assert isinstance(result, FetchResult)
    assert result.url == "https://example.com/a"
    assert result.title == "Hello"
    assert result.word_count == 100


async def test_fetch_200_degraded_escalates_engine():
    captured_bodies: list[dict] = []
    responses = [
        httpx.Response(
            200,
            json={"data": {"title": "T", "content": " ".join(["word"] * 10)}},
        ),
        _good_content_response(word_count=100),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        captured_bodies.append(json.loads(request.content.decode()))
        return responses.pop(0)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await fetch("https://example.com/degraded", "", client)

    assert result.word_count == 100
    assert len(captured_bodies) == 2
    assert captured_bodies[0]["engine"] == "direct"
    assert captured_bodies[1]["engine"] == "browser"


async def test_fetch_429_is_transient_retried():
    responses = [
        httpx.Response(429, json={"error": "rate limited"}),
        _good_content_response(word_count=80),
    ]
    call_count = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        call_count[0] += 1
        return responses.pop(0)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await fetch("https://example.com/429", "key", client)

    assert result.word_count == 80
    assert call_count[0] == 2


async def test_fetch_404_is_permanent_no_retry():
    call_count = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        call_count[0] += 1
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(JinaPermanentError):
            await fetch("https://example.com/missing", "", client)

    assert call_count[0] == 1


async def test_fetch_three_transient_raises_last():
    call_count = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        call_count[0] += 1
        return httpx.Response(503, json={"error": "server unavailable"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(JinaTransientError):
            await fetch("https://example.com/down", "", client)

    assert call_count[0] == 3


async def test_fetch_data_as_string_parses():
    markdown = " ".join(["token"] * 60)
    responses = [httpx.Response(200, json={"data": markdown})]

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await fetch("https://example.com/string", "", client)

    assert result.title == ""
    assert result.word_count == 60
    assert result.content == markdown


async def test_no_auth_header_when_api_key_empty():
    captured_headers: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.append(request.headers)
        return _good_content_response(word_count=80)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await fetch("https://example.com/noauth", "", client)

    assert len(captured_headers) == 1
    assert "authorization" not in captured_headers[0]


async def test_auth_header_when_api_key_set():
    captured_headers: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.append(request.headers)
        return _good_content_response(word_count=80)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await fetch("https://example.com/auth", "secret-key", client)

    assert captured_headers[0]["authorization"] == "Bearer secret-key"
