"""Tests for --stop-after and --yes CLI flags."""

import argparse
import json
from unittest.mock import AsyncMock, patch

import pytest

from king_context.scraper.cli import _build_parser, run_pipeline
from king_context.scraper.config import ScraperConfig
from king_context.scraper.discover import DiscoveryResult
from king_context.scraper.fetch import FetchResult
from king_context.scraper.filter import FilterResult


def _make_config() -> ScraperConfig:
    return ScraperConfig(
        firecrawl_api_key="fake",
        openrouter_api_key="fake",
    )


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
        stop_after=None,
        yes=False,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestStopAfterFlag:
    """--stop-after stops the pipeline after the given step."""

    @pytest.mark.asyncio
    async def test_stop_after_discover(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "king_context.scraper.cli.get_work_dir", lambda url: tmp_path
        )
        discovery = DiscoveryResult(
            base_url="https://docs.example.com",
            discovered_at="2026-01-01",
            total_urls=10,
            urls=["https://docs.example.com/a"],
        )
        with patch(
            "king_context.scraper.cli.discover_urls",
            new_callable=AsyncMock,
            return_value=discovery,
        ) as mock_discover, patch(
            "king_context.scraper.cli.filter_urls"
        ) as mock_filter:
            args = _make_args(stop_after="discover")
            await run_pipeline(args, _make_config())

            mock_discover.assert_called_once()
            mock_filter.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_after_fetch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "king_context.scraper.cli.get_work_dir", lambda url: tmp_path
        )
        discovery = DiscoveryResult(
            base_url="https://docs.example.com",
            discovered_at="2026-01-01",
            total_urls=2,
            urls=["https://docs.example.com/a", "https://docs.example.com/b"],
        )
        filter_result = FilterResult(
            accepted=["https://docs.example.com/a"],
            rejected=["https://docs.example.com/b"],
            maybe=[],
            filter_method="heuristic",
            llm_fallback_used=False,
        )
        fetch_result = FetchResult(total=1, completed=1, failed=0, results=[])

        with patch(
            "king_context.scraper.cli.discover_urls",
            new_callable=AsyncMock,
            return_value=discovery,
        ), patch(
            "king_context.scraper.cli.filter_urls",
            return_value=filter_result,
        ), patch(
            "king_context.scraper.cli.fetch_pages",
            new_callable=AsyncMock,
            return_value=fetch_result,
        ) as mock_fetch, patch(
            "king_context.scraper.cli.chunk_pages"
        ) as mock_chunk:
            args = _make_args(stop_after="fetch")
            await run_pipeline(args, _make_config())

            mock_fetch.assert_called_once()
            mock_chunk.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_after_chunk(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "king_context.scraper.cli.get_work_dir", lambda url: tmp_path
        )
        discovery = DiscoveryResult(
            base_url="https://docs.example.com",
            discovered_at="2026-01-01",
            total_urls=1,
            urls=["https://docs.example.com/a"],
        )
        filter_result = FilterResult(
            accepted=["https://docs.example.com/a"],
            rejected=[],
            maybe=[],
            filter_method="heuristic",
            llm_fallback_used=False,
        )
        fetch_result = FetchResult(total=1, completed=1, failed=0, results=[])

        with patch(
            "king_context.scraper.cli.discover_urls",
            new_callable=AsyncMock,
            return_value=discovery,
        ), patch(
            "king_context.scraper.cli.filter_urls",
            return_value=filter_result,
        ), patch(
            "king_context.scraper.cli.fetch_pages",
            new_callable=AsyncMock,
            return_value=fetch_result,
        ), patch(
            "king_context.scraper.cli.chunk_pages",
            return_value=[],
        ) as mock_chunk, patch(
            "king_context.scraper.cli.enrich_chunks",
            new_callable=AsyncMock,
        ) as mock_enrich:
            args = _make_args(stop_after="chunk")
            await run_pipeline(args, _make_config())

            mock_chunk.assert_called_once()
            mock_enrich.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_after_with_no_llm_filter(self, tmp_path, monkeypatch):
        """--stop-after works in combination with --no-llm-filter."""
        monkeypatch.setattr(
            "king_context.scraper.cli.get_work_dir", lambda url: tmp_path
        )
        discovery = DiscoveryResult(
            base_url="https://docs.example.com",
            discovered_at="2026-01-01",
            total_urls=1,
            urls=["https://docs.example.com/a"],
        )
        filter_result = FilterResult(
            accepted=["https://docs.example.com/a"],
            rejected=[],
            maybe=[],
            filter_method="heuristic",
            llm_fallback_used=False,
        )
        fetch_result = FetchResult(total=1, completed=1, failed=0, results=[])

        with patch(
            "king_context.scraper.cli.discover_urls",
            new_callable=AsyncMock,
            return_value=discovery,
        ), patch(
            "king_context.scraper.cli.filter_urls",
            return_value=filter_result,
        ), patch(
            "king_context.scraper.cli.fetch_pages",
            new_callable=AsyncMock,
            return_value=fetch_result,
        ), patch(
            "king_context.scraper.cli.chunk_pages",
            return_value=[],
        ) as mock_chunk:
            args = _make_args(stop_after="chunk", no_llm_filter=True)
            await run_pipeline(args, _make_config())

            mock_chunk.assert_called_once()


