"""Shared fixtures for scraper_providers tests."""
from __future__ import annotations

import pytest

from scraper_providers import registry


@pytest.fixture(autouse=True)
def reset_registries():
    """Snapshot and restore registry state around every test so registrations
    in one test do not leak into the next.
    """
    discovery_snapshot = dict(registry._DISCOVERY_FACTORIES)
    fetch_snapshot = dict(registry._FETCH_FACTORIES)
    registry._DISCOVERY_FACTORIES.clear()
    registry._FETCH_FACTORIES.clear()
    try:
        yield
    finally:
        registry._DISCOVERY_FACTORIES.clear()
        registry._FETCH_FACTORIES.clear()
        registry._DISCOVERY_FACTORIES.update(discovery_snapshot)
        registry._FETCH_FACTORIES.update(fetch_snapshot)
