"""Tests for the research pipeline orchestration."""
from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from king_context.research.config import EffortLevel, ResearchConfig
from king_context.research.fetch import SourceDoc
from king_context.research.pipeline import run_pipeline
from king_context.scraper.chunk import Chunk
from king_context.scraper.config import ConfigError, ScraperConfig
from king_context.scraper.enrich import EnrichedChunk


def make_config(**over) -> ResearchConfig:
    defaults = dict(
        scraper=ScraperConfig(
            openrouter_api_key="or-k",
            firecrawl_api_key="fc-k",
        ),
        exa_api_key="exa-k",
    )
    defaults.update(over)
    return ResearchConfig(**defaults)


def make_args(**over) -> Namespace:
    defaults = dict(
        topic="prompt engineering",
        effort=EffortLevel.BASIC,
        name=None,
        step=None,
        stop_after=None,
        no_filter=False,
        yes=True,
        no_auto_index=False,
        force=False,
    )
    defaults.update(over)
    return Namespace(**defaults)


def mk_source(url: str = "https://ex.com/a") -> SourceDoc:
    return SourceDoc(
        url=url,
        title="T",
        content="word " * 200,
        author="A",
        published_date=None,
        domain="ex.com",
        query="q",
        discovery_iteration=0,
        score=0.5,
        fetch_path="exa",
    )


def mk_chunk(url: str = "https://ex.com/a") -> Chunk:
    return Chunk(
        title="T",
        breadcrumb="T",
        content="chunk content goes here",
        source_url=url,
        path="/a/t",
        token_count=10,
    )


def mk_enriched(url: str = "https://ex.com/a") -> EnrichedChunk:
    return EnrichedChunk(
        title="T",
        path="/a/t",
        url=url,
        content="chunk content goes here",
        keywords=["k1", "k2", "k3", "k4", "k5"],
        use_cases=["u1", "u2"],
        tags=["tag"],
        priority=5,
    )


def _cost_stub() -> dict:
    return {
        "total_chunks": 1,
        "total_batches": 1,
        "estimated_input_tokens": 100,
        "estimated_output_tokens": 50,
        "model": "test-model",
        "estimated_cost": 0.0001,
    }


async def test_happy_path_runs_all_five_steps(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "king_context.research.pipeline.TEMP_DOCS_DIR", tmp_path
    )

    output_file = tmp_path / "out.json"

    with patch(
        "king_context.research.pipeline.run_deepening_loop",
        new_callable=AsyncMock,
        return_value=[mk_source("https://ex.com/a")],
    ) as deepen_mock, patch(
        "king_context.research.pipeline.chunk_page",
        return_value=[mk_chunk("https://ex.com/a")],
    ) as chunk_mock, patch(
        "king_context.research.pipeline.estimate_cost",
        return_value=_cost_stub(),
    ) as cost_mock, patch(
        "king_context.research.pipeline.enrich_chunks",
        new_callable=AsyncMock,
        return_value=[mk_enriched("https://ex.com/a")],
    ) as enrich_mock, patch(
        "king_context.research.pipeline.export_research_to_json",
        return_value=output_file,
    ) as export_mock, patch(
        "king_context.research.pipeline.auto_index"
    ) as auto_index_mock:
        result = await run_pipeline(make_args(), make_config())

    assert isinstance(result, Path)
    assert result == output_file

    deepen_mock.assert_awaited_once()
    chunk_mock.assert_called_once()
    cost_mock.assert_called_once()
    enrich_mock.assert_awaited_once()
    export_mock.assert_called_once()
    auto_index_mock.assert_called_once_with(output_file)

    export_args, export_kwargs = export_mock.call_args
    enriched_arg = export_args[0]
    sources_by_url = export_args[1]
    slug = export_args[2]
    topic = export_args[3]
    assert len(enriched_arg) == 1
    assert "https://ex.com/a" in sources_by_url
    assert isinstance(slug, str) and slug
    assert topic == "prompt engineering"


async def test_missing_exa_key_fails_fast(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "king_context.research.pipeline.TEMP_DOCS_DIR", tmp_path
    )

    config = make_config(
        scraper=ScraperConfig(
            openrouter_api_key="or-k", firecrawl_api_key="fc-k"
        ),
        exa_api_key="",
    )

    with patch(
        "king_context.research.pipeline.run_deepening_loop",
        new_callable=AsyncMock,
    ) as deepen_mock, patch(
        "king_context.research.pipeline.enrich_chunks",
        new_callable=AsyncMock,
    ) as enrich_mock, patch(
        "king_context.research.pipeline.export_research_to_json"
    ) as export_mock:
        with pytest.raises(ConfigError, match="EXA_API_KEY"):
            await run_pipeline(make_args(), config)

    deepen_mock.assert_not_called()
    enrich_mock.assert_not_called()
    export_mock.assert_not_called()


