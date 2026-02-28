import argparse
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from king_context.scraper.chunk import Chunk
from king_context.scraper.config import ScraperConfig
from king_context.scraper.discover import DiscoveryResult
from king_context.scraper.enrich import EnrichedChunk
from king_context.scraper.fetch import FetchResult
from king_context.scraper.filter import FilterResult
from king_context.scraper.cli import (
    _build_parser,
    _name_from_url,
    run_pipeline,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_args(**kwargs) -> argparse.Namespace:
    defaults = dict(
        url="https://docs.example.com",
        name="example",
        display_name="Example Docs",
        step=None,
        model="google/gemini-flash-2.0",
        chunk_max_tokens=800,
        chunk_min_tokens=50,
        concurrency=5,
        no_llm_filter=False,
        no_auto_seed=True,
        include_maybe=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def make_enriched_chunk(title: str = "Section") -> EnrichedChunk:
    return EnrichedChunk(
        title=title,
        path="/docs/section",
        url="https://docs.example.com/section",
        content="Content here.",
        keywords=["kw1", "kw2", "kw3", "kw4", "kw5"],
        use_cases=["Use when testing", "Configure when needed"],
        tags=["testing"],
        priority=5,
    )


def make_chunk(title: str = "Section") -> Chunk:
    return Chunk(
        title=title,
        breadcrumb=title,
        content="Content here.",
        source_url="https://docs.example.com/page",
        path="/page/section",
        token_count=50,
    )


# ---------------------------------------------------------------------------
# _name_from_url
# ---------------------------------------------------------------------------

def test_cli_name_from_url_docs_subdomain():
    assert _name_from_url("https://docs.stripe.com") == "stripe"


def test_cli_name_from_url_api_subdomain():
    assert _name_from_url("https://api.stripe.com") == "stripe"


def test_cli_name_from_url_www():
    assert _name_from_url("https://www.example.com") == "example"


def test_cli_name_from_url_plain_domain():
    assert _name_from_url("https://reactjs.org") == "reactjs"


def test_cli_name_from_url_io_tld():
    assert _name_from_url("https://docs.fastapi.io") == "fastapi"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def test_cli_parse_args_basic():
    parser = _build_parser()
    args = parser.parse_args(["https://docs.stripe.com"])
    assert args.url == "https://docs.stripe.com"
    assert args.name is None
    assert args.step is None
    assert args.model == "google/gemini-flash-2.0"
    assert args.chunk_max_tokens == 800
    assert args.chunk_min_tokens == 50
    assert args.concurrency == 5
    assert args.no_llm_filter is False
    assert args.no_auto_seed is False
    assert args.include_maybe is False


def test_cli_parse_args_with_flags():
    parser = _build_parser()
    args = parser.parse_args([
        "https://docs.stripe.com",
        "--name", "stripe",
        "--display-name", "Stripe Docs",
        "--step", "chunk",
        "--model", "openai/gpt-4o-mini",
        "--chunk-max-tokens", "600",
        "--chunk-min-tokens", "30",
        "--concurrency", "10",
        "--no-llm-filter",
        "--no-auto-seed",
        "--include-maybe",
    ])
    assert args.name == "stripe"
    assert args.display_name == "Stripe Docs"
    assert args.step == "chunk"
    assert args.model == "openai/gpt-4o-mini"
    assert args.chunk_max_tokens == 600
    assert args.chunk_min_tokens == 30
    assert args.concurrency == 10
    assert args.no_llm_filter is True
    assert args.no_auto_seed is True
    assert args.include_maybe is True


def test_cli_parse_args_invalid_step():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["https://docs.example.com", "--step", "invalid"])


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def test_cli_full_pipeline(tmp_path):
    work_dir = tmp_path / "docs-example-com"
    work_dir.mkdir()

    config = ScraperConfig()
    args = make_args(step=None)
    call_order = []

    discovery = DiscoveryResult(
        base_url="https://docs.example.com",
        discovered_at="2026-01-01T00:00:00+00:00",
        total_urls=3,
        urls=["https://docs.example.com/a", "https://docs.example.com/b"],
    )
    filter_res = FilterResult(
        accepted=["https://docs.example.com/a"],
        rejected=[],
        maybe=[],
        filter_method="heuristic",
        llm_fallback_used=False,
    )
    fetch_res = FetchResult(total=1, completed=1, failed=0, results=[])
    chunks = [make_chunk()]
    enriched = [make_enriched_chunk()]
    doc_data = {"name": "example", "sections": []}

    async def mock_discover(url, cfg):
        call_order.append("discover")
        return discovery

    async def mock_fetch(urls, out_dir, cfg):
        call_order.append("fetch")
        return fetch_res

    async def mock_enrich(chunks_arg, cfg, output_dir=None):
        call_order.append("enrich")
        return enriched

    with (
        patch("king_context.scraper.cli.get_work_dir", return_value=work_dir),
        patch("king_context.scraper.cli.discover_urls", side_effect=mock_discover),
        patch("king_context.scraper.cli.filter_urls", side_effect=lambda urls, url, cfg: (
            call_order.append("filter") or filter_res
        )),
        patch("king_context.scraper.cli.fetch_pages", side_effect=mock_fetch),
        patch("king_context.scraper.cli.chunk_pages", side_effect=lambda p, o, cfg: (
            call_order.append("chunk") or chunks
        )),
        patch("king_context.scraper.cli.enrich_chunks", side_effect=mock_enrich),
        patch("king_context.scraper.cli.export_to_json", side_effect=lambda *a, **kw: (
            call_order.append("export") or doc_data
        )),
        patch("king_context.scraper.cli.save_and_index"),
        patch("king_context.scraper.cli._update_step"),
        patch("builtins.input", return_value="y"),
    ):
        asyncio.run(run_pipeline(args, config))

    assert call_order == ["discover", "filter", "fetch", "chunk", "enrich", "export"]


# ---------------------------------------------------------------------------
# Step resume
# ---------------------------------------------------------------------------

def test_cli_step_resume(tmp_path):
    """--step chunk should skip discovery, filtering, and fetching."""
    work_dir = tmp_path / "docs-example-com"
    work_dir.mkdir()

    # Create pages dir so chunk_pages can find it
    pages_dir = work_dir / "pages"
    pages_dir.mkdir()

    # Write a manifest marking earlier steps as done
    manifest = {
        "discovery": {"status": "done", "total_urls": 5},
        "filtering": {"status": "done", "accepted": 3},
        "fetch": {"status": "done", "total": 3, "completed": 3},
    }
    (work_dir / "manifest.json").write_text(json.dumps(manifest))

    config = ScraperConfig()
    args = make_args(step="chunk")

    chunks = [make_chunk()]

    with (
        patch("king_context.scraper.cli.get_work_dir", return_value=work_dir),
        patch("king_context.scraper.cli.discover_urls") as mock_discover,
        patch("king_context.scraper.cli.filter_urls") as mock_filter,
        patch("king_context.scraper.cli.fetch_pages") as mock_fetch,
        patch("king_context.scraper.cli.chunk_pages", return_value=chunks),
        patch("king_context.scraper.cli.enrich_chunks", new_callable=AsyncMock, return_value=[]),
        patch("king_context.scraper.cli.export_to_json", return_value={}),
        patch("king_context.scraper.cli.save_and_index"),
        patch("king_context.scraper.cli._update_step"),
        patch("builtins.input", return_value="y"),
    ):
        asyncio.run(run_pipeline(args, config))

    mock_discover.assert_not_called()
    mock_filter.assert_not_called()
    mock_fetch.assert_not_called()


def test_cli_step_resume_skips_completed_in_full_pipeline(tmp_path):
    """Full pipeline skips steps already marked done in the manifest."""
    work_dir = tmp_path / "docs-example-com"
    work_dir.mkdir()

    # Discovery is already done
    manifest = {"discovery": {"status": "done", "total_urls": 2}}
    (work_dir / "manifest.json").write_text(json.dumps(manifest))

    # Write the checkpoint file that the skip handler will read
    disc_data = {
        "base_url": "https://docs.example.com",
        "discovered_at": "2026-01-01T00:00:00+00:00",
        "total_urls": 2,
        "urls": ["https://docs.example.com/a"],
    }
    (work_dir / "discovered_urls.json").write_text(json.dumps(disc_data))

    config = ScraperConfig()
    args = make_args(step=None)

    filter_res = FilterResult(
        accepted=["https://docs.example.com/a"],
        rejected=[],
        maybe=[],
        filter_method="heuristic",
        llm_fallback_used=False,
    )

    with (
        patch("king_context.scraper.cli.get_work_dir", return_value=work_dir),
        patch("king_context.scraper.cli.discover_urls") as mock_discover,
        patch("king_context.scraper.cli.filter_urls", return_value=filter_res),
        patch("king_context.scraper.cli.fetch_pages", new_callable=AsyncMock,
              return_value=FetchResult(total=1, completed=1, failed=0, results=[])),
        patch("king_context.scraper.cli.chunk_pages", return_value=[make_chunk()]),
        patch("king_context.scraper.cli.enrich_chunks", new_callable=AsyncMock,
              return_value=[make_enriched_chunk()]),
        patch("king_context.scraper.cli.export_to_json", return_value={}),
        patch("king_context.scraper.cli.save_and_index"),
        patch("king_context.scraper.cli._update_step"),
        patch("builtins.input", return_value="y"),
    ):
        asyncio.run(run_pipeline(args, config))

    mock_discover.assert_not_called()
