"""Crawl4AI scraper provider — local Playwright-based backend."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from .base import (
    PageContent,
    ProviderUnavailableError,
)
from .registry import register_discovery_provider, register_fetch_provider

try:
    from crawl4ai import (  # type: ignore[import-not-found]
        AsyncWebCrawler,
        BrowserConfig,
        CrawlerRunConfig,
    )
    from crawl4ai.deep_crawling import (  # type: ignore[import-not-found]
        BFSDeepCrawlStrategy,
    )
    _CRAWL4AI_AVAILABLE = True
except ImportError:
    AsyncWebCrawler = None  # type: ignore[assignment,misc]
    BrowserConfig = None  # type: ignore[assignment,misc]
    CrawlerRunConfig = None  # type: ignore[assignment,misc]
    BFSDeepCrawlStrategy = None  # type: ignore[assignment,misc]
    _CRAWL4AI_AVAILABLE = False


_INSTALL_HINT = (
    "crawl4ai not installed. Run: "
    "pip install king-context[crawl4ai] && crawl4ai-setup"
)
_SETUP_HINT = (
    "crawl4ai installed but Playwright browser (chromium) missing. "
    "Run: crawl4ai-setup"
)
_BROWSER_MISSING_MARKERS = ("executable doesn't exist", "playwright install")


def _ensure_available() -> None:
    if not _CRAWL4AI_AVAILABLE:
        raise ProviderUnavailableError("crawl4ai", _INSTALL_HINT)


def _ensure_browser_present() -> None:
    """Heuristic: confirm Playwright is importable. The real check happens at
    arun() time — Playwright raises a clear "executable doesn't exist" error
    if the browser binary is missing, which we translate in _is_browser_missing.
    """
    from importlib.util import find_spec

    if find_spec("playwright") is None:
        raise ProviderUnavailableError("crawl4ai", _SETUP_HINT)


def _is_browser_missing(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _BROWSER_MISSING_MARKERS)


def _extract_markdown(result: Any) -> str:
    """Crawl4AI exposes `markdown` as a property returning StringCompatibleMarkdown
    (a str subclass) or None. Coerce to plain str."""
    md = getattr(result, "markdown", None)
    if md is None:
        return ""
    return str(md)


def _extract_title(result: Any) -> str | None:
    """Title lives on result.metadata['title'] in Crawl4AI's CrawlResult shape.
    metadata may be None or absent."""
    metadata = getattr(result, "metadata", None)
    if metadata is None:
        return None
    if isinstance(metadata, dict):
        title = metadata.get("title")
        return title or None
    title = getattr(metadata, "title", None)
    return title or None


def _iter_results(results: Any) -> Iterable[Any]:
    """Deep-crawl batch mode returns a list[CrawlResult]; single fetch returns
    a CrawlResultContainer (iterable). Normalize both to an iterable."""
    if results is None:
        return []
    if isinstance(results, list):
        return results
    if hasattr(results, "__iter__"):
        return results
    return [results]


class Crawl4AIDiscoveryProvider:
    name = "crawl4ai"

    async def discover_urls(self, base_url: str) -> list[str]:
        _ensure_available()
        _ensure_browser_present()
        run_config = CrawlerRunConfig(  # type: ignore[misc]
            deep_crawl_strategy=BFSDeepCrawlStrategy(  # type: ignore[misc]
                max_depth=2, include_external=False
            ),
        )
        try:
            async with AsyncWebCrawler(  # type: ignore[misc]
                config=BrowserConfig(headless=True),  # type: ignore[misc]
            ) as crawler:
                results = await crawler.arun(url=base_url, config=run_config)
        except Exception as exc:
            if _is_browser_missing(exc):
                raise ProviderUnavailableError("crawl4ai", _SETUP_HINT) from exc
            raise
        urls: list[str] = []
        for r in _iter_results(results):
            u = getattr(r, "url", None)
            if u:
                urls.append(u)
        return urls


class Crawl4AIFetchProvider:
    name = "crawl4ai"

    async def fetch_one(self, url: str) -> PageContent:
        _ensure_available()
        _ensure_browser_present()
        try:
            async with AsyncWebCrawler(  # type: ignore[misc]
                config=BrowserConfig(headless=True),  # type: ignore[misc]
            ) as crawler:
                result = await crawler.arun(url=url)
        except Exception as exc:
            if _is_browser_missing(exc):
                raise ProviderUnavailableError("crawl4ai", _SETUP_HINT) from exc
            raise
        return PageContent(
            url=url,
            markdown=_extract_markdown(result),
            title=_extract_title(result),
            fetched_at=datetime.now(timezone.utc),
        )


def register() -> None:
    """Entry-point hook. Idempotent (registry is first-write-wins)."""
    register_discovery_provider("crawl4ai", lambda: Crawl4AIDiscoveryProvider())
    register_fetch_provider("crawl4ai", lambda: Crawl4AIFetchProvider())