async def test_missing_openrouter_key_fails_fast(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "king_context.research.pipeline.TEMP_DOCS_DIR", tmp_path
    )

    config = make_config(
        scraper=ScraperConfig(openrouter_api_key="", firecrawl_api_key="fc-k"),
        exa_api_key="exa-k",
    )

    with patch(
        "king_context.research.pipeline.run_deepening_loop",
        new_callable=AsyncMock,
    ) as deepen_mock:
        with pytest.raises(ConfigError, match="OPENROUTER_API_KEY"):
            await run_pipeline(make_args(), config)

    deepen_mock.assert_not_called()


async def test_zero_sources_raises_user_friendly_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "king_context.research.pipeline.TEMP_DOCS_DIR", tmp_path
    )

    with patch(
        "king_context.research.pipeline.run_deepening_loop",
        new_callable=AsyncMock,
        return_value=[],
    ) as deepen_mock, patch(
        "king_context.research.pipeline.chunk_page"
    ) as chunk_mock, patch(
        "king_context.research.pipeline.enrich_chunks",
        new_callable=AsyncMock,
    ) as enrich_mock, patch(
        "king_context.research.pipeline.export_research_to_json"
    ) as export_mock:
        with pytest.raises(RuntimeError, match="No sources"):
            await run_pipeline(make_args(), make_config())

    deepen_mock.assert_awaited_once()
    chunk_mock.assert_not_called()
    enrich_mock.assert_not_called()
    export_mock.assert_not_called()


async def test_existing_work_dir_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "king_context.research.pipeline.TEMP_DOCS_DIR", tmp_path
    )

    slug = "prompt-engineering"
    pre_existing = tmp_path / "research" / slug
    pre_existing.mkdir(parents=True, exist_ok=True)
    (pre_existing / "manifest.json").write_text('{"existing": {"status": "done"}}')
    (pre_existing / "scratch.txt").write_text("previous run artifact")

    output_file = tmp_path / "out.json"

    with patch(
        "king_context.research.pipeline.run_deepening_loop",
        new_callable=AsyncMock,
        return_value=[mk_source("https://ex.com/a")],
    ), patch(
        "king_context.research.pipeline.chunk_page",
        return_value=[mk_chunk("https://ex.com/a")],
    ), patch(
        "king_context.research.pipeline.estimate_cost",
        return_value=_cost_stub(),
    ), patch(
        "king_context.research.pipeline.enrich_chunks",
        new_callable=AsyncMock,
        return_value=[mk_enriched("https://ex.com/a")],
    ), patch(
        "king_context.research.pipeline.export_research_to_json",
        return_value=output_file,
    ), patch(
        "king_context.research.pipeline.auto_index"
    ):
        result = await run_pipeline(
            make_args(name=slug), make_config()
        )

    assert result == output_file
    assert pre_existing.exists()
    assert (pre_existing / "scratch.txt").exists()

    import json as _json
    manifest = _json.loads((pre_existing / "manifest.json").read_text())
    assert "existing" in manifest
    assert manifest.get("generate", {}).get("status") == "done"
    assert manifest.get("search", {}).get("status") == "done"
    assert manifest.get("export", {}).get("status") == "done"


async def test_stop_after_search_does_not_run_later_steps(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "king_context.research.pipeline.TEMP_DOCS_DIR", tmp_path
    )

    with patch(
        "king_context.research.pipeline.run_deepening_loop",
        new_callable=AsyncMock,
        return_value=[mk_source("https://ex.com/a")],
    ) as deepen_mock, patch(
        "king_context.research.pipeline.chunk_page"
    ) as chunk_mock, patch(
        "king_context.research.pipeline.enrich_chunks",
        new_callable=AsyncMock,
    ) as enrich_mock, patch(
        "king_context.research.pipeline.export_research_to_json"
    ) as export_mock:
        result = await run_pipeline(
            make_args(stop_after="search"), make_config()
        )

    assert isinstance(result, Path)
    deepen_mock.assert_awaited_once()
    chunk_mock.assert_not_called()
    enrich_mock.assert_not_called()
    export_mock.assert_not_called()


async def test_no_auto_index_flag_skips_indexing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "king_context.research.pipeline.TEMP_DOCS_DIR", tmp_path
    )
    output_file = tmp_path / "out.json"

    with patch(
        "king_context.research.pipeline.run_deepening_loop",
        new_callable=AsyncMock,
        return_value=[mk_source("https://ex.com/a")],
    ), patch(
        "king_context.research.pipeline.chunk_page",
        return_value=[mk_chunk("https://ex.com/a")],
    ), patch(
        "king_context.research.pipeline.estimate_cost",
        return_value=_cost_stub(),
    ), patch(
        "king_context.research.pipeline.enrich_chunks",
        new_callable=AsyncMock,
        return_value=[mk_enriched("https://ex.com/a")],
    ), patch(
        "king_context.research.pipeline.export_research_to_json",
        return_value=output_file,
    ), patch(
        "king_context.research.pipeline.auto_index"
    ) as auto_index_mock:
        await run_pipeline(
            make_args(no_auto_index=True), make_config()
        )

    auto_index_mock.assert_not_called()
