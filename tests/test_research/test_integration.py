"""End-to-end integration test for the research pipeline.

All externals (Exa SDK, Jina httpx, OpenRouter httpx) are mocked. The pipeline,
chunk, enrich, export, and indexing code paths run for real so we exercise the
wiring between components.
"""
from __future__ import annotations

import json
from argparse import Namespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

import respx

from king_context.research.config import EffortLevel, ResearchConfig
from king_context.research.pipeline import run_pipeline
from king_context.scraper.config import ScraperConfig
from context_cli.indexer import index_doc


skip_no_respx = pytest.mark.skipif(False, reason="")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Content crafted to produce at least 3 chunks per page.
# chunk_page splits on h2/h3 boundaries — we emit 4 sections per page,
# each with enough text (~400+ chars) to sit comfortably above the 100-token
# minimum and under the 1000-token maximum (merged section stays ~150 tokens).
_SECTION_TEXT_SUFFIX = " ".join(["word"] * 80)


def _build_page_markdown(query: str) -> str:
    return (
        f"# {query}\n\n"
        f"Intro paragraph about {query}. {_SECTION_TEXT_SUFFIX}.\n\n"
        f"## Overview of {query}\n\n"
        f"This section introduces {query}. {_SECTION_TEXT_SUFFIX}.\n\n"
        f"## Implementation details\n\n"
        f"Implementation details relevant to {query}. {_SECTION_TEXT_SUFFIX}.\n\n"
        f"## Best practices\n\n"
        f"Best practices around {query}. {_SECTION_TEXT_SUFFIX}.\n\n"
        f"## Common pitfalls\n\n"
        f"Common pitfalls encountered with {query}. {_SECTION_TEXT_SUFFIX}.\n"
    )


def _make_exa_result(url: str, query: str, index: int) -> MagicMock:
    r = MagicMock()
    r.url = url
    r.title = f"{query} article {index}"
    r.text = _build_page_markdown(query)
    r.highlights = [f"highlight about {query}"]
    r.author = "Alice Author" if index == 0 else None
    r.published_date = "2024-01-01" if index == 0 else None
    r.score = 0.9 - index * 0.1
    return r


def _make_exa_response(query: str, num_results: int) -> MagicMock:
    results = []
    # A predictable URL per (query, index) pair — slugified so dedup works.
    safe_q = query.replace(" ", "-")
    for i in range(num_results):
        url = f"https://example.com/{safe_q}/{i}"
        results.append(_make_exa_result(url, query, i))
    resp = MagicMock()
    resp.results = results
    return resp


def _make_enrichment_response() -> httpx.Response:
    payload = {
        "keywords": ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"],
        "use_cases": ["Use when testing", "Implement when integrating"],
        "tags": ["research"],
        "priority": 7,
    }
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": json.dumps(payload)}}]
        },
    )


def _make_queries_response(queries: list[str]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"content": json.dumps({"queries": queries})}}
            ]
        },
    )


def _is_enrichment_request(body: dict) -> bool:
    """Enrichment uses a single user message; queries uses system+user.
    Detect by looking for the enrichment prompt's distinctive preamble.
    """
    messages = body.get("messages", [])
    # Enrichment payload is one user message with the ENRICHMENT_PROMPT text.
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str) and (
            "documentation metadata specialist" in content
            or "Documentation section:" in content
        ):
            return True
    return False


def _make_config(**overrides) -> ResearchConfig:
    scraper = ScraperConfig(
        openrouter_api_key="or-test",
        firecrawl_api_key="fc-test",
        concurrency=3,
        enrichment_model="test-model",
        enrichment_batch_size=5,
    )
    defaults = dict(
        scraper=scraper,
        exa_api_key="exa-test",
        exa_results_per_query=3,
        basic_queries=3,
        medium_queries=5,
        medium_iterations=1,
        medium_followups=3,
    )
    defaults.update(overrides)
    return ResearchConfig(**defaults)


