"""Tests for king_context.web.handlers (ADR endpoints)."""

from __future__ import annotations

import json

import pytest

from context_cli import adr
from king_context.web import handlers, router


def _patch_project(tmp_path, monkeypatch):
    """Redirect ADR / decisions paths at the `_project_root()` indirection.

    `context_cli.adr._project_root()` reads `cli_mod.PROJECT_ROOT`. The
    handler module imports `_adr_dir` and `_decisions_dir`, which both
    funnel through that indirection, so a single monkeypatch covers all
    paths used by the handler suite.
    """
    import context_cli.cli as cli_mod

    monkeypatch.setattr(cli_mod, "PROJECT_ROOT", tmp_path)
    return tmp_path / ".king-context" / "adr", tmp_path / ".king-context" / "decisions" / "project"


def _write_adr(
    adr_dir,
    *,
    adr_id="ADR-0001",
    title="First decision",
    status="accepted",
    adr_date="2026-05-02",
    areas=None,
    related=None,
    supersedes=None,
    superseded_by=None,
    supersession_reason="",
    keywords=None,
    tags=None,
):
    areas = areas or ["cli"]
    related = related or []
    supersedes = supersedes or []
    superseded_by = superseded_by or []
    keywords = keywords or ["test"]
    tags = tags or ["arch"]
    content = adr.render_adr_markdown(
        adr_id=adr_id,
        title=title,
        status=status,
        adr_date=adr_date,
        areas=areas,
        supersedes=supersedes,
        superseded_by=superseded_by,
        related=related,
        supersession_reason=supersession_reason,
        keywords=keywords,
        tags=tags,
        context="The team needed a decision.",
        decision="Adopt the proposed approach.",
        alternatives="Alternative options were considered.",
        consequences="Consequences are documented here.",
    )
    adr_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{adr_id.split('-')[1]}-{title.lower().replace(' ', '-')}.md"
    path = adr_dir / filename
    path.write_text(content)
    return path


@pytest.fixture
def populated_repo(tmp_path, monkeypatch):
    """Create three ADRs and rebuild the index. Returns (adr_dir, decisions_dir)."""
    adr_dir, decisions_dir = _patch_project(tmp_path, monkeypatch)

    _write_adr(adr_dir, adr_id="ADR-0001", title="First decision",
               related=["ADR-0002"])
    _write_adr(adr_dir, adr_id="ADR-0002", title="Second decision",
               related=["ADR-0001"])
    _write_adr(adr_dir, adr_id="ADR-0003", title="Third decision",
               status="proposed", areas=["docs"])

    # Make ADR-0001 reference a non-existent ADR for the broken-link test.
    # rebuild_index uses the .md files, so we re-write ADR-0001 with the
    # broken ref. We need to disable the validation that linked IDs exist:
    # rebuild_index does NOT enforce that, only the `new` flow does. So
    # writing a stale broken ref by editing the source file works.
    md_path = adr_dir / "0001-first-decision.md"
    text = md_path.read_text()
    text = text.replace(
        "related:\n  - ADR-0002\n",
        "related:\n  - ADR-0002\n  - ADR-0099\n",
    )
    md_path.write_text(text)

    adr.rebuild_index()
    return adr_dir, decisions_dir


@pytest.fixture
def empty_repo(tmp_path, monkeypatch):
    """Patch project root to a fresh dir with NO .king-context."""
    _patch_project(tmp_path, monkeypatch)
    return tmp_path


@pytest.fixture
def adrs_no_index(tmp_path, monkeypatch):
    """ADR markdown exists but the decisions index has not been built."""
    adr_dir, decisions_dir = _patch_project(tmp_path, monkeypatch)
    _write_adr(adr_dir, adr_id="ADR-0001", title="First decision")
    return adr_dir, decisions_dir


# ---------------------------------------------------------------------------
# adr_list
# ---------------------------------------------------------------------------


