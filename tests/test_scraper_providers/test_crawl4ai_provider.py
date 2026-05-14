"""Tests for scraper_providers.crawl4ai_provider — soft import + Playwright translation."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from scraper_providers import (
    DiscoveryProvider,
    FetchProvider,
    PageContent,
    ProviderUnavailableError,
    get_discovery_provider,
    get_fetch_provider,
)
from scraper_providers import crawl4ai_provider
from scraper_providers.crawl4ai_provider import (
    Crawl4AIDiscoveryProvider,
    Crawl4AIFetchProvider,
)


class _FakeResult:
    def __init__(self, url: str, markdown: str | None = "", metadata: dict | None = None):
        self.url = url
        self.markdown = markdown
        self.metadata = metadata


def _make_crawler_mock(arun_return):
    """Build a MagicMock that supports async-context-manager and async arun()."""
    crawler = MagicMock()
    crawler.__aenter__ = AsyncMock(return_value=crawler)
    crawler.__aexit__ = AsyncMock(return_value=None)
    if isinstance(arun_return, Exception):
        crawler.arun = AsyncMock(side_effect=arun_return)
    else:
        crawler.arun = AsyncMock(return_value=arun_return)
    return crawler


def _patch_crawl4ai(monkeypatch, crawler_mock) -> None:
    """Force _CRAWL4AI_AVAILABLE=True and stub AsyncWebCrawler factory + configs."""
    monkeypatch.setattr(
        "scraper_providers.crawl4ai_provider._CRAWL4AI_AVAILABLE", True
    )
    monkeypatch.setattr(
        "scraper_providers.crawl4ai_provider.AsyncWebCrawler",
        lambda **kw: crawler_mock,
    )
    monkeypatch.setattr(
        "scraper_providers.crawl4ai_provider.BrowserConfig",
        lambda **kw: object(),
    )
    monkeypatch.setattr(
        "scraper_providers.crawl4ai_provider.CrawlerRunConfig",
        lambda **kw: object(),
    )
    monkeypatch.setattr(
        "scraper_providers.crawl4ai_provider.BFSDeepCrawlStrategy",
        lambda **kw: object(),
    )
    # Bypass Playwright presence check
    monkeypatch.setattr(
        "scraper_providers.crawl4ai_provider._ensure_browser_present",
        lambda: None,
    )


async def test_fetch_returns_page_content(monkeypatch):
    result = _FakeResult(
        url="https://u",
        markdown="# Hi",
        metadata={"title": "Title"},
    )
    _patch_crawl4ai(monkeypatch, _make_crawler_mock(result))

    provider = Crawl4AIFetchProvider()
    page = await provider.fetch_one("https://u")

    assert isinstance(page, PageContent)
    assert page.url == "https://u"
    assert page.markdown == "# Hi"
    assert page.title == "Title"
    assert isinstance(page.fetched_at, datetime)
    assert page.fetched_at.tzinfo == timezone.utc


async def test_fetch_handles_missing_title(monkeypatch):
    result = _FakeResult(url="https://u", markdown="x", metadata=None)
    _patch_crawl4ai(monkeypatch, _make_crawler_mock(result))

    provider = Crawl4AIFetchProvider()
    page = await provider.fetch_one("https://u")

    assert page.title is None
    assert page.markdown == "x"


async def test_fetch_handles_missing_markdown(monkeypatch):
    result = _FakeResult(url="https://u", markdown=None)
    _patch_crawl4ai(monkeypatch, _make_crawler_mock(result))

    provider = Crawl4AIFetchProvider()
    page = await provider.fetch_one("https://u")

    assert page.markdown == ""


async def test_fetch_handles_empty_string_markdown(monkeypatch):
    result = _FakeResult(url="https://u", markdown="")
    _patch_crawl4ai(monkeypatch, _make_crawler_mock(result))

    provider = Crawl4AIFetchProvider()
    page = await provider.fetch_one("https://u")

    assert page.markdown == ""


async def test_discover_returns_urls_from_deep_crawl(monkeypatch):
    results = [
        _FakeResult(url="https://a"),
        _FakeResult(url="https://b"),
        _FakeResult(url="https://c"),
    ]
    _patch_crawl4ai(monkeypatch, _make_crawler_mock(results))

    provider = Crawl4AIDiscoveryProvider()
    urls = await provider.discover_urls("https://a")

    assert urls == ["https://a", "https://b", "https://c"]


async def test_discover_skips_results_without_url(monkeypatch):
    class _NoUrl:
        url = None

    results = [_FakeResult(url="https://a"), _NoUrl(), _FakeResult(url="https://b")]
    _patch_crawl4ai(monkeypatch, _make_crawler_mock(results))

    provider = Crawl4AIDiscoveryProvider()
    urls = await provider.discover_urls("https://a")

    assert urls == ["https://a", "https://b"]


def test_unavailable_when_crawl4ai_not_installed(monkeypatch):
    monkeypatch.setattr(
        "scraper_providers.crawl4ai_provider._CRAWL4AI_AVAILABLE", False
    )

    with pytest.raises(ProviderUnavailableError) as excinfo:
        crawl4ai_provider._ensure_available()

    assert excinfo.value.provider == "crawl4ai"
    assert "pip install" in excinfo.value.hint
    assert "crawl4ai-setup" in excinfo.value.hint


async def test_unavailable_propagates_through_fetch(monkeypatch):
    monkeypatch.setattr(
        "scraper_providers.crawl4ai_provider._CRAWL4AI_AVAILABLE", False
    )

    provider = Crawl4AIFetchProvider()
    with pytest.raises(ProviderUnavailableError) as excinfo:
        await provider.fetch_one("https://u")

    assert excinfo.value.provider == "crawl4ai"
    assert "pip install" in excinfo.value.hint


async def test_browser_missing_translates_to_provider_error(monkeypatch):
    crawler = _make_crawler_mock(
        Exception("BrowserType.launch: Executable doesn't exist at /path")
    )
    _patch_crawl4ai(monkeypatch, crawler)

    provider = Crawl4AIFetchProvider()
    with pytest.raises(ProviderUnavailableError) as excinfo:
        await provider.fetch_one("https://u")

    assert excinfo.value.provider == "crawl4ai"
    assert "crawl4ai-setup" in excinfo.value.hint


async def test_browser_missing_translates_in_discover(monkeypatch):
    crawler = _make_crawler_mock(
        Exception("Please run: playwright install chromium")
    )
    _patch_crawl4ai(monkeypatch, crawler)

    provider = Crawl4AIDiscoveryProvider()
    with pytest.raises(ProviderUnavailableError) as excinfo:
        await provider.discover_urls("https://u")

    assert excinfo.value.provider == "crawl4ai"
    assert "crawl4ai-setup" in excinfo.value.hint


async def test_other_exceptions_bubble_up(monkeypatch):
    crawler = _make_crawler_mock(RuntimeError("network unreachable"))
    _patch_crawl4ai(monkeypatch, crawler)

    provider = Crawl4AIFetchProvider()
    with pytest.raises(RuntimeError, match="network unreachable"):
        await provider.fetch_one("https://u")


def test_register_makes_provider_resolvable():
    crawl4ai_provider.register()

    discovery = get_discovery_provider("crawl4ai")
    fetch = get_fetch_provider("crawl4ai")

    assert isinstance(discovery, Crawl4AIDiscoveryProvider)
    assert isinstance(fetch, Crawl4AIFetchProvider)
    assert discovery.name == "crawl4ai"
    assert fetch.name == "crawl4ai"


def test_protocol_compliance():
    assert isinstance(Crawl4AIDiscoveryProvider(), DiscoveryProvider)
    assert isinstance(Crawl4AIFetchProvider(), FetchProvider)


def test_init_skips_when_crawl4ai_missing(monkeypatch):
    """Re-importing the package with crawl4ai unavailable must not raise.

    Saves the original scraper_providers.* module instances and restores them
    after the reload. Other test files hold references to these modules at
    import time; if we let a fresh reload replace them, monkeypatch.setattr in
    those tests would patch the new instances while the test calls the old.
    """
    import importlib
    import sys

    real_crawl4ai = sys.modules.pop("crawl4ai", None)
    monkeypatch.setitem(sys.modules, "crawl4ai", None)

    orig_modules = {
        k: v for k, v in sys.modules.items() if k.startswith("scraper_providers")
    }
    for k in orig_modules:
        sys.modules.pop(k, None)
    try:
        pkg = importlib.import_module("scraper_providers")
        assert hasattr(pkg, "get_fetch_provider")
    finally:
        for k in [k for k in list(sys.modules) if k.startswith("scraper_providers")]:
            sys.modules.pop(k, None)
        sys.modules.update(orig_modules)
        if real_crawl4ai is not None:
            sys.modules["crawl4ai"] = real_crawl4ai
        else:
            sys.modules.pop("crawl4ai", None)


def test_browser_missing_when_playwright_absent(monkeypatch):
    """If crawl4ai is importable but Playwright isn't, _ensure_browser_present
    raises ProviderUnavailableError with the setup hint."""
    monkeypatch.setattr(
        "scraper_providers.crawl4ai_provider._CRAWL4AI_AVAILABLE", True
    )

    def _fake_find_spec(name):
        if name == "playwright":
            return None
        from importlib.util import find_spec as _real
        return _real(name)

    monkeypatch.setattr(
        "importlib.util.find_spec", _fake_find_spec
    )

    with pytest.raises(ProviderUnavailableError) as excinfo:
        crawl4ai_provider._ensure_browser_present()

    assert excinfo.value.provider == "crawl4ai"
    assert "crawl4ai-setup" in excinfo.value.hint


# --- SCRAPE_CACHE_MODE handling (#50) ---------------------------------------


class _StubCacheMode:
    """Stand-in for crawl4ai.CacheMode so tests don't depend on the lib."""
    ENABLED = "enabled-sentinel"
    BYPASS = "bypass-sentinel"
    DISABLED = "disabled-sentinel"
    READ_ONLY = "read-only-sentinel"
    WRITE_ONLY = "write-only-sentinel"


