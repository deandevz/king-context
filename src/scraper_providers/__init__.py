"""Pluggable scraper providers for king-scrape.

Built-in providers are registered via soft import. If their optional
dependency (firecrawl-py, crawl4ai) is not installed, registration
is skipped — selecting that provider will raise ProviderUnavailableError
at resolution time with an install hint.
"""
from __future__ import annotations

from .base import (
    DiscoveryProvider,
    FetchProvider,
    PageContent,
    ProviderUnavailableError,
)
from .registry import (
    get_discovery_provider,
    get_fetch_provider,
    load_entry_point_providers,
    register_discovery_provider,
    register_fetch_provider,
    resolve_provider_name,
)

# Built-in providers — soft import.
try:
    from scraper_providers.firecrawl_provider import (  # pyright: ignore[reportMissingImports]
        register as _register_firecrawl,
    )
    _register_firecrawl()
except ImportError:
    pass

# Third-party plugins via entry_points (after built-ins so built-ins win conflicts).
load_entry_point_providers()

__all__ = [
    "DiscoveryProvider",
    "FetchProvider",
    "PageContent",
    "ProviderUnavailableError",
    "register_discovery_provider",
    "register_fetch_provider",
    "get_discovery_provider",
    "get_fetch_provider",
    "resolve_provider_name",
]