class TestAdrList:
    def test_returns_items_with_counts(self, populated_repo):
        status, body = handlers.adr_list("/api/adrs", {})
        assert status == 200
        assert "items" in body
        items = body["items"]
        assert len(items) == 3
        first = next(item for item in items if item["id"] == "ADR-0001")
        assert first["title"] == "First decision"
        assert first["status"] == "accepted"
        assert first["date"] == "2026-05-02"
        # Two related links: ADR-0002 (real) + ADR-0099 (broken).
        assert first["related_count"] == 2
        assert first["supersedes_count"] == 0
        assert first["superseded_by_count"] == 0

    def test_dir_missing_when_no_decisions_dir(self, empty_repo):
        status, body = handlers.adr_list("/api/adrs", {})
        assert status == 200
        assert body["items"] == []
        assert body["reason"] == "dir_missing"
        assert "kctx adr index" in body["hint"]

    def test_not_indexed_when_decisions_dir_empty(self, adrs_no_index):
        # decisions dir does not exist yet (ADR markdown only).
        status, body = handlers.adr_list("/api/adrs", {})
        assert body["reason"] == "dir_missing"

        # Now create an empty decisions/project/ to simulate the
        # "exists but no sections" case.
        _, decisions_dir = adrs_no_index
        decisions_dir.mkdir(parents=True, exist_ok=True)
        status, body = handlers.adr_list("/api/adrs", {})
        assert status == 200
        assert body["reason"] == "not_indexed"


# ---------------------------------------------------------------------------
# adr_detail
# ---------------------------------------------------------------------------


class TestAdrDetail:
    def test_returns_full_adr(self, populated_repo):
        status, body = handlers.adr_detail("/api/adrs/ADR-0001", {}, id="ADR-0001")
        assert status == 200
        assert "adr" in body
        assert body["adr"]["id"] == "ADR-0001"
        assert body["adr"]["title"] == "First decision"
        # Frontmatter must be stripped from content_html.
        assert "<h2>Context</h2>" in body["adr"]["content_html"]
        # Frontmatter (`id: ADR-0001`) should not leak into the rendered HTML.
        assert "id: ADR-0001" not in body["adr"]["content_html"]
        assert "neighborhood" in body
        assert "related" in body["neighborhood"]

    def test_unknown_id_returns_dir_missing(self, populated_repo):
        status, body = handlers.adr_detail(
            "/api/adrs/ADR-9999", {}, id="ADR-9999"
        )
        assert status == 200
        assert body["items"] == []
        assert body["reason"] == "dir_missing"

    def test_invalid_id_format_returns_dir_missing(self, populated_repo):
        # `_normalize_id` rejects non ADR-NNNN values; handler must not crash.
        status, body = handlers.adr_detail(
            "/api/adrs/not-an-id", {}, id="not-an-id"
        )
        assert status == 200
        assert body["reason"] == "dir_missing"

    def test_invalid_frontmatter_returns_parse_error(
        self, populated_repo, monkeypatch
    ):
        adr_dir, _ = populated_repo
        # Plant a file that matches the ADR-0099 number prefix but has
        # broken frontmatter: opens with --- but is not closed correctly.
        broken_path = adr_dir / "0099-broken.md"
        broken_path.write_text(
            "---\nid: ADR-0099\ntitle: Broken\nbut no closing\n"
            "## Context\nbody\n"
        )
        status, body = handlers.adr_detail(
            "/api/adrs/ADR-0099", {}, id="ADR-0099"
        )
        assert status == 200
        assert body["reason"] == "parse_error"
        # Other ADRs remain accessible.
        status_ok, body_ok = handlers.adr_detail(
            "/api/adrs/ADR-0001", {}, id="ADR-0001"
        )
        assert "adr" in body_ok

    def test_broken_neighborhood_ref(self, populated_repo):
        status, body = handlers.adr_detail(
            "/api/adrs/ADR-0001", {}, id="ADR-0001"
        )
        related = body["neighborhood"]["related"]
        broken = [r for r in related if r["broken"]]
        assert any(r["id"] == "ADR-0099" for r in broken)

    def test_resolves_when_md_missing_via_indexed_fallback(
        self, populated_repo
    ):
        adr_dir, _ = populated_repo
        # Remove the .md file: the indexed sections JSON should still serve.
        (adr_dir / "0002-second-decision.md").unlink()
        status, body = handlers.adr_detail(
            "/api/adrs/ADR-0002", {}, id="ADR-0002"
        )
        assert status == 200
        assert body["adr"]["id"] == "ADR-0002"


