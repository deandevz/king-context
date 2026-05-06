"""Tests for unified search, home page, and the canonical empty-state shape."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from context_cli import adr
from king_context.web import handlers, router
from king_context.web.render import default_hint, empty_state


# ---------------------------------------------------------------------------
# Fixtures: mirror the patterns in test_web_handlers / test_web_corpus
# ---------------------------------------------------------------------------


def _patch_project(tmp_path: Path, monkeypatch) -> Path:
    import context_cli.cli as cli_mod

    monkeypatch.setattr(cli_mod, "PROJECT_ROOT", tmp_path)
    return tmp_path / ".king-context"


def _write_index(corpus_dir: Path, *, name: str, **overrides) -> None:
    payload = {
        "name": name,
        "display_name": overrides.get("display_name", name.title()),
        "version": overrides.get("version", "v1"),
        "base_url": overrides.get("base_url", f"https://example.test/{name}"),
        "section_count": overrides.get("section_count", 0),
        "indexed_at": "2026-05-06T00:00:00+00:00",
    }
    corpus_dir.mkdir(parents=True, exist_ok=True)
    (corpus_dir / "index.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_section(
    corpus_dir: Path,
    *,
    path: str,
    title: str,
    content: str = "Body.",
    keywords=None,
    use_cases=None,
    tags=None,
    priority: int = 5,
) -> None:
    sections_dir = corpus_dir / "sections"
    sections_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "title": title,
        "path": path,
        "url": f"https://example.test/{path}",
        "keywords": keywords or [],
        "use_cases": use_cases or [],
        "tags": tags or [],
        "priority": priority,
        "content": content,
    }
    (sections_dir / f"{path}.json").write_text(json.dumps(data), encoding="utf-8")


def _write_reverse_index(
    corpus_dir: Path,
    name: str,
    mapping: dict[str, list[str]],
) -> None:
    (corpus_dir / f"{name}.json").write_text(
        json.dumps(mapping), encoding="utf-8"
    )


def _write_adr(adr_dir: Path, *, adr_id="ADR-0001", title="MCP integration",
               keywords=None, areas=None) -> None:
    keywords = keywords or ["mcp", "integration"]
    areas = areas or ["server"]
    content = adr.render_adr_markdown(
        adr_id=adr_id,
        title=title,
        status="accepted",
        adr_date="2026-05-02",
        areas=areas,
        supersedes=[],
        superseded_by=[],
        related=[],
        supersession_reason="",
        keywords=keywords,
        tags=["arch"],
        context="Reason for the change.",
        decision="Adopt the proposal.",
        alternatives="None significant.",
        consequences="Documented here.",
    )
    adr_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{adr_id.split('-')[1]}-{title.lower().replace(' ', '-')}.md"
    (adr_dir / filename).write_text(content)


@pytest.fixture
def empty_repo(tmp_path, monkeypatch):
    _patch_project(tmp_path, monkeypatch)
    return tmp_path


@pytest.fixture
def populated_repo(tmp_path, monkeypatch):
    """A project with one ADR mentioning `mcp` plus a docs and a research corpus
    that both index sections matching `mcp` via keywords/tags."""
    base = _patch_project(tmp_path, monkeypatch)

    # Docs corpus: section "intro" with keyword "mcp".
    docs = base / "docs" / "guide"
    _write_index(docs, name="guide", section_count=2)
    _write_section(
        docs,
        path="intro",
        title="MCP intro",
        keywords=["mcp"],
        tags=["protocol"],
        priority=8,
    )
    _write_section(
        docs,
        path="cli",
        title="CLI usage",
        keywords=["cli"],
        tags=["tool"],
        priority=4,
    )
    _write_reverse_index(docs, "keywords", {"mcp": ["intro"], "cli": ["cli"]})
    _write_reverse_index(docs, "use_cases", {})
    _write_reverse_index(docs, "tags", {"protocol": ["intro"], "tool": ["cli"]})

    # Research corpus: section "alpha" with tag "mcp".
    research = base / "research" / "papers"
    _write_index(research, name="papers", section_count=1)
    _write_section(
        research,
        path="alpha",
        title="MCP literature review",
        keywords=["mcp"],
        tags=["mcp"],
        priority=6,
    )
    _write_reverse_index(research, "keywords", {"mcp": ["alpha"]})
    _write_reverse_index(research, "use_cases", {})
    _write_reverse_index(research, "tags", {"mcp": ["alpha"]})

    # ADRs.
    adr_dir = base / "adr"
    _write_adr(adr_dir, adr_id="ADR-0001", title="MCP integration")
    _write_adr(
        adr_dir,
        adr_id="ADR-0002",
        title="Other unrelated",
        keywords=["other"],
        areas=["misc"],
    )
    adr.rebuild_index()
    return base


# ---------------------------------------------------------------------------
# render: empty_state + default_hint
# ---------------------------------------------------------------------------


class TestEmptyStateHelper:
    def test_empty_state_shape(self):
        result = empty_state("dir_missing", "hint text")
        assert result == {
            "items": [],
            "reason": "dir_missing",
            "hint": "hint text",
        }

    def test_empty_state_with_extra_fields(self):
        result = empty_state(
            "not_indexed",
            "hint",
            extra_fields={"results": [], "scoring": {"k": 1.0}},
        )
        assert result["items"] == []
        assert result["reason"] == "not_indexed"
        assert result["hint"] == "hint"
        assert result["results"] == []
        assert result["scoring"] == {"k": 1.0}


class TestDefaultHint:
    @pytest.mark.parametrize(
        "source,reason,expected_substring",
        [
            ("adrs", "dir_missing", "kctx adr index"),
            ("adrs", "not_indexed", "kctx adr new"),
            ("adrs", "parse_error", "kctx adr validate"),
            ("docs", "dir_missing", "@king-context/cli init"),
            ("docs", "not_indexed", "kctx index"),
            ("docs", "parse_error", "Re-run"),
            ("research", "dir_missing", "@king-context/cli init"),
            ("research", "not_indexed", "king-research"),
            ("research", "parse_error", "Re-run"),
        ],
    )
    def test_known_combinations(self, source, reason, expected_substring):
        hint = default_hint(source, reason)
        assert expected_substring in hint

    def test_unknown_combination_returns_empty(self):
        assert default_hint("unknown", "dir_missing") == ""
        assert default_hint("docs", "weird") == ""


# ---------------------------------------------------------------------------
# search_unified
# ---------------------------------------------------------------------------


class TestSearchUnified:
    def test_combines_sources(self, populated_repo):
        status, body = handlers.search_unified(
            "/api/search", {"q": ["mcp"], "source": ["all"]}
        )
        assert status == 200
        sources = {r["source"] for r in body["results"]}
        assert sources == {"adrs", "docs", "research"}
        assert "scoring" in body
        for key in ("keyword_weight", "use_case_weight",
                    "tag_weight", "priority_multiplier"):
            assert key in body["scoring"]

    def test_filters_by_source_docs_only(self, populated_repo):
        _, body = handlers.search_unified(
            "/api/search", {"q": ["mcp"], "source": ["docs"]}
        )
        assert body["results"]
        assert {r["source"] for r in body["results"]} == {"docs"}

    def test_filters_by_source_adrs_only(self, populated_repo):
        _, body = handlers.search_unified(
            "/api/search", {"q": ["mcp"], "source": ["adrs"]}
        )
        assert body["results"]
        assert {r["source"] for r in body["results"]} == {"adrs"}
        # ADR remap shape.
        first = body["results"][0]
        assert first["doc_name"] == "project"
        assert first["section_path"] == "adr-0001"
        assert first["priority"] == 10
        assert first["matched_keywords"] == []
        assert first["matched_use_cases"] == []
        assert isinstance(first["matched_tags"], list)

    def test_empty_query_returns_zero_results_no_error(self, empty_repo):
        status, body = handlers.search_unified(
            "/api/search", {"q": [""], "source": ["all"]}
        )
        assert status == 200
        assert body == {"results": [], "scoring": handlers.SEARCH_SCORING}

    def test_missing_q_returns_zero_results(self, empty_repo):
        status, body = handlers.search_unified(
            "/api/search", {"source": ["all"]}
        )
        assert status == 200
        assert body["results"] == []

    def test_invalid_source_returns_400(self, empty_repo):
        status, body = handlers.search_unified(
            "/api/search", {"q": ["x"], "source": ["foo"]}
        )
        assert status == 400
        assert body == {"error": "invalid_source"}

    def test_special_chars_dont_break(self, populated_repo):
        for q in ("'; DROP TABLE", ".*+?[](){}|", "__init__"):
            status, body = handlers.search_unified(
                "/api/search", {"q": [q], "source": ["all"]}
            )
            assert status == 200
            assert "results" in body

    def test_orders_by_score_desc(self, populated_repo):
        _, body = handlers.search_unified(
            "/api/search", {"q": ["mcp"], "source": ["all"]}
        )
        scores = [r["score"] for r in body["results"]]
        assert scores == sorted(scores, reverse=True)

    def test_respects_top_param(self, populated_repo):
        _, body = handlers.search_unified(
            "/api/search", {"q": ["mcp"], "source": ["all"], "top": ["1"]}
        )
        assert len(body["results"]) == 1

    def test_top_zero_returns_empty(self, populated_repo):
        _, body = handlers.search_unified(
            "/api/search", {"q": ["mcp"], "source": ["all"], "top": ["0"]}
        )
        assert body["results"] == []

    def test_top_clamped_to_max(self, populated_repo):
        _, body = handlers.search_unified(
            "/api/search", {"q": ["mcp"], "source": ["all"], "top": ["1000"]}
        )
        # Real corpus only has 3 hits, so just confirm no crash.
        assert len(body["results"]) <= 50

    def test_negative_top_returns_empty(self, populated_repo):
        _, body = handlers.search_unified(
            "/api/search", {"q": ["mcp"], "source": ["all"], "top": ["-5"]}
        )
        assert body["results"] == []

    def test_whitespace_only_query_treated_as_empty(self, empty_repo):
        status, body = handlers.search_unified(
            "/api/search", {"q": ["   "], "source": ["all"]}
        )
        assert status == 200
        assert body["results"] == []

    def test_long_query_does_not_crash(self, populated_repo):
        q = "a" * 500
        status, _ = handlers.search_unified(
            "/api/search", {"q": [q], "source": ["all"]}
        )
        assert status == 200

    def test_unicode_query_does_not_raise(self, populated_repo):
        status, _ = handlers.search_unified(
            "/api/search", {"q": ["你好"], "source": ["all"]}
        )
        assert status == 200


class TestAdrRemap:
    def test_remap_shape(self, populated_repo):
        # Direct call into the search engine to get an AdrSearchResult, then
        # confirm the handler-level remap matches the SearchResult contract.
        adr_hits = adr.search_decisions("mcp", active_only=False, top=5)
        assert adr_hits, "expected at least one ADR matching `mcp`"
        remapped = handlers._adr_to_search_result(adr_hits[0])
        assert remapped["source"] == "adrs"
        assert remapped["doc_name"] == "project"
        assert remapped["section_path"].startswith("adr-")
        assert remapped["section_path"] == remapped["section_path"].lower()
        assert remapped["priority"] == 10
        assert remapped["matched_keywords"] == []
        assert remapped["matched_use_cases"] == []
        assert isinstance(remapped["matched_tags"], list)
        assert isinstance(remapped["score"], float)


# ---------------------------------------------------------------------------
# search_page (HTML)
# ---------------------------------------------------------------------------


class TestSearchPage:
    def test_renders_results(self, populated_repo):
        status, body = handlers.search_page(
            "/search", {"q": ["mcp"], "source": ["all"]}
        )
        assert status == 200
        text = body.decode("utf-8")
        assert "<title>Search - King Context</title>" in text
        assert "MCP intro" in text or "MCP literature review" in text
        # Source filter dropdown rendered.
        assert 'name="source"' in text

    def test_empty_query_renders_form_only(self, empty_repo):
        status, body = handlers.search_page("/search", {})
        assert status == 200
        text = body.decode("utf-8")
        assert 'name="q"' in text
        # No "results" wrapper rendered for empty q.
        assert "Enter a query" in text

    def test_invalid_source_rendered_in_html(self, populated_repo):
        status, body = handlers.search_page(
            "/search", {"q": ["mcp"], "source": ["foo"]}
        )
        assert status == 200
        assert b"Invalid" in body


# ---------------------------------------------------------------------------
# home_page (HTML)
# ---------------------------------------------------------------------------


class TestHomePage:
    def test_shows_counts(self, populated_repo):
        status, body = handlers.home_page("/", {})
        assert status == 200
        assert isinstance(body, bytes)
        text = body.decode("utf-8")
        assert "<title>King Context</title>" in text
        # Three card headings.
        for label in ("ADRs", "Docs", "Research"):
            assert f">{label}<" in text
        # ADR count = 2, docs corpora = 1, research corpora = 1.
        assert ">2<" in text
        assert ">1<" in text

    def test_shows_hints_when_empty(self, empty_repo):
        status, body = handlers.home_page("/", {})
        assert status == 200
        text = body.decode("utf-8")
        # Each source surfaces a hint instead of a count.
        assert "kctx adr index" in text
        assert "@king-context/cli init" in text

    def test_includes_global_search_form(self, empty_repo):
        _, body = handlers.home_page("/", {})
        text = body.decode("utf-8")
        assert 'action="/search"' in text
        assert 'name="q"' in text


# ---------------------------------------------------------------------------
# Router integration: /, /search, /api/search
# ---------------------------------------------------------------------------


class TestRouterRoutes:
    def test_root_returns_html(self, populated_repo):
        status, headers, body = router.dispatch("GET", "/", {})
        assert status == 200
        assert headers["Content-Type"] == "text/html; charset=utf-8"
        assert b"<title>King Context</title>" in body

    def test_search_html_route(self, populated_repo):
        status, headers, body = router.dispatch(
            "GET", "/search", {"q": ["mcp"]}
        )
        assert status == 200
        assert headers["Content-Type"] == "text/html; charset=utf-8"

    def test_api_search_returns_json(self, populated_repo):
        status, headers, body = router.dispatch(
            "GET", "/api/search", {"q": ["mcp"], "source": ["all"]}
        )
        assert status == 200
        assert "application/json" in headers["Content-Type"]
        payload = json.loads(body)
        assert "results" in payload
        assert "scoring" in payload

    def test_api_search_invalid_source_returns_400(self, empty_repo):
        status, _, body = router.dispatch(
            "GET", "/api/search", {"q": ["x"], "source": ["foo"]}
        )
        assert status == 400
        payload = json.loads(body)
        assert payload == {"error": "invalid_source"}

    def test_api_search_empty_query_status_200(self, empty_repo):
        status, _, body = router.dispatch(
            "GET", "/api/search", {"q": [""]}
        )
        assert status == 200
        payload = json.loads(body)
        assert payload["results"] == []


# ---------------------------------------------------------------------------
# EmptyState shape consistency across endpoints
# ---------------------------------------------------------------------------


class TestEmptyStateConsistency:
    def test_shape_identical_across_endpoints(self, empty_repo):
        endpoints = [
            ("/api/adrs", {}),
            ("/api/docs", {}),
            ("/api/research", {}),
        ]
        seen_keys: list[set[str]] = []
        for path, query in endpoints:
            _, _, body = router.dispatch("GET", path, query)
            payload = json.loads(body)
            assert payload["items"] == []
            assert "reason" in payload
            assert "hint" in payload
            seen_keys.append(set(payload.keys()))
        # All three endpoints expose exactly the same envelope keys.
        assert seen_keys[0] == seen_keys[1] == seen_keys[2]