def _make_args(
    effort: EffortLevel = EffortLevel.BASIC,
    topic: str = "prompt engineering",
    name: str | None = None,
) -> Namespace:
    return Namespace(
        topic=topic,
        effort=effort,
        name=name,
        step=None,
        stop_after=None,
        no_filter=False,
        yes=True,
        no_auto_index=True,
        force=False,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@skip_no_respx
@respx.mock
async def test_basic_effort_end_to_end(tmp_path, monkeypatch):
    """Happy path: BASIC effort with all externals mocked.

    Asserts the exported JSON is well-formed, has the research-specific
    metadata fields, and that the downstream indexer + searcher work on it.
    """
    monkeypatch.setattr(
        "king_context.research.pipeline.TEMP_DOCS_DIR", tmp_path / "_temp"
    )
    monkeypatch.setattr(
        "king_context.research.export.RESEARCH_DATA_DIR",
        tmp_path / "data" / "research",
    )

    # ---- Mock OpenRouter ----
    def openrouter_handler(request):
        body = json.loads(request.content)
        if _is_enrichment_request(body):
            return _make_enrichment_response()
        return _make_queries_response(["query a", "query b", "query c"])

    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        side_effect=openrouter_handler
    )

    # ---- Mock Exa ----
    def fake_search_and_contents(**kwargs):
        return _make_exa_response(kwargs["query"], num_results=3)

    with patch("king_context.research.exa.Exa") as mock_exa_cls:
        mock_exa_cls.return_value.search_and_contents.side_effect = (
            fake_search_and_contents
        )

        output_path = await run_pipeline(
            _make_args(
                effort=EffortLevel.BASIC,
                topic="prompt engineering",
                name="prompt-engineering",
            ),
            _make_config(),
        )

    # ---- Assertions on the exported JSON ----
    assert output_path.exists(), f"Expected output JSON at {output_path}"
    assert output_path.parent == tmp_path / "data" / "research"
    assert output_path.name == "prompt-engineering.json"

    data = json.loads(output_path.read_text())
    sections = data["sections"]
    assert len(sections) >= 3, f"Expected >= 3 sections, got {len(sections)}"

    for sec in sections:
        assert sec["source_type"] == "research"
        assert "domain" in sec
        assert "discovery_iteration" in sec

    # At least one section from URL index 0 should have authors ("Alice Author").
    assert any(
        s.get("authors") == ["Alice Author"] for s in sections
    ), "expected at least one section with authors populated"

    # ---- Index downstream ----
    store_dir = tmp_path / "docs"
    store_dir.mkdir()
    result = index_doc(output_path, store_dir)

    assert result.doc_name == "prompt-engineering"
    sections_dir = store_dir / result.doc_name / "sections"
    assert sections_dir.exists()
    assert any(sections_dir.iterdir()), "sections directory is empty"

    # ---- Search via context_cli.searcher ----
    from context_cli.searcher import search as kctx_search

    # Use a keyword we know the enricher assigned ("alpha").
    hits = kctx_search("alpha", store_dir)
    assert len(hits) >= 1, "expected at least one search hit for 'alpha'"
    assert any(h.doc_name == "prompt-engineering" for h in hits)


@skip_no_respx
@respx.mock
async def test_medium_effort_iteration_sources_present(tmp_path, monkeypatch):
    """MEDIUM effort: verify the deepening loop ran by checking for sections
    from both iteration 0 and iteration 1.
    """
    monkeypatch.setattr(
        "king_context.research.pipeline.TEMP_DOCS_DIR", tmp_path / "_temp"
    )
    monkeypatch.setattr(
        "king_context.research.export.RESEARCH_DATA_DIR",
        tmp_path / "data" / "research",
    )

    call_count = [0]

    def openrouter_handler(request):
        body = json.loads(request.content)
        if _is_enrichment_request(body):
            return _make_enrichment_response()

        call_count[0] += 1
        if call_count[0] == 1:
            qs = ["init a", "init b", "init c", "init d", "init e"]
        else:
            qs = ["followup a", "followup b", "followup c"]
        return _make_queries_response(qs)

    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        side_effect=openrouter_handler
    )

    def fake_search_and_contents(**kwargs):
        # Two results per query for a tighter medium run.
        return _make_exa_response(kwargs["query"], num_results=2)

    with patch("king_context.research.exa.Exa") as mock_exa_cls:
        mock_exa_cls.return_value.search_and_contents.side_effect = (
            fake_search_and_contents
        )

        output_path = await run_pipeline(
            _make_args(
                effort=EffortLevel.MEDIUM,
                topic="cache hierarchies",
                name="cache-hierarchies",
            ),
            _make_config(
                exa_results_per_query=2,
                medium_queries=5,
                medium_iterations=1,
                medium_followups=3,
            ),
        )

    assert output_path.exists()
    data = json.loads(output_path.read_text())
    sections = data["sections"]

    iterations = {s.get("discovery_iteration") for s in sections}
    assert 0 in iterations, (
        f"expected a section from iteration 0; got iterations={iterations}"
    )
    assert 1 in iterations, (
        f"expected a section from iteration 1 (deepening loop ran); "
        f"got iterations={iterations}"
    )
