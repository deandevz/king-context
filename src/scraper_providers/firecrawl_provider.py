"""Firecrawl scraper provider — wraps the firecrawl-py SDK."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

from .base import (
    PageContent,
    ProviderUnavailableError,
)
from .registry import register_discovery_provider, register_fetch_provider

try:
    from firecrawl import FirecrawlApp  # type: ignore[import-not-found]
    _FIRECRAWL_AVAILABLE = True
except ImportError:
    FirecrawlApp = None  # type: ignore[assignment,misc]
    _FIRECRAWL_AVAILABLE = False


_INSTALL_HINT = (
    "firecrawl-py not installed in the active Python environment. "
    "If you installed via npx @king-context/cli, run "
    "'npx @king-context/cli update' to refresh the venv. "
    "If you cloned the repo for development, run "
    "'pip install -e \".[firecrawl]\"' (or '.[all]'). "
    "Set FIRECRAWL_API_KEY before running."
)


def _build_app() -> Any:
    if not _FIRECRAWL_AVAILABLE:
        raise ProviderUnavailableError("firecrawl", _INSTALL_HINT)
    api_key = os.getenv("FIRECRAWL_API_KEY")
    return FirecrawlApp(api_key=api_key)  # type: ignore[misc]


def _extract_links(raw: Any) -> list[str]:
    """Mirror scraper/discover.py: handle SDK object, list, or dict shapes."""
    if hasattr(raw, "links"):
        links = raw.links
    elif isinstance(raw, list):
        links = raw
    elif isinstance(raw, dict):
        links = raw.get("links", [])
    else:
        links = []
    return [lnk.url if hasattr(lnk, "url") else str(lnk) for lnk in (links or [])]


def _extract_markdown(raw: Any) -> str:
    """Mirror scraper/fetch.py: handle SDK object or dict shapes."""
    if hasattr(raw, "markdown"):
        return raw.markdown or ""
    if isinstance(raw, dict):
        return raw.get("markdown", "") or ""
    return ""


def _extract_title(raw: Any) -> str | None:
    """Best-effort title extraction from SDK metadata (object or dict)."""
    metadata = getattr(raw, "metadata", None)
    if metadata is None and isinstance(raw, dict):
        metadata = raw.get("metadata")
    if metadata is None:
        return None
    if hasattr(metadata, "title"):
        return metadata.title or None
    if isinstance(metadata, dict):
        title = metadata.get("title")
        return title or None
    return None


class FirecrawlDiscoveryProvider:
    name = "firecrawl"

    async def discover_urls(self, base_url: str) -> list[str]:
        app = _build_app()
        raw = await asyncio.to_thread(app.map, base_url)
        return _extract_links(raw)


class FirecrawlFetchProvider:
    name = "firecrawl"

    async def fetch_one(self, url: str) -> PageContent:
        app = _build_app()
        raw = await asyncio.to_thread(app.scrape, url, formats=["markdown"])
        return PageContent(
            url=url,
            markdown=_extract_markdown(raw),
            title=_extract_title(raw),
            fetched_at=datetime.now(timezone.utc),
        )


def register() -> None:
    """Entry-point hook. Idempotent (registry is first-write-wins)."""
    register_discovery_provider("firecrawl", lambda: FirecrawlDiscoveryProvider())
    register_fetch_provider("firecrawl", lambda: FirecrawlFetchProvider())
