"""Tests for scraper_providers.firecrawl_provider — SDK wrapping + soft import."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from scraper_providers import (
    DiscoveryProvider,
    FetchProvider,
    PageContent,
    ProviderUnavailableError,
    get_discovery_provider,
    get_fetch_provider,
)
from scraper_providers import firecrawl_provider
from scraper_providers.firecrawl_provider import (
    FirecrawlDiscoveryProvider,
    FirecrawlFetchProvider,
)


def _patch_app(monkeypatch, mock_app: MagicMock) -> None:
    monkeypatch.setattr(
        "scraper_providers.firecrawl_provider.FirecrawlApp",
        lambda **kw: mock_app,
    )
    monkeypatch.setattr(
        "scraper_providers.firecrawl_provider._FIRECRAWL_AVAILABLE", True
    )


async def test_discover_returns_url_list(monkeypatch):
    fake_app = MagicMock()
    fake_app.map.return_value = {"links": ["https://a", "https://b"]}
    _patch_app(monkeypatch, fake_app)

    provider = FirecrawlDiscoveryProvider()
    urls = await provider.discover_urls("https://x")

    assert urls == ["https://a", "https://b"]
    fake_app.map.assert_called_once_with("https://x")


async def test_discover_empty_links(monkeypatch):
    fake_app = MagicMock()
    fake_app.map.return_value = {"links": []}
    _patch_app(monkeypatch, fake_app)

    provider = FirecrawlDiscoveryProvider()
    urls = await provider.discover_urls("https://x")

    assert urls == []


async def test_discover_handles_object_response(monkeypatch):
    """SDK v2.x may return an object with .links instead of a dict."""
    class _LinkObj:
        def __init__(self, url: str):
            self.url = url

    class _MapResp:
        links = [_LinkObj("https://a"), _LinkObj("https://b")]

    fake_app = MagicMock()
    fake_app.map.return_value = _MapResp()
    _patch_app(monkeypatch, fake_app)

    provider = FirecrawlDiscoveryProvider()
    urls = await provider.discover_urls("https://x")

    assert urls == ["https://a", "https://b"]


async def test_discover_handles_plain_list_response(monkeypatch):
    """Some SDK shapes return a bare list of URL strings."""
    fake_app = MagicMock()
    fake_app.map.return_value = ["https://a", "https://b"]
    _patch_app(monkeypatch, fake_app)

    provider = FirecrawlDiscoveryProvider()
    urls = await provider.discover_urls("https://x")

    assert urls == ["https://a", "https://b"]


async def test_fetch_returns_page_content(monkeypatch):
    fake_app = MagicMock()
    fake_app.scrape.return_value = {
        "markdown": "# Hi",
        "metadata": {"title": "T"},
    }
    _patch_app(monkeypatch, fake_app)

    provider = FirecrawlFetchProvider()
    page = await provider.fetch_one("https://u")

    assert isinstance(page, PageContent)
    assert page.url == "https://u"
    assert page.markdown == "# Hi"
    assert page.title == "T"
    assert isinstance(page.fetched_at, datetime)
    assert page.fetched_at.tzinfo == timezone.utc
    fake_app.scrape.assert_called_once_with("https://u", formats=["markdown"])


async def test_fetch_handles_missing_title(monkeypatch):
    fake_app = MagicMock()
    fake_app.scrape.return_value = {"markdown": "x"}
    _patch_app(monkeypatch, fake_app)

    provider = FirecrawlFetchProvider()
    page = await provider.fetch_one("https://u")

    assert page.title is None
    assert page.markdown == "x"


async def test_fetch_handles_empty_markdown(monkeypatch):
    fake_app = MagicMock()
    fake_app.scrape.return_value = {}
    _patch_app(monkeypatch, fake_app)

    provider = FirecrawlFetchProvider()
    page = await provider.fetch_one("https://u")

    assert page.markdown == ""
    assert page.title is None


def test_unavailable_when_not_installed(monkeypatch):
    monkeypatch.setattr(
        "scraper_providers.firecrawl_provider._FIRECRAWL_AVAILABLE", False
    )

    with pytest.raises(ProviderUnavailableError) as excinfo:
        firecrawl_provider._build_app()

    assert excinfo.value.provider == "firecrawl"
    assert "pip install" in excinfo.value.hint


def test_register_makes_provider_resolvable():
    firecrawl_provider.register()

    discovery = get_discovery_provider("firecrawl")
    fetch = get_fetch_provider("firecrawl")

    assert isinstance(discovery, FirecrawlDiscoveryProvider)
    assert isinstance(fetch, FirecrawlFetchProvider)
    assert discovery.name == "firecrawl"
    assert fetch.name == "firecrawl"


def test_protocol_compliance():
    assert isinstance(FirecrawlDiscoveryProvider(), DiscoveryProvider)
    assert isinstance(FirecrawlFetchProvider(), FetchProvider)


def test_init_skips_when_firecrawl_missing(monkeypatch):
    """Re-importing the package with firecrawl unavailable must not raise."""
    import importlib
    import sys

    real_firecrawl = sys.modules.pop("firecrawl", None)
    monkeypatch.setitem(sys.modules, "firecrawl", None)

    sys.modules.pop("scraper_providers", None)
    sys.modules.pop("scraper_providers.firecrawl_provider", None)
    try:
        pkg = importlib.import_module("scraper_providers")
        assert hasattr(pkg, "get_fetch_provider")
    finally:
        sys.modules.pop("scraper_providers", None)
        sys.modules.pop("scraper_providers.firecrawl_provider", None)
        if real_firecrawl is not None:
            sys.modules["firecrawl"] = real_firecrawl
        else:
            sys.modules.pop("firecrawl", None)
        importlib.import_module("scraper_providers")
