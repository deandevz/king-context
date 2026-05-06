"""Tests for king_context.web.render."""

from __future__ import annotations

import pytest

from king_context.web import render


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------


class TestRenderMarkdown:
    def test_basic_markdown(self):
        out = render.render_markdown("# Hello\n\nWorld")
        assert "<h1>Hello</h1>" in out
        assert "<p>World</p>" in out

    def test_empty_input_does_not_raise(self):
        # Best-effort: empty input is allowed and must not raise.
        out = render.render_markdown("")
        assert isinstance(out, str)

    def test_malformed_input_does_not_raise(self):
        # Strange bytes / unmatched markers should still produce a string.
        out = render.render_markdown("`unterminated\n\n```\nno close")
        assert isinstance(out, str)

    def test_fenced_code_extension_enabled(self):
        out = render.render_markdown("```python\nprint('hi')\n```")
        assert "<code" in out

    def test_tables_extension_enabled(self):
        md = "| a | b |\n|---|---|\n| 1 | 2 |\n"
        out = render.render_markdown(md)
        assert "<table>" in out


# ---------------------------------------------------------------------------
# render_template / render_page
# ---------------------------------------------------------------------------


class TestRenderTemplate:
    def test_substitutes_variables(self, tmp_path, monkeypatch):
        """`render_template` performs `${var}` substitution against ctx."""
        # Patch the template loader to point at a temp file.
        tpl = tmp_path / "fake.html"
        tpl.write_text("Hello, ${name}!", encoding="utf-8")
        monkeypatch.setattr(render, "_read_template", lambda _name: tpl.read_text("utf-8"))
        out = render.render_template("fake.html", {"name": "World"})
        assert out == "Hello, World!"

    def test_passes_through_pre_escaped_values(self, tmp_path, monkeypatch):
        """Caller is responsible for escaping. The template substitution is
        plain string replacement.
        """
        tpl = tmp_path / "x.html"
        tpl.write_text("<div>${msg}</div>", encoding="utf-8")
        monkeypatch.setattr(render, "_read_template", lambda _name: tpl.read_text("utf-8"))
        # Caller used html_escape before passing in.
        escaped = render.html_escape("<script>alert(1)</script>")
        out = render.render_template("x.html", {"msg": escaped})
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_inserts_raw_html_block_unescaped(self, tmp_path, monkeypatch):
        """Keys ending in `_raw` carry pre-rendered HTML and must be inserted
        verbatim. The substitution itself does not transform values.
        """
        tpl = tmp_path / "x.html"
        tpl.write_text("Body: ${content_html_raw}", encoding="utf-8")
        monkeypatch.setattr(render, "_read_template", lambda _name: tpl.read_text("utf-8"))
        out = render.render_template(
            "x.html", {"content_html_raw": "<p>hello</p>"}
        )
        assert "Body: <p>hello</p>" == out

    def test_render_page_wraps_with_layout(self):
        """`render_page` calls the real `_layout.html`. Output must contain
        the wrapped template content and the title.
        """
        # The adrs.html template needs adr_list_html_raw and adr_panel_html_raw.
        out = render.render_page(
            "adrs.html",
            {
                "adr_list_html_raw": "<ul></ul>",
                "adr_panel_html_raw": "",
            },
            title="Test Title",
        )
        assert isinstance(out, bytes)
        text = out.decode("utf-8")
        assert "<title>Test Title</title>" in text
        assert "<ul></ul>" in text
        assert "<nav" in text


# ---------------------------------------------------------------------------
# resolve_neighborhood
# ---------------------------------------------------------------------------


class TestResolveNeighborhood:
    def _decision(self, **overrides):
        base = {
            "id": "ADR-0001",
            "related": [],
            "supersedes": [],
            "superseded_by": [],
        }
        base.update(overrides)
        return base

    def test_marks_broken_for_missing_ids(self):
        decision = self._decision(related=["ADR-0099"])
        out = render.resolve_neighborhood(decision, indexed=[])
        assert out["related"][0]["broken"] is True
        assert out["related"][0]["title"] == ""
        assert out["related"][0]["status"] == ""
        assert out["related"][0]["id"] == "ADR-0099"

    def test_populates_existing_ids(self):
        indexed = [
            {"id": "ADR-0002", "title": "Two", "status": "accepted"},
        ]
        decision = self._decision(related=["ADR-0002"])
        out = render.resolve_neighborhood(decision, indexed)
        assert out["related"][0]["broken"] is False
        assert out["related"][0]["title"] == "Two"
        assert out["related"][0]["status"] == "accepted"

    def test_handles_all_three_relation_kinds(self):
        indexed = [
            {"id": "ADR-0002", "title": "Two", "status": "accepted"},
            {"id": "ADR-0003", "title": "Three", "status": "superseded"},
        ]
        decision = self._decision(
            related=["ADR-0002"],
            supersedes=["ADR-0003"],
            superseded_by=["ADR-0099"],
        )
        out = render.resolve_neighborhood(decision, indexed)
        assert len(out["related"]) == 1
        assert len(out["supersedes"]) == 1
        assert len(out["superseded_by"]) == 1
        assert out["supersedes"][0]["title"] == "Three"
        assert out["superseded_by"][0]["broken"] is True


# ---------------------------------------------------------------------------
# html_escape
# ---------------------------------------------------------------------------


class TestHtmlEscape:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("<a>", "&lt;a&gt;"),
            ('"x"', "&quot;x&quot;"),
            ("'y'", "&#x27;y&#x27;"),
            ("a&b", "a&amp;b"),
        ],
    )
    def test_escapes_special_chars(self, raw, expected):
        assert render.html_escape(raw) == expected