@pytest.fixture
def cache_mode(monkeypatch):
    """Make ``CacheMode`` available to ``_resolve_cache_mode`` even when
    ``crawl4ai`` is not actually installed in the test environment."""
    monkeypatch.setattr(
        "scraper_providers.crawl4ai_provider.CacheMode", _StubCacheMode
    )
    return _StubCacheMode


def test_resolve_cache_mode_unset_returns_none(monkeypatch, cache_mode):
    monkeypatch.delenv("SCRAPE_CACHE_MODE", raising=False)
    assert crawl4ai_provider._resolve_cache_mode() is None


def test_resolve_cache_mode_default_returns_none(monkeypatch, cache_mode):
    monkeypatch.setenv("SCRAPE_CACHE_MODE", "default")
    assert crawl4ai_provider._resolve_cache_mode() is None


def test_resolve_cache_mode_bypass(monkeypatch, cache_mode):
    monkeypatch.setenv("SCRAPE_CACHE_MODE", "bypass")
    assert crawl4ai_provider._resolve_cache_mode() == cache_mode.BYPASS


def test_resolve_cache_mode_bypass_case_insensitive(monkeypatch, cache_mode):
    monkeypatch.setenv("SCRAPE_CACHE_MODE", "BYPASS  ")
    assert crawl4ai_provider._resolve_cache_mode() == cache_mode.BYPASS


