"""LLM-backed search query generation for the research pipeline."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import string
from dataclasses import dataclass

import httpx

from king_context.research.config import ResearchConfig


log = logging.getLogger(__name__)

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_REQUEST_TIMEOUT = 30.0
_MAX_ATTEMPTS = 3
_RETRY_DELAYS: list[float] = [1.0, 2.0]
_HIGHLIGHT_MAX_CHARS = 240

_SYSTEM_PROMPT = (
    "You are a research query planner. "
    'Output STRICTLY a JSON object with a single key "queries" whose value is an '
    "array of strings. No prose, no explanation."
)

_WS_RE = re.compile(r"\s+")
_MD_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL | re.IGNORECASE)


class QueryGenerationError(Exception):
    """LLM call failed or response was unusable."""


@dataclass
class SourceSummary:
    title: str
    top_highlight: str


def _normalize(query: str) -> str:
    """Lowercase, collapse whitespace, strip trailing punctuation."""
    collapsed = _WS_RE.sub(" ", query.strip().lower())
    return collapsed.rstrip(string.punctuation + " ")


def _build_user_prompt(
    topic: str,
    count: int,
    previous_results: list[SourceSummary] | None,
    previous_queries: list[str] | None,
) -> str:
    parts: list[str] = [
        f"Topic: {topic}",
        f"Generate {count} distinct search queries that cover complementary "
        "angles of the topic.",
    ]

    if previous_queries:
        parts.append(
            "Avoid duplicating these queries (any substring or close rewording):"
        )
        for q in previous_queries:
            parts.append(f"- {q}")

    if previous_results:
        parts.append(
            "Here is a condensed view of what was already found. Use this to "
            "emit FOLLOW-UP queries that dig deeper into promising themes — "
            "not queries that would retrieve the same pages."
        )
        for item in previous_results:
            highlight = (item.top_highlight or "").strip()
            if len(highlight) > _HIGHLIGHT_MAX_CHARS:
                highlight = highlight[: _HIGHLIGHT_MAX_CHARS - 1].rstrip() + "…"
            parts.append(f'- "{item.title}" — {highlight}')

    return "\n".join(parts)


def _strip_code_fence(content: str) -> str:
    stripped = content.strip()
    match = _MD_FENCE_RE.match(stripped)
    if match:
        return match.group(1).strip()
    return stripped


def _extract_queries(raw_content: str) -> list[str]:
    """Parse the model's content string into a list of query strings."""
    content = _strip_code_fence(raw_content)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise QueryGenerationError(
            f"LLM response was not valid JSON: {exc}"
        ) from exc

    if isinstance(parsed, list):
        candidates = parsed
    elif isinstance(parsed, dict) and isinstance(parsed.get("queries"), list):
        candidates = parsed["queries"]
    else:
        raise QueryGenerationError(
            "LLM response did not contain a list of queries"
        )

    queries: list[str] = []
    for item in candidates:
        if isinstance(item, str) and item.strip():
            queries.append(item.strip())
    return queries


def _should_retry(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


def _is_fatal_client_error(status_code: int) -> bool:
    return status_code in (400, 401)


async def _post_once(
    client: httpx.AsyncClient,
    payload: dict,
    api_key: str,
) -> httpx.Response:
    return await client.post(
        _OPENROUTER_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
    )


async def _call_openrouter(
    system_prompt: str,
    user_prompt: str,
    model: str,
    api_key: str,
) -> str:
    """POST to OpenRouter with retries. Returns the raw ``content`` string."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }

    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = await _post_once(client, payload, api_key)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_error = exc
                log.warning(
                    "OpenRouter transient error on attempt %d: %s", attempt + 1, exc
                )
            else:
                status = response.status_code
                if status < 400:
                    data = response.json()
                    try:
                        return data["choices"][0]["message"]["content"]
                    except (KeyError, IndexError, TypeError) as exc:
                        raise QueryGenerationError(
                            f"Unexpected OpenRouter response shape: {exc}"
                        ) from exc

                if _is_fatal_client_error(status):
                    raise QueryGenerationError(
                        f"OpenRouter rejected request (status {status}): "
                        f"{response.text[:200]}"
                    )

                if not _should_retry(status):
                    raise QueryGenerationError(
                        f"OpenRouter returned status {status}: "
                        f"{response.text[:200]}"
                    )

                last_error = httpx.HTTPStatusError(
                    f"status {status}", request=response.request, response=response
                )
                log.warning(
                    "OpenRouter retryable status %d on attempt %d", status, attempt + 1
                )

            if attempt < len(_RETRY_DELAYS):
                await asyncio.sleep(_RETRY_DELAYS[attempt])

    raise QueryGenerationError(
        f"OpenRouter call failed after {_MAX_ATTEMPTS} attempts: {last_error}"
    )


def _dedup(
    candidates: list[str],
    previous_queries: list[str] | None,
    count: int,
) -> list[str]:
    seen: set[str] = set()
    if previous_queries:
        for q in previous_queries:
            seen.add(_normalize(q))

    out: list[str] = []
    for q in candidates:
        norm = _normalize(q)
        if not norm:
            continue
        if norm in seen:
            log.info("Skipping duplicate query: %r", q)
            continue
        seen.add(norm)
        out.append(q)
        if len(out) >= count:
            break

    return out


async def generate_queries(
    topic: str,
    count: int,
    config: ResearchConfig,
    *,
    previous_results: list[SourceSummary] | None = None,
    previous_queries: list[str] | None = None,
) -> list[str]:
    """Generate up to ``count`` distinct search queries for ``topic``.

    Initial call: ``previous_results``/``previous_queries`` are ``None`` and the
    model returns fresh queries for the topic. Follow-up call: pass the prior
    summaries/queries; the LLM emits follow-ups that dig deeper.
    """
    if count <= 0:
        return []

    model = config.research_model or config.scraper.enrichment_model
    if not model:
        raise QueryGenerationError("No model configured for query generation")
    if not config.scraper.openrouter_api_key:
        raise QueryGenerationError("OPENROUTER_API_KEY is not configured")

    user_prompt = _build_user_prompt(topic, count, previous_results, previous_queries)
    raw_content = await _call_openrouter(
        _SYSTEM_PROMPT,
        user_prompt,
        model,
        config.scraper.openrouter_api_key,
    )

    candidates = _extract_queries(raw_content)
    return _dedup(candidates, previous_queries, count)
