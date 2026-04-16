"""Tests for context_cli.grep module."""

import json

import pytest

from context_cli.grep import GrepMatch, grep_docs


def _create_store(tmp_path, docs):
    """Build a .king-context/ structure from a dict specification.

    docs: dict mapping doc_name -> list of section dicts.
    Each section dict has keys: title, path, content (and optionally others).
    Returns the store_dir path.
    """
    store_dir = tmp_path / ".king-context"
    for doc_name, sections in docs.items():
        sections_dir = store_dir / doc_name / "sections"
        sections_dir.mkdir(parents=True)

        # Write index.json
        index_data = {
            "name": doc_name,
            "display_name": doc_name.title(),
            "version": "v1",
            "base_url": f"https://{doc_name}.example.com",
            "section_count": len(sections),
        }
        (store_dir / doc_name / "index.json").write_text(
            json.dumps(index_data, indent=2)
        )

        for section in sections:
            section_data = {
                "title": section["title"],
                "path": section["path"],
                "url": section.get("url", ""),
                "keywords": section.get("keywords", []),
                "use_cases": section.get("use_cases", []),
                "tags": section.get("tags", []),
                "priority": section.get("priority", 0),
                "content": section["content"],
            }
            (sections_dir / f"{section['path']}.json").write_text(
                json.dumps(section_data, indent=2)
            )

    return store_dir


class TestGrepDocs:
    """Tests for grep_docs function."""

    def test_basic_text_match(self, tmp_path):
        store = _create_store(tmp_path, {
            "my-api": [
                {
                    "title": "Getting Started",
                    "path": "getting-started",
                    "content": "Install with pip install my-api.\nThen run the setup command.",
                },
            ],
        })

        results = grep_docs("pip install", store)

        assert len(results) == 1
        assert results[0].doc_name == "my-api"
        assert results[0].section_path == "getting-started"
        assert results[0].section_title == "Getting Started"
        assert results[0].line_number == 1
        assert "pip install" in results[0].line_content

    def test_regex_pattern_match(self, tmp_path):
        store = _create_store(tmp_path, {
            "my-api": [
                {
                    "title": "Config",
                    "path": "config",
                    "content": "Set timeout to 30s.\nOr set timeout to 60s.\nDone.",
                },
            ],
        })

        results = grep_docs(r"timeout to \d+s", store)

        assert len(results) == 2
        assert results[0].line_number == 1
        assert results[1].line_number == 2

    def test_context_lines(self, tmp_path):
        store = _create_store(tmp_path, {
            "my-api": [
                {
                    "title": "Steps",
                    "path": "steps",
                    "content": "Line A\nLine B\nLine C\nLine D\nLine E",
                },
            ],
        })

        results = grep_docs("Line C", store, context_lines=1)

        assert len(results) == 1
        m = results[0]
        assert m.line_number == 3
        assert m.context_before == ["Line B"]
        assert m.context_after == ["Line D"]

    def test_scoped_to_one_doc(self, tmp_path):
        store = _create_store(tmp_path, {
            "alpha": [
                {
                    "title": "Alpha Intro",
                    "path": "intro",
                    "content": "Welcome to alpha.",
                },
            ],
            "beta": [
                {
                    "title": "Beta Intro",
                    "path": "intro",
                    "content": "Welcome to beta.",
                },
            ],
        })

        results = grep_docs("Welcome", store, doc_name="alpha")

        assert len(results) == 1
        assert results[0].doc_name == "alpha"

    def test_no_matches_returns_empty(self, tmp_path):
        store = _create_store(tmp_path, {
            "my-api": [
                {
                    "title": "Intro",
                    "path": "intro",
                    "content": "Hello world.",
                },
            ],
        })

        results = grep_docs("zzz-nonexistent-pattern", store)

        assert results == []

    def test_grouped_by_section(self, tmp_path):
        """Multiple matches in the same section should be adjacent."""
        store = _create_store(tmp_path, {
            "my-api": [
                {
                    "title": "First Section",
                    "path": "first",
                    "content": "apple pie\norange juice\napple sauce",
                },
                {
                    "title": "Second Section",
                    "path": "second",
                    "content": "apple cider\nbanana split",
                },
            ],
        })

        results = grep_docs("apple", store)

        assert len(results) == 3
        # First two matches should come from "first" section (grouped)
        assert results[0].section_path == "first"
        assert results[1].section_path == "first"
        # Third from "second"
        assert results[2].section_path == "second"

    def test_case_insensitive(self, tmp_path):
        store = _create_store(tmp_path, {
            "my-api": [
                {
                    "title": "Casing",
                    "path": "casing",
                    "content": "Hello World\nhello world\nHELLO WORLD",
                },
            ],
        })

        results = grep_docs("hello world", store)

        assert len(results) == 3

    def test_empty_store(self, tmp_path):
        store = tmp_path / ".king-context"
        # store does not exist at all
        results = grep_docs("anything", store)
        assert results == []

    def test_context_lines_at_boundaries(self, tmp_path):
        """Context lines should not go out of bounds at start/end of content."""
        store = _create_store(tmp_path, {
            "my-api": [
                {
                    "title": "Boundary",
                    "path": "boundary",
                    "content": "First line\nSecond line\nThird line",
                },
            ],
        })

        # Match first line - context_before should be empty
        results = grep_docs("First line", store, context_lines=2)
        assert len(results) == 1
        assert results[0].context_before == []
        assert results[0].context_after == ["Second line", "Third line"]

        # Match last line - context_after should be empty
        results = grep_docs("Third line", store, context_lines=2)
        assert len(results) == 1
        assert results[0].context_before == ["First line", "Second line"]
        assert results[0].context_after == []

    def test_skips_underscore_directories(self, tmp_path):
        store = _create_store(tmp_path, {
            "my-api": [
                {
                    "title": "Visible",
                    "path": "visible",
                    "content": "match here",
                },
            ],
        })
        # Create an underscore directory that should be skipped
        hidden_dir = store / "_internal" / "sections"
        hidden_dir.mkdir(parents=True)
        (store / "_internal" / "index.json").write_text('{"name":"_internal"}')
        section_data = {
            "title": "Hidden",
            "path": "hidden",
            "content": "match here too",
        }
        (hidden_dir / "hidden.json").write_text(json.dumps(section_data))

        results = grep_docs("match", store)

        assert len(results) == 1
        assert results[0].doc_name == "my-api"
