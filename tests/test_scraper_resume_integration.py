"""Integration tests for pipeline resume — fetch + enrich + full pipeline."""

import argparse
import json
from unittest.mock import AsyncMock, patch

import pytest

from king_context.scraper.chunk import Chunk
from king_context.scraper.cli import run_pipeline
from king_context.scraper.config import ScraperConfig
from king_context.scraper.discover import DiscoveryResult
from king_context.scraper.enrich import EnrichedChunk
from king_context.scraper.fetch import FetchResult, PageResult, _url_to_slug
from king_context.scraper.filter import FilterResult


def _make_config() -> ScraperConfig:
    return ScraperConfig(
        firecrawl_api_key="fake",
        openrouter_api_key="fake",
        enrichment_batch_size=5,
        concurrency=5,
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
        yes=True,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _make_enriched_data(count: int, start_idx: int = 0) -> list[dict]:
    """Create enriched chunk data dicts for batch files."""
    return [
        {
            "title": f"Section {i}",
            "path": f"/section-{i}",
            "url": f"https://docs.example.com/section-{i}",
            "content": f"Content for section {i}",
            "keywords": [f"kw{j}" for j in range(5)],
            "use_cases": [f"Use case {j}" for j in range(2)],
            "tags": ["test"],
            "priority": 5,
        }
        for i in range(start_idx, start_idx + count)
    ]


def _make_chunk_data(count: int) -> list[dict]:
    """Create chunk data dicts for chunk files."""
    return [
        {
            "title": f"Section {i}",
            "breadcrumb": f"Docs > Section {i}",
            "content": f"Content for section {i}",
            "source_url": f"https://docs.example.com/section-{i}",
            "path": f"/section-{i}",
            "token_count": 20,
        }
        for i in range(count)
    ]


def _setup_work_dir(
    tmp_path,
    *,
    total_urls: int,
    fetched_pages: int,
    total_chunks: int,
    enriched_chunks: int,
):
    """Set up a work_dir simulating a partially completed pipeline."""
    urls = [f"https://docs.example.com/section-{i}" for i in range(total_urls)]

    # discovery checkpoint
    disc_data = {
        "base_url": "https://docs.example.com",
        "discovered_at": "2026-01-01",
        "total_urls": total_urls,
        "urls": urls,
    }
    (tmp_path / "discovered_urls.json").write_text(json.dumps(disc_data))

    # filter checkpoint
    filt_data = {
        "accepted": urls,
        "rejected": [],
        "maybe": [],
        "filter_method": "heuristic",
        "llm_fallback_used": False,
    }
    (tmp_path / "filtered_urls.json").write_text(json.dumps(filt_data))

    # pages — simulate partial fetch
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    for i in range(fetched_pages):
        slug = _url_to_slug(urls[i])
        (pages_dir / f"{slug}.md").write_text(f"# Section {i}\nContent for section {i}")

    # manifest with partial progress
    manifest = {
        "discovery": {"status": "done", "total_urls": total_urls},
        "filtering": {"status": "done"},
    }
    if fetched_pages > 0:
        manifest["fetch"] = {
            "status": "in_progress" if fetched_pages < total_urls else "done",
            "total": total_urls,
            "completed": fetched_pages,
        }
    if total_chunks > 0:
        # chunks checkpoint
        chunks_dir = tmp_path / "chunks"
        chunks_dir.mkdir()
        (chunks_dir / "group_000.json").write_text(
            json.dumps(_make_chunk_data(total_chunks))
        )
        manifest["chunking"] = {"status": "done", "total_chunks": total_chunks}

    if enriched_chunks > 0:
        enriched_dir = tmp_path / "enriched"
        enriched_dir.mkdir()
        (enriched_dir / "batch_0000.json").write_text(
            json.dumps(_make_enriched_data(enriched_chunks))
        )
        manifest["enrichment"] = {
            "status": "in_progress",
            "enriched": enriched_chunks,
            "total": total_chunks,
        }

    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return urls


class TestFetchResumeIntegration:
    """Simulate interrupted fetch → resume downloads remaining pages."""

    @pytest.mark.asyncio
    async def test_fetch_resume_downloads_remaining(self, tmp_path, monkeypatch):
        """40/100 pages already fetched → resume fetches 60."""
        monkeypatch.setattr(
            "king_context.scraper.cli.get_work_dir", lambda url: tmp_path
        )
        total = 100
        already_fetched = 40
        urls = _setup_work_dir(
            tmp_path, total_urls=total, fetched_pages=already_fetched,
            total_chunks=0, enriched_chunks=0,
        )

        fetched_urls = []

        async def mock_fetch_one(url, semaphore, pages_dir, app):
            fetched_urls.append(url)
            slug = _url_to_slug(url)
            (pages_dir / f"{slug}.md").write_text(f"# {url}")
            return PageResult(url=url, markdown=f"# {url}", success=True, error=None)

        with patch(
            "king_context.scraper.fetch._fetch_one",
            side_effect=mock_fetch_one,
        ), patch(
            "king_context.scraper.fetch.FirecrawlApp",
        ), patch(
            "king_context.scraper.cli.chunk_pages",
            return_value=[],
        ):
            args = _make_args(stop_after="fetch")
            await run_pipeline(args, _make_config())

        # Should have fetched exactly the remaining 60
        assert len(fetched_urls) == total - already_fetched
        # None of the already-fetched URLs should be in the list
        existing_slugs = {_url_to_slug(urls[i]) for i in range(already_fetched)}
        for url in fetched_urls:
            assert _url_to_slug(url) not in existing_slugs


class TestEnrichResumeIntegration:
    """Simulate interrupted enrich → resume enriches remaining chunks."""

    @pytest.mark.asyncio
    async def test_enrich_resume_processes_remaining(self, tmp_path, monkeypatch):
        """30/80 chunks already enriched → resume enriches 50."""
        monkeypatch.setattr(
            "king_context.scraper.cli.get_work_dir", lambda url: tmp_path
        )
        total_chunks = 80
        already_enriched = 30
        _setup_work_dir(
            tmp_path, total_urls=80, fetched_pages=80,
            total_chunks=total_chunks, enriched_chunks=already_enriched,
        )

        api_call_count = 0

        async def mock_call_openrouter(prompt, config):
            nonlocal api_call_count
            api_call_count += 1
            return {
                "keywords": [f"kw{j}" for j in range(5)],
                "use_cases": [f"Use when {j}" for j in range(2)],
                "tags": ["test"],
                "priority": 5,
            }

        with patch(
            "king_context.scraper.enrich.call_openrouter",
            side_effect=mock_call_openrouter,
        ):
            args = _make_args(stop_after="enrich", yes=True)
            await run_pipeline(args, _make_config())

        # Should have made API calls only for remaining chunks
        remaining = total_chunks - already_enriched
        assert api_call_count == remaining

        # Final enriched dir should have all chunks
        enriched_dir = tmp_path / "enriched"
        batch_files = sorted(enriched_dir.glob("batch_*.json"))
        last_batch = json.loads(batch_files[-1].read_text())
        assert len(last_batch) == total_chunks


class TestFullPipelineResumeIntegration:
    """Full pipeline with resume — fetch resume + enrich resume → export produces correct JSON."""

    @pytest.mark.asyncio
    async def test_full_pipeline_resume_to_export(self, tmp_path, monkeypatch):
        """Pipeline interrupted at enrich (20/40 chunks). Resume → export produces correct JSON."""
        monkeypatch.setattr(
            "king_context.scraper.cli.get_work_dir", lambda url: tmp_path
        )
        monkeypatch.setattr(
            "king_context.scraper.cli.PROJECT_ROOT", tmp_path,
        )

        total_urls = 40
        total_chunks = 40
        already_enriched = 20

        _setup_work_dir(
            tmp_path, total_urls=total_urls, fetched_pages=total_urls,
            total_chunks=total_chunks, enriched_chunks=already_enriched,
        )

        async def mock_call_openrouter(prompt, config):
            return {
                "keywords": [f"kw{j}" for j in range(5)],
                "use_cases": [f"Use when {j}" for j in range(2)],
                "tags": ["test"],
                "priority": 5,
            }

        with patch(
            "king_context.scraper.enrich.call_openrouter",
            side_effect=mock_call_openrouter,
        ), patch(
            "king_context.scraper.export.seed_data",
        ):
            # Create .king-context/data/ dir for export output
            (tmp_path / ".king-context" / "data").mkdir(parents=True, exist_ok=True)

            args = _make_args(yes=True, no_auto_seed=True)
            await run_pipeline(args, _make_config())

        # Export should have created the JSON file
        output_path = tmp_path / ".king-context" / "data" / "example.json"
        assert output_path.exists()

        doc_data = json.loads(output_path.read_text())
        assert doc_data["name"] == "example"
        assert len(doc_data["sections"]) == total_chunks
