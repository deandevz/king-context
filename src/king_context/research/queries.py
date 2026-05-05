"""LLM-backed search query generation for the research pipeline."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import string
from dataclasses import dataclass

from king_context.research.config import ResearchConfig
from llm_providers import get_client
from llm_providers.base import ProviderError


log = logging.getLogger(__name__)

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


def _extract_queries(raw_content: str | dict | list) -> list[str]:
    """Parse the model's content or parsed payload into query strings."""
    if isinstance(raw_content, str):
        content = _strip_code_fence(raw_content)
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise QueryGenerationError(
                f"LLM response was not valid JSON: {exc}"
            ) from exc
    else:
        parsed = raw_content

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

    user_prompt = _build_user_prompt(topic, count, previous_results, previous_queries)
    model = config.research_model or config.scraper.enrichment_model or None
    client = get_client(
        "research",
        model_override=model,
        openrouter_api_key_override=config.scraper.openrouter_api_key,
    )

    last_error: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            payload = await client.complete(user_prompt, system=_SYSTEM_PROMPT)
            candidates = _extract_queries(payload)
            return _dedup(candidates, previous_queries, count)
        except ProviderError as exc:
            last_error = exc
            if not exc.transient:
                raise QueryGenerationError(
                    f"{client.name} query generation failed: {exc.message}"
                ) from exc
            log.warning(
                "%s transient error on attempt %d: %s",
                client.name,
                attempt + 1,
                exc.message,
            )
        except QueryGenerationError:
            raise

        if attempt < len(_RETRY_DELAYS):
            await asyncio.sleep(_RETRY_DELAYS[attempt])

    raise QueryGenerationError(
        f"{client.name} query generation failed after {_MAX_ATTEMPTS} attempts: "
        f"{last_error}"
    )
