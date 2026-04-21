from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

import httpx

from king_context.research.config import ResearchConfig
from king_context.research.exa import ExaResult, search as exa_search
from king_context.research.jina import (
    JinaDegradedError,
    JinaPermanentError,
    JinaTransientError,
    fetch as jina_fetch,
)

log = logging.getLogger(__name__)

MIN_CONTENT_CHARS = 600


@dataclass
class SourceDoc:
    url: str
    title: str
    content: str
    author: str | None
    published_date: str | None
    domain: str
    query: str
    discovery_iteration: int
    score: float | None
    fetch_path: Literal["exa", "jina"]


def _build_exa_doc(result: ExaResult, query: str, iteration: int) -> SourceDoc:
    return SourceDoc(
        url=result.url,
        title=result.title,
        content=result.text,
        author=result.author,
        published_date=result.published_date,
        domain=urlparse(result.url).netloc,
        query=query,
        discovery_iteration=iteration,
        score=result.score,
        fetch_path="exa",
    )


async def _jina_fallback(
    exa_result: ExaResult,
    query: str,
    iteration: int,
    semaphore: asyncio.Semaphore,
    jina_client: httpx.AsyncClient,
    config: ResearchConfig,
) -> SourceDoc | None:
    async with semaphore:
        try:
            result = await jina_fetch(
                exa_result.url, config.jina_api_key, jina_client
            )
        except (JinaTransientError, JinaPermanentError, JinaDegradedError) as exc:
            log.warning(
                "Jina fallback failed for %s: %s", exa_result.url, exc
            )
            return None
        except Exception as exc:
            log.warning(
                "Unexpected Jina fallback failure for %s: %s",
                exa_result.url,
                exc,
            )
            return None
        return SourceDoc(
            url=exa_result.url,
            title=result.title or exa_result.title,
            content=result.content,
            author=exa_result.author,
            published_date=exa_result.published_date,
            domain=urlparse(exa_result.url).netloc,
            query=query,
            discovery_iteration=iteration,
            score=exa_result.score,
            fetch_path="jina",
        )


async def fetch_for_query(
    query: str,
    iteration: int,
    config: ResearchConfig,
    jina_client: httpx.AsyncClient,
) -> list[SourceDoc]:
    """Run Exa search, keep sufficient results directly, fallback short ones to Jina."""
    exa_results = await exa_search(query, config)

    direct_docs: list[SourceDoc] = []
    short_results: list[ExaResult] = []

    for result in exa_results:
        if len(result.text) >= MIN_CONTENT_CHARS:
            direct_docs.append(_build_exa_doc(result, query, iteration))
        else:
            short_results.append(result)

    if not short_results:
        return direct_docs

    semaphore = asyncio.Semaphore(config.scraper.concurrency)
    tasks = [
        _jina_fallback(result, query, iteration, semaphore, jina_client, config)
        for result in short_results
    ]
    jina_docs = await asyncio.gather(*tasks, return_exceptions=True)
    fallback_docs: list[SourceDoc] = []
    for result, doc in zip(short_results, jina_docs):
        if isinstance(doc, Exception):
            log.warning(
                "Unhandled Jina fallback failure for %s: %s",
                result.url,
                doc,
            )
            continue
        if doc is not None:
            fallback_docs.append(doc)

    return direct_docs + fallback_docs
