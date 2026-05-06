"""Common scraper provider interfaces."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class PageContent:
    url: str
    markdown: str
    fetched_at: datetime
    title: str | None = None


class ProviderUnavailableError(RuntimeError):
    """Raised when a provider is selected but its dependency is not installed
    or its setup step (e.g. crawl4ai-setup) has not been run.

    Carries an actionable install/setup hint, not a raw ImportError traceback.
    """

    def __init__(self, provider: str, hint: str):
        self.provider = provider
        self.hint = hint
        super().__init__(f"Provider '{provider}' unavailable: {hint}")


@runtime_checkable
class DiscoveryProvider(Protocol):
    name: str

    async def discover_urls(self, base_url: str) -> list[str]: ...


@runtime_checkable
class FetchProvider(Protocol):
    name: str

    async def fetch_one(self, url: str) -> PageContent: ...
