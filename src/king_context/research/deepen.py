"""Deepening loop that orchestrates iterative query generation and fetching."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from pathlib import Path

import httpx

from king_context.research.config import EffortLevel, ResearchConfig, effort_profile
from king_context.research.fetch import SourceDoc, fetch_for_query as fetch_fn
from king_context.research.queries import (
    QueryGenerationError,
    SourceSummary,
    generate_queries as generate_queries_fn,
)

log = logging.getLogger(__name__)

_HIGHLIGHT_MAX_CHARS = 240


def _build_summaries(docs: list[SourceDoc]) -> list[SourceSummary]:
    summaries: list[SourceSummary] = []
    for doc in docs:
        content = doc.content or ""
        snippet = content[:_HIGHLIGHT_MAX_CHARS].strip()
        summaries.append(SourceSummary(title=doc.title, top_highlight=snippet))
    return summaries


def _dedup_by_url(docs: list[SourceDoc]) -> list[SourceDoc]:
    seen: set[str] = set()
    out: list[SourceDoc] = []
    for doc in docs:
        if doc.url in seen:
            continue
        seen.add(doc.url)
        out.append(doc)
    return out


def _write_iteration_snapshot(
    work_dir: Path, iteration: int, docs: list[SourceDoc]
) -> None:
    path = work_dir / f"iteration_{iteration}.json"
    payload = [asdict(doc) for doc in docs]
    try:
        path.write_text(
            json.dumps(payload, default=str, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        log.warning("Failed to write iteration snapshot %s: %s", path, exc)


async def _fetch_batch(
    queries: list[str],
    iteration: int,
    config: ResearchConfig,
    jina_client: httpx.AsyncClient,
) -> list[SourceDoc]:
    results = await asyncio.gather(
        *[fetch_fn(q, iteration, config, jina_client) for q in queries],
        return_exceptions=True,
    )
    docs: list[SourceDoc] = []
    for r in results:
        if isinstance(r, BaseException):
            log.warning("fetch_for_query failed: %s", r)
            continue
        docs.extend(r)
    return docs


async def run_deepening_loop(
    topic: str,
    effort: EffortLevel,
    config: ResearchConfig,
    work_dir: Path,
) -> list[SourceDoc]:
    """Run the discovery loop: initial queries + optional deepening iterations."""
    work_dir.mkdir(parents=True, exist_ok=True)
    profile = effort_profile(effort, config)

    all_docs: list[SourceDoc] = []
    seen_queries: list[str] = []

    async with httpx.AsyncClient() as jina_client:
        try:
            initial_queries = await generate_queries_fn(
                topic,
                count=profile.initial_queries,
                config=config,
            )
        except QueryGenerationError as exc:
            log.warning("Initial query generation failed: %s", exc)
            return []

        if not initial_queries:
            log.warning("Initial query generation returned no queries")
            return []

        seen_queries.extend(initial_queries)
        iter0_docs = await _fetch_batch(initial_queries, 0, config, jina_client)
        _write_iteration_snapshot(work_dir, 0, iter0_docs)
        all_docs.extend(iter0_docs)

        for i in range(1, profile.iterations + 1):
            summaries = _build_summaries(all_docs)
            try:
                follow_ups = await generate_queries_fn(
                    topic,
                    count=profile.followups_per_iteration,
                    config=config,
                    previous_results=summaries,
                    previous_queries=seen_queries,
                )
            except QueryGenerationError as exc:
                log.warning(
                    "Deepening iteration %d: query generation failed: %s", i, exc
                )
                break

            if not follow_ups:
                log.info(
                    "Deepening iteration %d returned no new queries; stopping", i
                )
                break

            seen_queries.extend(follow_ups)
            iter_docs = await _fetch_batch(follow_ups, i, config, jina_client)
            _write_iteration_snapshot(work_dir, i, iter_docs)
            all_docs.extend(iter_docs)

    return _dedup_by_url(all_docs)
