"""Tests for king_context.web.handlers corpus endpoints (docs + research)."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

import pytest

from king_context.web import handlers, router


def _patch_project(tmp_path: Path, monkeypatch) -> Path:
    """Redirect `_project_root` (used by handlers) at the cli indirection."""
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
    content: str = "## Heading\n\nBody text.",
    tags=None,
    priority: int = 5,
    keywords=None,
    use_cases=None,
    url: str = "https://example.test/page",
    extra: dict | None = None,
) -> Path:
    sections_dir = corpus_dir / "sections"
    sections_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "title": title,
        "path": path,
        "url": url,
        "keywords": keywords or [],
        "use_cases": use_cases or [],
        "tags": tags or [],
        "priority": priority,
        "content": content,
    }
    if extra:
        data.update(extra)
    file_path = sections_dir / f"{path}.json"
    file_path.write_text(json.dumps(data), encoding="utf-8")
    return file_path


def _write_tags_index(corpus_dir: Path, mapping: dict[str, list[str]]) -> None:
    (corpus_dir / "tags.json").write_text(
        json.dumps(mapping), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def docs_root(tmp_path, monkeypatch):
    """Empty .king-context with `.king-context/docs/` not present."""
    base = _patch_project(tmp_path, monkeypatch)
    return base


@pytest.fixture
def docs_empty(tmp_path, monkeypatch):
    """`.king-context/docs/` exists but holds no corpora."""
    base = _patch_project(tmp_path, monkeypatch)
    (base / "docs").mkdir(parents=True)
    return base


@pytest.fixture
def docs_populated(tmp_path, monkeypatch):
    """A `sample` docs corpus with three sections, two tags, valid index."""
    base = _patch_project(tmp_path, monkeypatch)
    corpus = base / "docs" / "sample"
    _write_index(corpus, name="sample", section_count=3)
    _write_section(
        corpus,
        path="intro",
        title="Introduction",
        content="# Intro\n\nWelcome to **sample**.",
        tags=["overview"],
        priority=10,
    )
    _write_section(
        corpus,
        path="usage",
        title="Usage",
        content="Use it carefully.",
        tags=["overview", "guide"],
        priority=8,
    )
    _write_section(
        corpus,
        path="extras",
        title="Extras",
        content="Bonus content.",
        tags=[],
        priority=3,
    )
    _write_tags_index(
        corpus,
        {
            "overview": ["intro", "usage"],
            "guide": ["usage"],
        },
    )
    return base


@pytest.fixture
def research_populated(tmp_path, monkeypatch):
    """A `papers` research corpus with research-only metadata fields."""
    base = _patch_project(tmp_path, monkeypatch)
    corpus = base / "research" / "papers"
    _write_index(corpus, name="papers", section_count=1)
    _write_section(
        corpus,
        path="alpha",
        title="Alpha paper",
        content="Original research summary.",
        tags=["primary"],
        priority=7,
        extra={
            "source_type": "research",
            "published_date": "2026-01-15",
            "domain": "openai.com",
        },
    )
    _write_tags_index(corpus, {"primary": ["alpha"]})
    return base


# ---------------------------------------------------------------------------
# corpus_index
# ---------------------------------------------------------------------------


class TestCorpusIndex:
    def test_lists_corpora(self, docs_populated):
        status, body = handlers.corpus_index("docs", "/api/docs", {})
        assert status == 200
        assert "items" in body
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["name"] == "sample"
        assert item["display_name"] == "Sample"
        assert item["version"] == "v1"
        assert item["section_count"] == 3
        assert item["base_url"].startswith("https://")

    def test_dir_missing(self, docs_root):
        status, body = handlers.corpus_index("docs", "/api/docs", {})
        assert status == 200
        assert body["items"] == []
        assert body["reason"] == "dir_missing"
        assert "init" in body["hint"].lower()

    def test_not_indexed_when_empty(self, docs_empty):
        status, body = handlers.corpus_index("docs", "/api/docs", {})
        assert status == 200
        assert body["reason"] == "not_indexed"
        assert "kctx index" in body["hint"]

    def test_research_lists_corpora(self, research_populated):
        status, body = handlers.corpus_index("research", "/api/research", {})
        assert status == 200
        assert body["items"][0]["name"] == "papers"

    def test_research_dir_missing(self, docs_root):
        status, body = handlers.corpus_index(
            "research", "/api/research", {}
        )
        assert body["reason"] == "dir_missing"


# ---------------------------------------------------------------------------
# section_list
# ---------------------------------------------------------------------------


class TestSectionList:
    def test_orders_by_priority_then_title(self, docs_populated):
        status, body = handlers.section_list(
            "docs", "/api/docs/sample/sections", {}, name="sample"
        )
        assert status == 200
        items = body["items"]
        assert [i["path"] for i in items] == ["intro", "usage", "extras"]

    def test_excludes_content_field(self, docs_populated):
        _, body = handlers.section_list(
            "docs", "/api/docs/sample/sections", {}, name="sample"
        )
        for item in body["items"]:
            assert "content" not in item
            assert "content_md" not in item
            assert "content_html" not in item
            assert {"path", "title", "tags", "priority"} <= set(item.keys())

    def test_dir_missing_for_unknown_corpus(self, docs_populated):
        status, body = handlers.section_list(
            "docs", "/api/docs/missing/sections", {}, name="missing"
        )
        assert status == 200
        assert body["reason"] == "dir_missing"

    def test_not_indexed_when_sections_dir_empty(self, tmp_path, monkeypatch):
        base = _patch_project(tmp_path, monkeypatch)
        corpus = base / "docs" / "empty"
        _write_index(corpus, name="empty")
        # No sections/ subdir created.
        status, body = handlers.section_list(
            "docs", "/api/docs/empty/sections", {}, name="empty"
        )
        assert status == 200
        assert body["reason"] == "not_indexed"

    def test_parse_error_when_index_missing(self, tmp_path, monkeypatch):
        base = _patch_project(tmp_path, monkeypatch)
        corpus = base / "docs" / "broken"
        corpus.mkdir(parents=True)
        # No index.json. Sections dir created with one entry.
        _write_section(corpus, path="orphan", title="Orphan")
        status, body = handlers.section_list(
            "docs", "/api/docs/broken/sections", {}, name="broken"
        )
        assert status == 200
        assert body["reason"] == "parse_error"

    def test_research_list(self, research_populated):
        status, body = handlers.section_list(
            "research", "/api/research/papers/sections", {}, name="papers"
        )
        assert status == 200
        assert body["items"][0]["path"] == "alpha"


# ---------------------------------------------------------------------------
# section_detail
# ---------------------------------------------------------------------------


class TestSectionDetail:
    def test_returns_section_full(self, docs_populated):
        status, body = handlers.section_detail(
            "docs",
            "/api/docs/sample/sections/intro",
            {},
            name="sample",
            section_path="intro",
        )
        assert status == 200
        section = body["section"]
        assert section["title"] == "Introduction"
        assert section["priority"] == 10
        assert section["content_md"].startswith("# Intro")
        assert "<h1>" in section["content_html"]

    def test_research_extra_fields_present_when_set(self, research_populated):
        _, body = handlers.section_detail(
            "research",
            "/api/research/papers/sections/alpha",
            {},
            name="papers",
            section_path="alpha",
        )
        section = body["section"]
        assert section["source_type"] == "research"
        assert section["published_date"] == "2026-01-15"
        assert section["domain"] == "openai.com"

    def test_docs_section_omits_research_only_fields(self, docs_populated):
        _, body = handlers.section_detail(
            "docs",
            "/api/docs/sample/sections/intro",
            {},
            name="sample",
            section_path="intro",
        )
        section = body["section"]
        for field in ("source_type", "published_date", "domain"):
            assert field not in section

    def test_traversal_in_path_blocked(self, docs_populated):
        _, body = handlers.section_detail(
            "docs",
            "/api/docs/sample/sections/..%2F..%2Fetc%2Fpasswd",
            {},
            name="sample",
            section_path="../../etc/passwd",
        )
        assert body["items"] == []
        assert body["reason"] == "dir_missing"

    def test_traversal_in_name_blocked(self, docs_populated):
        _, body = handlers.section_detail(
            "docs",
            "/api/docs/../etc/sections/passwd",
            {},
            name="../etc",
            section_path="passwd",
        )
        assert body["reason"] == "dir_missing"

    def test_unknown_section_returns_dir_missing(self, docs_populated):
        _, body = handlers.section_detail(
            "docs",
            "/api/docs/sample/sections/nope",
            {},
            name="sample",
            section_path="nope",
        )
        assert body["reason"] == "dir_missing"

    def test_invalid_json_returns_parse_error(
        self, docs_populated
    ):
        # Corrupt one section file in place.
        from context_cli import PROJECT_ROOT  # noqa: F401  (route reads cli)
        import context_cli.cli as cli_mod

        bad = (
            cli_mod.PROJECT_ROOT
            / ".king-context"
            / "docs"
            / "sample"
            / "sections"
            / "intro.json"
        )
        bad.write_text("{not valid json", encoding="utf-8")
        _, body = handlers.section_detail(
            "docs",
            "/api/docs/sample/sections/intro",
            {},
            name="sample",
            section_path="intro",
        )
        assert body["reason"] == "parse_error"

    def test_malformed_markdown_renders_best_effort(
        self, tmp_path, monkeypatch
    ):
        base = _patch_project(tmp_path, monkeypatch)
        corpus = base / "docs" / "sample"
        _write_index(corpus, name="sample")
        _write_section(
            corpus,
            path="weird",
            title="Weird",
            content="```\nunclosed code fence\n",
        )
        status, body = handlers.section_detail(
            "docs",
            "/api/docs/sample/sections/weird",
            {},
            name="sample",
            section_path="weird",
        )
        assert status == 200
        assert body["section"]["content_html"]


# ---------------------------------------------------------------------------
# HTML pages
# ---------------------------------------------------------------------------


class TestCorpusPages:
    def test_corpus_page_renders_layout_and_sidebar(self, docs_populated):
        status, body = handlers.corpus_page(
            "docs", "/docs/sample", {}, name="sample"
        )
        assert status == 200
        assert isinstance(body, bytes)
        text = body.decode("utf-8")
        assert "<title>sample - King Context</title>" in text
        assert 'data-source="docs"' in text
        assert "Introduction" in text
        # Hint visible when no section is selected.
        assert "Choose a section" in text

    def test_section_page_renders_viewer_and_content(self, docs_populated):
        status, body = handlers.section_page(
            "docs",
            "/docs/sample/intro",
            {},
            name="sample",
            section_path="intro",
        )
        assert status == 200
        text = body.decode("utf-8")
        assert "Introduction" in text
        assert "<h1>" in text  # rendered markdown
        # Tag badge present.
        assert "overview" in text

    def test_research_page_uses_same_template_with_research_label(
        self, research_populated
    ):
        status, body = handlers.section_page(
            "research",
            "/research/papers/alpha",
            {},
            name="papers",
            section_path="alpha",
        )
        assert status == 200
        text = body.decode("utf-8")
        assert 'data-source="research"' in text
        # Research-only metadata bubbles into the viewer.
        assert "openai.com" in text
        assert "2026-01-15" in text

    def test_corpus_page_groups_untagged_sections(self, docs_populated):
        _, body = handlers.corpus_page(
            "docs", "/docs/sample", {}, name="sample"
        )
        text = body.decode("utf-8")
        # `extras` has no tag so it lands in the untagged group.
        assert "untagged" in text
        assert "Extras" in text

    def test_corpus_page_without_tags_index_still_renders(
        self, tmp_path, monkeypatch
    ):
        base = _patch_project(tmp_path, monkeypatch)
        corpus = base / "docs" / "sample"
        _write_index(corpus, name="sample")
        _write_section(
            corpus, path="solo", title="Solo", tags=["solo"], priority=1
        )
        # Note: no tags.json written.
        _, body = handlers.corpus_page(
            "docs", "/docs/sample", {}, name="sample"
        )
        text = body.decode("utf-8")
        # Falls back to "untagged" because tags.json is absent.
        assert "untagged" in text
        assert "Solo" in text


# ---------------------------------------------------------------------------
# Router integration
# ---------------------------------------------------------------------------


class TestRouterIntegration:
    @pytest.mark.parametrize("source", ["docs", "research"])
    def test_api_index_routed(
        self, docs_populated, research_populated, source
    ):
        status, headers, body = router.dispatch("GET", f"/api/{source}", {})
        assert status == 200
        assert "application/json" in headers["Content-Type"]
        payload = json.loads(body)
        assert "items" in payload

    @pytest.mark.parametrize(
        "source,corpus", [("docs", "sample"), ("research", "papers")]
    )
    def test_api_section_list_routed(
        self, docs_populated, research_populated, source, corpus
    ):
        status, _, body = router.dispatch(
            "GET", f"/api/{source}/{corpus}/sections", {}
        )
        assert status == 200
        payload = json.loads(body)
        assert payload["items"]

    @pytest.mark.parametrize(
        "source,corpus,section",
        [
            ("docs", "sample", "intro"),
            ("research", "papers", "alpha"),
        ],
    )
    def test_api_section_detail_routed(
        self,
        docs_populated,
        research_populated,
        source,
        corpus,
        section,
    ):
        status, _, body = router.dispatch(
            "GET", f"/api/{source}/{corpus}/sections/{section}", {}
        )
        assert status == 200
        payload = json.loads(body)
        assert payload["section"]["title"]

    @pytest.mark.parametrize(
        "source,corpus", [("docs", "sample"), ("research", "papers")]
    )
    def test_html_corpus_page_routed(
        self, docs_populated, research_populated, source, corpus
    ):
        status, headers, body = router.dispatch(
            "GET", f"/{source}/{corpus}", {}
        )
        assert status == 200
        assert headers["Content-Type"] == "text/html; charset=utf-8"
        assert b"<title>" in body

    @pytest.mark.parametrize(
        "source,corpus,section",
        [
            ("docs", "sample", "intro"),
            ("research", "papers", "alpha"),
        ],
    )
    def test_html_section_page_routed(
        self,
        docs_populated,
        research_populated,
        source,
        corpus,
        section,
    ):
        status, headers, body = router.dispatch(
            "GET", f"/{source}/{corpus}/{section}", {}
        )
        assert status == 200
        assert headers["Content-Type"] == "text/html; charset=utf-8"

    def test_url_encoded_section_path_decoded_by_router(
        self, docs_populated
    ):
        encoded = quote("intro", safe="")
        status, _, body = router.dispatch(
            "GET", f"/api/docs/sample/sections/{encoded}", {}
        )
        assert status == 200
        payload = json.loads(body)
        assert payload["section"]["path"] == "intro"

    def test_traversal_via_router_returns_empty_state(self, docs_populated):
        # `..%2F..%2Fetc%2Fpasswd` decodes to `../../etc/passwd`. The router
        # decodes named segments before calling the handler, which then
        # rejects the traversal at `_safe_segment`.
        status, _, body = router.dispatch(
            "GET",
            "/api/docs/sample/sections/" + quote("../../etc/passwd", safe=""),
            {},
        )
        assert status == 200
        payload = json.loads(body)
        assert payload["reason"] == "dir_missing"
        assert payload["items"] == []
