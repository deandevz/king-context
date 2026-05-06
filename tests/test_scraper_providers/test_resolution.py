"""Tests for scraper_providers.registry.resolve_provider_name — env precedence."""
from __future__ import annotations

from scraper_providers import resolve_provider_name


def _clear_env(monkeypatch):
    monkeypatch.delenv("SCRAPE_PROVIDER", raising=False)
    monkeypatch.delenv("SCRAPE_DISCOVER_PROVIDER", raising=False)
    monkeypatch.delenv("SCRAPE_FETCH_PROVIDER", raising=False)


def test_default_is_firecrawl(monkeypatch):
    _clear_env(monkeypatch)
    assert resolve_provider_name("discover") == "firecrawl"
    assert resolve_provider_name("fetch") == "firecrawl"


def test_global_env_applies_both_stages(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SCRAPE_PROVIDER", "crawl4ai")
    assert resolve_provider_name("discover") == "crawl4ai"
    assert resolve_provider_name("fetch") == "crawl4ai"


def test_stage_specific_envs_mix(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SCRAPE_DISCOVER_PROVIDER", "crawl4ai")
    monkeypatch.setenv("SCRAPE_FETCH_PROVIDER", "firecrawl")
    assert resolve_provider_name("discover") == "crawl4ai"
    assert resolve_provider_name("fetch") == "firecrawl"


def test_stage_specific_overrides_global(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SCRAPE_PROVIDER", "foo")
    monkeypatch.setenv("SCRAPE_FETCH_PROVIDER", "bar")
    assert resolve_provider_name("fetch") == "bar"
    assert resolve_provider_name("discover") == "foo"


def test_empty_string_falls_back_to_default(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SCRAPE_PROVIDER", "")
    assert resolve_provider_name("discover") == "firecrawl"


def test_empty_stage_var_falls_back_to_global(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SCRAPE_PROVIDER", "crawl4ai")
    monkeypatch.setenv("SCRAPE_FETCH_PROVIDER", "")
    assert resolve_provider_name("fetch") == "crawl4ai"
