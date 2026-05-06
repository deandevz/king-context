"""Tests for provider injection at the pipeline level (cli.run_pipeline).

These tests verify the resolution + injection layer, not the providers themselves:
- default resolves to firecrawl (no env, no flag)
- --provider flag sets SCRAPE_PROVIDER for the run
- stage-specific envs win over the flag (per ADR-0009)
- unknown provider name → exit 2
- ProviderUnavailableError at runtime → exit 3 with hint
"""

from __future__ import annotations

import argparse
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from scraper_providers import (
    ProviderUnavailableError,
    register_discovery_provider,
    register_fetch_provider,
)

from king_context.scraper.cli import main, run_pipeline
from king_context.scraper.config import ScraperConfig
from king_context.scraper.discover import DiscoveryResult


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def clean_provider_env(monkeypatch):
    """Ensure no SCRAPE_* envs leak between tests."""
    monkeypatch.delenv("SCRAPE_PROVIDER", raising=False)
    monkeypatch.delenv("SCRAPE_DISCOVER_PROVIDER", raising=False)
    monkeypatch.delenv("SCRAPE_FETCH_PROVIDER", raising=False)


def _make_args(**overrides) -> argparse.Namespace:
    defaults = dict(
        url="https://docs.example.com",
        name="example",
        display_name="Example",
        step=None,
        model="test-model",
        chunk_max_tokens=800,
        chunk_min_tokens=50,
        concurrency=5,
        no_llm_filter=False,
        no_auto_seed=True,
        include_maybe=False,
        stop_after="discover",
        yes=True,
        provider=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _make_config() -> ScraperConfig:
    return ScraperConfig(firecrawl_api_key="fake", openrouter_api_key="fake")


class _RecordingDiscoveryProvider:
    name = "recording-discovery"

    def __init__(self):
        self.calls = []

    async def discover_urls(self, base_url: str) -> list[str]:
        self.calls.append(base_url)
        return []


class _RecordingFetchProvider:
    name = "recording-fetch"


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

def test_default_uses_firecrawl_provider(tmp_path, monkeypatch, clean_provider_env):
    """No env, no flag → cli resolves 'firecrawl' for both stages."""
    monkeypatch.setattr(
        "king_context.scraper.cli.get_work_dir", lambda url: tmp_path
    )

    captured: dict[str, str | None] = {"discovery_name": None, "fetch_name": None}

    real_get_discovery = __import__(
        "scraper_providers", fromlist=["get_discovery_provider"]
    ).get_discovery_provider
    real_get_fetch = __import__(
        "scraper_providers", fromlist=["get_fetch_provider"]
    ).get_fetch_provider

    def spy_get_discovery(name: str):
        captured["discovery_name"] = name
        return real_get_discovery(name)

    def spy_get_fetch(name: str):
        captured["fetch_name"] = name
        return real_get_fetch(name)

    discovery = DiscoveryResult(
        base_url="https://docs.example.com",
        discovered_at="2026-01-01",
        total_urls=0,
        urls=[],
    )

    with patch(
        "king_context.scraper.cli.get_discovery_provider",
        side_effect=spy_get_discovery,
    ), patch(
        "king_context.scraper.cli.get_fetch_provider",
        side_effect=spy_get_fetch,
    ), patch(
        "king_context.scraper.cli.discover_urls",
        new_callable=AsyncMock,
        return_value=discovery,
    ):
        asyncio.run(run_pipeline(_make_args(), _make_config()))

    assert captured["discovery_name"] == "firecrawl"
    assert captured["fetch_name"] == "firecrawl"


def test_provider_flag_sets_env(tmp_path, monkeypatch, clean_provider_env):
    """--provider=NAME → SCRAPE_PROVIDER set, both stages resolve to NAME."""
    monkeypatch.setattr(
        "king_context.scraper.cli.get_work_dir", lambda url: tmp_path
    )
    register_discovery_provider("flag-test", lambda: _RecordingDiscoveryProvider())
    register_fetch_provider("flag-test", lambda: _RecordingFetchProvider())

    captured: dict[str, str | None] = {"discovery_name": None, "fetch_name": None}

    def fake_get_discovery(name: str):
        captured["discovery_name"] = name
        return _RecordingDiscoveryProvider()

    def fake_get_fetch(name: str):
        captured["fetch_name"] = name
        return _RecordingFetchProvider()

    discovery = DiscoveryResult(
        base_url="https://docs.example.com",
        discovered_at="2026-01-01",
        total_urls=0,
        urls=[],
    )

    with patch(
        "king_context.scraper.cli.get_discovery_provider",
        side_effect=fake_get_discovery,
    ), patch(
        "king_context.scraper.cli.get_fetch_provider",
        side_effect=fake_get_fetch,
    ), patch(
        "king_context.scraper.cli.discover_urls",
        new_callable=AsyncMock,
        return_value=discovery,
    ):
        asyncio.run(run_pipeline(_make_args(provider="flag-test"), _make_config()))

    assert captured["discovery_name"] == "flag-test"
    assert captured["fetch_name"] == "flag-test"


def test_stage_env_overrides_flag(tmp_path, monkeypatch, clean_provider_env):
    """SCRAPE_FETCH_PROVIDER=X + --provider=Y → fetch=X, discover=Y."""
    monkeypatch.setattr(
        "king_context.scraper.cli.get_work_dir", lambda url: tmp_path
    )
    monkeypatch.setenv("SCRAPE_FETCH_PROVIDER", "stage-fetch")

    captured: dict[str, str | None] = {"discovery_name": None, "fetch_name": None}

    def fake_get_discovery(name: str):
        captured["discovery_name"] = name
        return _RecordingDiscoveryProvider()

    def fake_get_fetch(name: str):
        captured["fetch_name"] = name
        return _RecordingFetchProvider()

    discovery = DiscoveryResult(
        base_url="https://docs.example.com",
        discovered_at="2026-01-01",
        total_urls=0,
        urls=[],
    )

    with patch(
        "king_context.scraper.cli.get_discovery_provider",
        side_effect=fake_get_discovery,
    ), patch(
        "king_context.scraper.cli.get_fetch_provider",
        side_effect=fake_get_fetch,
    ), patch(
        "king_context.scraper.cli.discover_urls",
        new_callable=AsyncMock,
        return_value=discovery,
    ):
        asyncio.run(run_pipeline(_make_args(provider="flag-global"), _make_config()))

    # discover gets the flag (no stage env), fetch gets the stage env
    assert captured["discovery_name"] == "flag-global"
    assert captured["fetch_name"] == "stage-fetch"


def test_unknown_provider_exits_2(monkeypatch, clean_provider_env, capsys):
    """--provider=bogus → main() exits with code 2 and stderr lists registered."""
    monkeypatch.setattr(
        "sys.argv",
        ["king-scrape", "https://docs.example.com", "--provider", "bogus-xyz"],
    )
    monkeypatch.setattr(
        "king_context.scraper.cli.load_config", lambda **kwargs: _make_config()
    )

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "Unknown" in captured.err
    assert "bogus-xyz" in captured.err


def test_provider_unavailable_exits_3(tmp_path, monkeypatch, clean_provider_env, capsys):
    """ProviderUnavailableError at runtime → main() exits 3 with hint."""
    monkeypatch.setattr(
        "sys.argv",
        ["king-scrape", "https://docs.example.com", "--stop-after", "discover"],
    )
    monkeypatch.setattr(
        "king_context.scraper.cli.load_config", lambda **kwargs: _make_config()
    )
    monkeypatch.setattr(
        "king_context.scraper.cli.get_work_dir", lambda url: tmp_path
    )

    def boom(name: str):
        raise ProviderUnavailableError(name, "install hint: pip install king-context[firecrawl]")

    with patch(
        "king_context.scraper.cli.get_discovery_provider",
        side_effect=boom,
    ):
        with pytest.raises(SystemExit) as excinfo:
            main()

    assert excinfo.value.code == 3
    captured = capsys.readouterr()
    assert "pip install" in captured.err