def test_resolve_cache_mode_disabled(monkeypatch, cache_mode):
    monkeypatch.setenv("SCRAPE_CACHE_MODE", "disabled")
    assert crawl4ai_provider._resolve_cache_mode() == cache_mode.DISABLED


def test_resolve_cache_mode_read_only(monkeypatch, cache_mode):
    monkeypatch.setenv("SCRAPE_CACHE_MODE", "read_only")
    assert crawl4ai_provider._resolve_cache_mode() == cache_mode.READ_ONLY


def test_resolve_cache_mode_write_only(monkeypatch, cache_mode):
    monkeypatch.setenv("SCRAPE_CACHE_MODE", "write_only")
    assert crawl4ai_provider._resolve_cache_mode() == cache_mode.WRITE_ONLY


def test_resolve_cache_mode_unknown_value_warns(monkeypatch, cache_mode, capsys):
    # Reset the warn-once cache so this test gets a fresh first emission.
    monkeypatch.setattr(
        "scraper_providers.crawl4ai_provider._WARNED_CACHE_VALUES", set()
    )
    monkeypatch.setenv("SCRAPE_CACHE_MODE", "totally-invalid-once")
    assert crawl4ai_provider._resolve_cache_mode() is None
    err = capsys.readouterr().err
    assert "totally-invalid-once" in err
    assert "not recognised" in err


def test_resolve_cache_mode_when_crawl4ai_not_installed_is_silent(monkeypatch, capsys):
    """Library missing must NOT print 'not recognised'; the caller's
    ``_ensure_available`` surfaces the real error path."""
    monkeypatch.setattr(
        "scraper_providers.crawl4ai_provider.CacheMode", None
    )
    monkeypatch.setenv("SCRAPE_CACHE_MODE", "bypass")
    assert crawl4ai_provider._resolve_cache_mode() is None
    err = capsys.readouterr().err
    assert "not recognised" not in err


