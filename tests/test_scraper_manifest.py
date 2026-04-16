"""Tests for partial progress tracking in manifest during fetch and enrich."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from king_context.scraper.chunk import Chunk
from king_context.scraper.config import ScraperConfig
from king_context.scraper.fetch import FetchResult, PageResult, fetch_pages
from king_context.scraper.enrich import enrich_chunks, EnrichedChunk


def _make_config() -> ScraperConfig:
    return ScraperConfig(
        firecrawl_api_key="fake",
        openrouter_api_key="fake",
        enrichment_batch_size=2,
        concurrency=5,
    )


def _read_manifest(work_dir):
    return json.loads((work_dir / "manifest.json").read_text())


class TestFetchManifestProgress:
    """fetch_pages updates manifest with in_progress and done status."""

    @pytest.mark.asyncio
    async def test_fetch_shows_in_progress(self, tmp_path):
        """During fetch, manifest shows in_progress with completed count."""
        pages_dir = tmp_path / "pages"
        pages_dir.mkdir(parents=True)
        urls = ["https://example.com/a", "https://example.com/b", "https://example.com/c"]
        config = _make_config()

        manifests_during_fetch = []

        original_update_step = None

        def _capture_update(work_dir, step, stats):
            """Capture manifest updates during fetch."""
            from king_context.scraper.discover import _update_step as real_update
            real_update(work_dir, step, stats)
            manifests_during_fetch.append(dict(stats))

        with patch(
            "king_context.scraper.fetch._fetch_one",
            new_callable=AsyncMock,
            side_effect=[
                PageResult(url=u, markdown=f"# {u}", success=True, error=None)
                for u in urls
            ],
        ), patch(
            "king_context.scraper.fetch._update_step",
            side_effect=_capture_update,
        ), patch(
            "king_context.scraper.fetch.FirecrawlApp",
        ):
            result = await fetch_pages(urls, tmp_path, config)

        # At least one in_progress update happened
        in_progress = [m for m in manifests_during_fetch if m["status"] == "in_progress"]
        assert len(in_progress) >= 1

        # Each in_progress has completed and total fields
        for m in in_progress:
            assert "completed" in m
            assert "total" in m
            assert m["total"] == 3

        # Final update is done
        assert manifests_during_fetch[-1]["status"] == "done"
        assert manifests_during_fetch[-1]["completed"] == 3

    @pytest.mark.asyncio
    async def test_fetch_done_status(self, tmp_path):
        """After fetch completes, manifest shows done with correct counts."""
        pages_dir = tmp_path / "pages"
        pages_dir.mkdir(parents=True)
        urls = ["https://example.com/a"]
        config = _make_config()

        with patch(
            "king_context.scraper.fetch._fetch_one",
            new_callable=AsyncMock,
            return_value=PageResult(url=urls[0], markdown="# A", success=True, error=None),
        ), patch(
            "king_context.scraper.fetch.FirecrawlApp",
        ):
            result = await fetch_pages(urls, tmp_path, config)

        manifest = _read_manifest(tmp_path)
        assert manifest["fetch"]["status"] == "done"
        assert manifest["fetch"]["completed"] == 1
        assert manifest["fetch"]["total"] == 1


class TestEnrichManifestProgress:
    """enrich_chunks updates manifest with in_progress and done status."""

    @pytest.mark.asyncio
    async def test_enrich_shows_in_progress(self, tmp_path):
        """During enrich, manifest shows in_progress with enriched count."""
        chunks = [
            Chunk(title=f"C{i}", breadcrumb="", content=f"content {i}",
                  source_url=f"https://example.com/{i}", path=f"/{i}", token_count=10)
            for i in range(4)
        ]
        config = _make_config()  # batch_size=2, so 2 batches

        enrichment = {
            "keywords": ["k1", "k2", "k3", "k4", "k5"],
            "use_cases": ["u1", "u2"],
            "tags": ["t1"],
            "priority": 5,
        }

        with patch(
            "king_context.scraper.enrich.call_openrouter",
            new_callable=AsyncMock,
            return_value=enrichment,
        ):
            result = await enrich_chunks(chunks, config, output_dir=tmp_path)

        manifest = _read_manifest(tmp_path)
        assert manifest["enrichment"]["status"] == "done"
        assert manifest["enrichment"]["enriched"] == 4
        assert manifest["enrichment"]["total"] == 4

    @pytest.mark.asyncio
    async def test_enrich_done_status(self, tmp_path):
        """After enrich completes, manifest shows done with correct total."""
        chunks = [
            Chunk(title="Only", breadcrumb="", content="content",
                  source_url="https://example.com/only", path="/only", token_count=10)
        ]
        config = _make_config()

        enrichment = {
            "keywords": ["k1", "k2", "k3", "k4", "k5"],
            "use_cases": ["u1", "u2"],
            "tags": ["t1"],
            "priority": 5,
        }

        with patch(
            "king_context.scraper.enrich.call_openrouter",
            new_callable=AsyncMock,
            return_value=enrichment,
        ):
            result = await enrich_chunks(chunks, config, output_dir=tmp_path)

        manifest = _read_manifest(tmp_path)
        assert manifest["enrichment"]["status"] == "done"
        assert manifest["enrichment"]["enriched"] == 1
        assert manifest["enrichment"]["total"] == 1

    @pytest.mark.asyncio
    async def test_enrich_progress_transitions_to_done(self, tmp_path):
        """Manifest transitions from in_progress to done during enrich."""
        chunks = [
            Chunk(title=f"C{i}", breadcrumb="", content=f"content {i}",
                  source_url=f"https://example.com/{i}", path=f"/{i}", token_count=10)
            for i in range(4)
        ]
        config = _make_config()  # batch_size=2

        manifests_captured = []

        def _capture_update(work_dir, step, stats):
            from king_context.scraper.discover import _update_step as real_update
            real_update(work_dir, step, stats)
            manifests_captured.append(dict(stats))

        enrichment = {
            "keywords": ["k1", "k2", "k3", "k4", "k5"],
            "use_cases": ["u1", "u2"],
            "tags": ["t1"],
            "priority": 5,
        }

        with patch(
            "king_context.scraper.enrich.call_openrouter",
            new_callable=AsyncMock,
            return_value=enrichment,
        ), patch(
            "king_context.scraper.enrich._update_step",
            side_effect=_capture_update,
        ):
            result = await enrich_chunks(chunks, config, output_dir=tmp_path)

        # Should have in_progress updates followed by done
        statuses = [m["status"] for m in manifests_captured]
        assert "in_progress" in statuses
        assert statuses[-1] == "done"

        # The first in_progress should show partial enrichment
        first_ip = next(m for m in manifests_captured if m["status"] == "in_progress")
        assert first_ip["enriched"] == 2  # first batch of 2
        assert first_ip["total"] == 4
