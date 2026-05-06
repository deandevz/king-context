"""Tests for scraper_providers.base — Protocols, PageContent, ProviderUnavailableError."""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest

from scraper_providers import (
    DiscoveryProvider,
    FetchProvider,
    PageContent,
    ProviderUnavailableError,
)


def test_page_content_frozen():
    page = PageContent(
        url="https://example.com",
        markdown="# Hello",
        fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        page.url = "https://other.example.com"  # type: ignore[misc]


def test_page_content_title_optional():
    page = PageContent(
        url="https://example.com",
        markdown="# Hello",
        fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert page.title is None


def test_provider_unavailable_carries_hint():
    err = ProviderUnavailableError("crawl4ai", "run crawl4ai-setup")
    assert err.provider == "crawl4ai"
    assert err.hint == "run crawl4ai-setup"
    assert "crawl4ai" in str(err)
    assert "run crawl4ai-setup" in str(err)
    assert isinstance(err, RuntimeError)


def test_provider_unavailable_distinct_from_value_error():
    err = ProviderUnavailableError("foo", "install bar")
    assert not isinstance(err, ValueError)


class _StubDiscovery:
    name = "stub"

    async def discover_urls(self, base_url: str) -> list[str]:
        return [base_url]


class _StubFetch:
    name = "stub"

    async def fetch_one(self, url: str) -> PageContent:
        return PageContent(
            url=url,
            markdown="",
            fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


def test_protocols_runtime_checkable():
    assert isinstance(_StubDiscovery(), DiscoveryProvider)
    assert isinstance(_StubFetch(), FetchProvider)