def test_resolve_cache_mode_unknown_value_warns_only_once(
    monkeypatch, cache_mode, capsys
):
    """Repeated calls with the same bad value emit one stderr line, not N."""
    # Reset module state since the warn-once cache persists across tests.
    monkeypatch.setattr(
        "scraper_providers.crawl4ai_provider._WARNED_CACHE_VALUES", set()
    )
    monkeypatch.setenv("SCRAPE_CACHE_MODE", "totally-invalid")
    crawl4ai_provider._resolve_cache_mode()
    crawl4ai_provider._resolve_cache_mode()
    crawl4ai_provider._resolve_cache_mode()
    err = capsys.readouterr().err
    assert err.count("totally-invalid") == 1


def test_resolve_cache_mode_returns_none_when_enum_attribute_missing(
    monkeypatch, capsys
):
    """If a future crawl4ai release renames an enum value, fall back gracefully."""
    monkeypatch.setattr(
        "scraper_providers.crawl4ai_provider._WARNED_CACHE_VALUES", set()
    )

    class _PartialCacheMode:
        ENABLED = "enabled-sentinel"
        # BYPASS deliberately absent.

    monkeypatch.setattr(
        "scraper_providers.crawl4ai_provider.CacheMode", _PartialCacheMode
    )
    monkeypatch.setenv("SCRAPE_CACHE_MODE", "bypass")
    assert crawl4ai_provider._resolve_cache_mode() is None
    err = capsys.readouterr().err
    assert "bypass" in err


def test_discover_passes_cache_mode_to_run_config(monkeypatch, cache_mode):
    """SCRAPE_CACHE_MODE=bypass propagates into the deep-crawl run config."""
    captured: dict = {}

    def _spy_run_config(**kwargs):
        captured.update(kwargs)
        return object()

    crawler = _make_crawler_mock(arun_return=[_FakeResult("https://x/a")])
    _patch_crawl4ai(monkeypatch, crawler)
    monkeypatch.setattr(
        "scraper_providers.crawl4ai_provider.CrawlerRunConfig", _spy_run_config
    )
    monkeypatch.setenv("SCRAPE_CACHE_MODE", "bypass")

    import asyncio
    asyncio.run(Crawl4AIDiscoveryProvider().discover_urls("https://x"))

    assert captured.get("cache_mode") == cache_mode.BYPASS


def test_discover_omits_cache_mode_when_env_unset(monkeypatch, cache_mode):
    captured: dict = {}

    def _spy_run_config(**kwargs):
        captured.update(kwargs)
        return object()

    crawler = _make_crawler_mock(arun_return=[_FakeResult("https://x/a")])
    _patch_crawl4ai(monkeypatch, crawler)
    monkeypatch.setattr(
        "scraper_providers.crawl4ai_provider.CrawlerRunConfig", _spy_run_config
    )
    monkeypatch.delenv("SCRAPE_CACHE_MODE", raising=False)

    import asyncio
    asyncio.run(Crawl4AIDiscoveryProvider().discover_urls("https://x"))

    assert "cache_mode" not in captured


def test_fetch_one_passes_cache_mode_when_env_set(monkeypatch, cache_mode):
    """SCRAPE_CACHE_MODE=bypass causes fetch_one to pass a CrawlerRunConfig."""
    crawler = _make_crawler_mock(
        arun_return=_FakeResult("https://x/a", markdown="hi")
    )
    _patch_crawl4ai(monkeypatch, crawler)

    captured: dict = {}

    def _spy_run_config(**kwargs):
        captured.update(kwargs)
        return "run-config-sentinel"

    monkeypatch.setattr(
        "scraper_providers.crawl4ai_provider.CrawlerRunConfig", _spy_run_config
    )
    monkeypatch.setenv("SCRAPE_CACHE_MODE", "bypass")

    import asyncio
    page = asyncio.run(Crawl4AIFetchProvider().fetch_one("https://x/a"))

    assert page.markdown == "hi"
    assert captured.get("cache_mode") == cache_mode.BYPASS
    # arun was called WITH a config object.
    crawler.arun.assert_called_once()
    _, kwargs = crawler.arun.call_args
    assert kwargs.get("config") == "run-config-sentinel"


def test_fetch_one_omits_config_when_env_unset(monkeypatch, cache_mode):
    """No env override means fetch_one preserves the original
    ``crawler.arun(url=url)`` call shape with no config kwarg."""
    crawler = _make_crawler_mock(
        arun_return=_FakeResult("https://x/a", markdown="hi")
    )
    _patch_crawl4ai(monkeypatch, crawler)
    monkeypatch.delenv("SCRAPE_CACHE_MODE", raising=False)

    import asyncio
    page = asyncio.run(Crawl4AIFetchProvider().fetch_one("https://x/a"))

    assert page.markdown == "hi"
    crawler.arun.assert_called_once()
    _, kwargs = crawler.arun.call_args
    assert "config" not in kwargs