# ---------------------------------------------------------------------------
# adr_graph
# ---------------------------------------------------------------------------


class TestAdrGraph:
    def test_passthrough(self, populated_repo):
        status, body = handlers.adr_graph("/api/adrs/graph", {})
        assert status == 200
        assert "nodes" in body
        assert "edges" in body
        node_ids = [n["id"] for n in body["nodes"]]
        assert "ADR-0001" in node_ids

    def test_missing_returns_empty_state(self, empty_repo):
        status, body = handlers.adr_graph("/api/adrs/graph", {})
        assert status == 200
        assert body["reason"] == "not_indexed"
        assert "graph" in body["hint"].lower()


# ---------------------------------------------------------------------------
# HTML pages
# ---------------------------------------------------------------------------


class TestAdrPages:
    def test_list_page_renders_layout(self, populated_repo):
        status, body = handlers.adr_page("/adrs", {})
        assert status == 200
        assert isinstance(body, bytes)
        text = body.decode("utf-8")
        assert "<svg id=\"adr-graph\"" in text
        assert "<title>ADRs - King Context</title>" in text
        assert "ADR-0001" in text

    def test_detail_page_includes_title(self, populated_repo):
        status, body = handlers.adr_detail_page(
            "/adrs/ADR-0001", {}, id="ADR-0001"
        )
        assert status == 200
        text = body.decode("utf-8")
        assert "First decision" in text
        # Panel with status visible.
        assert "Status:" in text


# ---------------------------------------------------------------------------
# Router integration: routes registered, dispatch works end to end
# ---------------------------------------------------------------------------


class TestRouterRoutes:
    def test_api_adrs_returns_json(self, populated_repo):
        status, headers, body = router.dispatch("GET", "/api/adrs", {})
        assert status == 200
        assert "application/json" in headers["Content-Type"]
        payload = json.loads(body)
        assert "items" in payload

    def test_api_adrs_graph_routed_before_id(self, populated_repo):
        # `/api/adrs/graph` must hit the graph handler, not `adr_detail`.
        status, _, body = router.dispatch("GET", "/api/adrs/graph", {})
        assert status == 200
        payload = json.loads(body)
        assert "nodes" in payload
        assert "edges" in payload

    def test_api_adrs_id(self, populated_repo):
        status, _, body = router.dispatch("GET", "/api/adrs/ADR-0001", {})
        assert status == 200
        payload = json.loads(body)
        assert payload["adr"]["id"] == "ADR-0001"

    def test_api_adrs_url_encoded_id(self, populated_repo):
        # `%2D` decodes to `-`; the router must decode named segments before
        # passing them to the handler.
        status, _, body = router.dispatch(
            "GET", "/api/adrs/ADR%2D0001", {}
        )
        assert status == 200
        payload = json.loads(body)
        assert payload["adr"]["id"] == "ADR-0001"

    def test_html_page_content_type(self, populated_repo):
        status, headers, body = router.dispatch("GET", "/adrs", {})
        assert status == 200
        assert headers["Content-Type"] == "text/html; charset=utf-8"

    def test_html_detail_page(self, populated_repo):
        status, headers, body = router.dispatch(
            "GET", "/adrs/ADR-0001", {}
        )
        assert status == 200
        assert headers["Content-Type"] == "text/html; charset=utf-8"
        assert b"First decision" in body
