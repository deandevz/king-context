from __future__ import annotations

import asyncio
import dataclasses
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

JINA_BASE_URL = "https://r.jina.ai/"
WORD_COUNT_THRESHOLD = 50
_ENGINE_SEQUENCE = ["direct", "browser", "browser"]
_TIMEOUT_SEQUENCE = [30, 30, 60]
_RETRY_DELAYS = [2.0, 5.0]


class JinaTransientError(Exception):
    """Retry-able server or network error (429, 5xx, timeouts, connect errors)."""


class JinaPermanentError(Exception):
    """Non-retry-able (400, 401, 403, 404, 422). Skip this URL."""


class JinaDegradedError(Exception):
    """200 OK but content below WORD_COUNT_THRESHOLD. Escalate engine on retry."""


@dataclasses.dataclass
class FetchResult:
    url: str
    title: str
    content: str
    word_count: int


def _build_body(url: str, engine: str, timeout: int) -> dict[str, Any]:
    return {
        "url": url,
        "respondWith": "markdown",
        "engine": engine,
        "respondTiming": "network-idle",
        "retainLinks": "none",
        "retainImages": "none",
        "removeSelector": "nav, footer, aside, .ad, .cookie-banner, .sidebar",
        "timeout": timeout,
    }


def _parse_response(payload: dict[str, Any], url: str) -> FetchResult:
    data = payload.get("data") or {}
    if isinstance(data, str):
        content = data
        title = ""
    else:
        content = data.get("content") or data.get("text") or ""
        title = data.get("title") or ""
    word_count = len(content.split())
    return FetchResult(url=url, title=title, content=content, word_count=word_count)


async def _attempt(
    url: str,
    api_key: str,
    client: httpx.AsyncClient,
    engine: str,
    jina_timeout: int,
) -> FetchResult:
    headers = {
        "Accept": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = _build_body(url, engine, jina_timeout)
    client_timeout = httpx.Timeout(jina_timeout + 5.0)

    try:
        resp = await client.post(
            JINA_BASE_URL, json=body, headers=headers, timeout=client_timeout
        )
    except httpx.TimeoutException as exc:
        raise JinaTransientError(f"Client timeout fetching {url}") from exc
    except httpx.ConnectError as exc:
        raise JinaTransientError(f"Connection error fetching {url}") from exc

    if resp.status_code == 429 or resp.status_code >= 500:
        raise JinaTransientError(f"HTTP {resp.status_code} for {url}")
    if resp.status_code in (400, 401, 403, 404, 422):
        raise JinaPermanentError(f"HTTP {resp.status_code} for {url}")
    if resp.status_code != 200:
        raise JinaTransientError(f"Unexpected HTTP {resp.status_code} for {url}")

    payload: dict[str, Any] = resp.json()
    result = _parse_response(payload, url)

    if result.word_count < WORD_COUNT_THRESHOLD:
        raise JinaDegradedError(
            f"Insufficient content ({result.word_count} words) for {url}"
        )
    return result


async def fetch(url: str, api_key: str, client: httpx.AsyncClient) -> FetchResult:
    """Fetch and clean a URL via Jina Reader with retry + engine escalation."""
    last_exc: Exception = JinaPermanentError("No attempts made")

    for attempt in range(3):
        engine = _ENGINE_SEQUENCE[attempt]
        jina_timeout = _TIMEOUT_SEQUENCE[attempt]
        try:
            result = await _attempt(url, api_key, client, engine, jina_timeout)
            log.debug("Jina fetch OK: %s (attempt %d, engine=%s)", url, attempt + 1, engine)
            return result
        except JinaPermanentError:
            raise
        except (JinaTransientError, JinaDegradedError) as exc:
            log.warning("Jina attempt %d failed for %s: %s", attempt + 1, url, exc)
            last_exc = exc
            if attempt < len(_RETRY_DELAYS):
                await asyncio.sleep(_RETRY_DELAYS[attempt])

    raise last_exc
