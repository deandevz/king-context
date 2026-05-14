"""Crawl4AI scraper provider — local Playwright-based backend."""
from __future__ import annotations

import os
import sys
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
        CacheMode,
        CrawlerRunConfig,
    )
    from crawl4ai.deep_crawling import (  # type: ignore[import-not-found]
        BFSDeepCrawlStrategy,
    )
    _CRAWL4AI_AVAILABLE = True
except ImportError:
    AsyncWebCrawler = None  # type: ignore[assignment,misc]
    BrowserConfig = None  # type: ignore[assignment,misc]
    CacheMode = None  # type: ignore[assignment,misc]
    CrawlerRunConfig = None  # type: ignore[assignment,misc]
    BFSDeepCrawlStrategy = None  # type: ignore[assignment,misc]
    _CRAWL4AI_AVAILABLE = False


# Maps the public ``SCRAPE_CACHE_MODE`` env value to the attribute name on
# Crawl4AI's ``CacheMode`` enum. ``"default"`` is handled by an early return
# in ``_resolve_cache_mode`` and is intentionally absent here.
_CACHE_MODE_MAP = {
    "enabled": "ENABLED",
    "bypass": "BYPASS",
    "disabled": "DISABLED",
    "read_only": "READ_ONLY",
    "write_only": "WRITE_ONLY",
}

# One-shot warning state so a typo in SCRAPE_CACHE_MODE does not produce
# hundreds of duplicate stderr lines during a deep crawl. Keyed by the raw
# value so different typos still each warn once. Tests reset this set via
# ``monkeypatch.setattr(...)`` to keep warn-once assertions independent.
_WARNED_CACHE_VALUES: set[str] = set()


def _warn_unknown_cache_mode(raw: str) -> None:
    if raw in _WARNED_CACHE_VALUES:
        return
    _WARNED_CACHE_VALUES.add(raw)
    print(
        f"warning: SCRAPE_CACHE_MODE='{raw}' not recognised; "
        "using crawl4ai default",
        file=sys.stderr,
    )


def _resolve_cache_mode() -> Any:
    """Resolve ``SCRAPE_CACHE_MODE`` env to a ``CacheMode`` value or ``None``.

    ``None`` means "use the library default" — callers omit ``cache_mode``
    from ``CrawlerRunConfig`` rather than passing ``None``, so existing
    behaviour is preserved when the env is unset.

    Two distinct paths return ``None``: (1) the value is missing, ``default``,
    or unrecognised — emits a stderr warning the first time per raw value;
    (2) the ``crawl4ai`` library is not installed — silent because the
    caller's ``_ensure_available`` will surface a clearer error before any
    real fetch happens.
    """
    raw = (os.environ.get("SCRAPE_CACHE_MODE") or "").strip().lower()
    if not raw or raw == "default":
        return None
    if CacheMode is None:
        # Library missing: stay silent. The caller path won't reach a real
        # crawl4ai call (the provider's _ensure_available raises a clearer
        # ProviderUnavailableError), so a "not recognised" warning here would
        # only confuse a user whose actual problem is a missing dependency.
        return None
    mapped = _CACHE_MODE_MAP.get(raw)
    if mapped is None:
        _warn_unknown_cache_mode(raw)
        return None
    try:
        return getattr(CacheMode, mapped)
    except AttributeError:
        # Future crawl4ai version may rename the enum value. Fall back to
        # default behaviour with a one-shot warning so the run continues.
        _warn_unknown_cache_mode(raw)
        return None


_INSTALL_HINT = (
    "crawl4ai not installed in the active Python environment. "
    "If you installed via npx @king-context/cli, run "
    "'npx @king-context/cli update' to refresh the venv. "
    "If you cloned the repo for development, run "
    "'pip install -e \".[crawl4ai]\" && crawl4ai-setup'."
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
        cache_kwargs: dict[str, Any] = {}
        cache_mode = _resolve_cache_mode()
        if cache_mode is not None:
            cache_kwargs["cache_mode"] = cache_mode
        run_config = CrawlerRunConfig(  # type: ignore[misc]
            deep_crawl_strategy=BFSDeepCrawlStrategy(  # type: ignore[misc]
                max_depth=2, include_external=False
            ),
            **cache_kwargs,
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
        cache_mode = _resolve_cache_mode()
        run_config = (
            CrawlerRunConfig(cache_mode=cache_mode)  # type: ignore[misc]
            if cache_mode is not None
            else None
        )
        try:
            async with AsyncWebCrawler(  # type: ignore[misc]
                config=BrowserConfig(headless=True),  # type: ignore[misc]
            ) as crawler:
                if run_config is not None:
                    result = await crawler.arun(url=url, config=run_config)
                else:
                    # Preserve the pre-fix call shape when no cache override is
                    # set, so existing behaviour and any provider-side defaults
                    # remain unchanged for users who have not opted in.
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