class TestYesFlag:
    """--yes skips the enrichment confirmation prompt."""

    @pytest.mark.asyncio
    async def test_yes_skips_confirmation(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "king_context.scraper.cli.get_work_dir", lambda url: tmp_path
        )

        # Pre-populate chunks checkpoint
        chunks_dir = tmp_path / "chunks"
        chunks_dir.mkdir()
        chunk_data = [{
            "title": "Test",
            "breadcrumb": "Test > A",
            "content": "Hello world",
            "source_url": "https://docs.example.com/a",
            "path": "/a",
            "token_count": 5,
        }]
        (chunks_dir / "group_000.json").write_text(json.dumps(chunk_data))

        # Mark earlier steps as done in manifest
        manifest = {
            "discovery": {"status": "done"},
            "filtering": {"status": "done"},
            "fetch": {"status": "done"},
            "chunking": {"status": "done"},
        }
        (tmp_path / "manifest.json").write_text(json.dumps(manifest))

        # Provide checkpoint files so earlier steps are skipped
        disc_data = {
            "base_url": "https://docs.example.com",
            "discovered_at": "2026-01-01",
            "total_urls": 1,
            "urls": ["https://docs.example.com/a"],
        }
        (tmp_path / "discovered_urls.json").write_text(json.dumps(disc_data))
        filt_data = {
            "accepted": ["https://docs.example.com/a"],
            "rejected": [],
            "maybe": [],
            "filter_method": "heuristic",
            "llm_fallback_used": False,
        }
        (tmp_path / "filtered_urls.json").write_text(json.dumps(filt_data))

        from king_context.scraper.enrich import EnrichedChunk

        enriched = [
            EnrichedChunk(
                title="Test",
                path="/a",
                url="https://docs.example.com/a",
                content="Hello world",
                keywords=["test"] * 5,
                use_cases=["Use when testing"] * 2,
                tags=["test"],
                priority=5,
            )
        ]

        with patch(
            "king_context.scraper.cli.enrich_chunks",
            new_callable=AsyncMock,
            return_value=enriched,
        ) as mock_enrich, patch(
            "king_context.scraper.cli.estimate_cost",
            return_value={"estimated_cost": 0.001, "total_chunks": 1, "model": "test"},
        ), patch("builtins.input") as mock_input:
            args = _make_args(yes=True, stop_after="enrich")
            await run_pipeline(args, _make_config())

            mock_enrich.assert_called_once()
            mock_input.assert_not_called()

    @pytest.mark.asyncio
    async def test_without_yes_prompts_user(self, tmp_path, monkeypatch):
        """Without --yes, the enrichment step asks for confirmation."""
        monkeypatch.setattr(
            "king_context.scraper.cli.get_work_dir", lambda url: tmp_path
        )

        chunks_dir = tmp_path / "chunks"
        chunks_dir.mkdir()
        chunk_data = [{
            "title": "Test",
            "breadcrumb": "Test > A",
            "content": "Hello",
            "source_url": "https://docs.example.com/a",
            "path": "/a",
            "token_count": 5,
        }]
        (chunks_dir / "group_000.json").write_text(json.dumps(chunk_data))

        manifest = {
            "discovery": {"status": "done"},
            "filtering": {"status": "done"},
            "fetch": {"status": "done"},
            "chunking": {"status": "done"},
        }
        (tmp_path / "manifest.json").write_text(json.dumps(manifest))
        (tmp_path / "discovered_urls.json").write_text(json.dumps({
            "base_url": "https://docs.example.com",
            "discovered_at": "2026-01-01",
            "total_urls": 1,
            "urls": ["https://docs.example.com/a"],
        }))
        (tmp_path / "filtered_urls.json").write_text(json.dumps({
            "accepted": ["https://docs.example.com/a"],
            "rejected": [],
            "maybe": [],
            "filter_method": "heuristic",
            "llm_fallback_used": False,
        }))

        with patch(
            "king_context.scraper.cli.estimate_cost",
            return_value={"estimated_cost": 0.001, "total_chunks": 1, "model": "test"},
        ), patch("builtins.input", return_value="n") as mock_input:
            args = _make_args(yes=False, stop_after="enrich")
            await run_pipeline(args, _make_config())

            mock_input.assert_called_once()


class TestParserFlags:
    """Flags appear in the parser and --help."""

    def test_stop_after_in_parser(self):
        parser = _build_parser()
        args = parser.parse_args(["https://example.com", "--stop-after", "chunk"])
        assert args.stop_after == "chunk"

    def test_yes_in_parser(self):
        parser = _build_parser()
        args = parser.parse_args(["https://example.com", "--yes"])
        assert args.yes is True

    def test_yes_short_flag(self):
        parser = _build_parser()
        args = parser.parse_args(["https://example.com", "-y"])
        assert args.yes is True

    def test_stop_after_rejects_invalid_step(self):
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["https://example.com", "--stop-after", "invalid"])
