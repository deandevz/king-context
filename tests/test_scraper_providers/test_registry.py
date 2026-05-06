"""Tests for scraper_providers.registry — register/get/conflict semantics."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scraper_providers import (
    PageContent,
    get_discovery_provider,
    get_fetch_provider,
    register_discovery_provider,
    register_fetch_provider,
)


class _StubDiscovery:
    name = "stub-discovery"

    async def discover_urls(self, base_url: str) -> list[str]:
        return [base_url]


class _StubFetch:
    name = "stub-fetch"

    async def fetch_one(self, url: str) -> PageContent:
        return PageContent(
            url=url,
            markdown="",
            fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


def test_register_and_get_discovery():
    register_discovery_provider("stub", _StubDiscovery)
    instance = get_discovery_provider("stub")
    assert isinstance(instance, _StubDiscovery)


def test_register_and_get_fetch():
    register_fetch_provider("stub", _StubFetch)
    instance = get_fetch_provider("stub")
    assert isinstance(instance, _StubFetch)


def test_unknown_discovery_provider_raises():
    register_discovery_provider("alpha", _StubDiscovery)
    register_discovery_provider("beta", _StubDiscovery)
    with pytest.raises(ValueError) as excinfo:
        get_discovery_provider("missing")
    msg = str(excinfo.value)
    assert "missing" in msg
    assert "alpha" in msg
    assert "beta" in msg


def test_unknown_fetch_provider_raises():
    register_fetch_provider("alpha", _StubFetch)
    with pytest.raises(ValueError) as excinfo:
        get_fetch_provider("missing")
    assert "alpha" in str(excinfo.value)


def test_builtin_wins_on_conflict_discovery():
    register_discovery_provider("stub", _StubDiscovery)

    class _Other:
        name = "other"

        async def discover_urls(self, base_url: str) -> list[str]:
            return []

    register_discovery_provider("stub", _Other)
    instance = get_discovery_provider("stub")
    assert isinstance(instance, _StubDiscovery)


def test_builtin_wins_on_conflict_fetch():
    register_fetch_provider("stub", _StubFetch)

    class _Other:
        name = "other"

        async def fetch_one(self, url: str) -> PageContent:
            return PageContent(
                url=url,
                markdown="other",
                fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )

    register_fetch_provider("stub", _Other)
    instance = get_fetch_provider("stub")
    assert isinstance(instance, _StubFetch)
