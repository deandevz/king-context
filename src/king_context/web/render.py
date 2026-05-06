"""Render helpers for the local UI server.

Pure helpers used by `handlers.py`:

- `render_markdown(content_md)` converts markdown to HTML, best-effort (never raises).
- `render_template(template_name, ctx)` performs leaf-level string substitution
  using `string.Template` semantics (`$var` / `${var}`) on a template loaded
  from `king_context.web.templates`. No conditionals, no loops.
- `render_page(template_name, ctx, *, title)` wraps a rendered template inside
  `_layout.html` and returns UTF-8 bytes.
- `html_escape(value)` is a thin wrapper around `html.escape(value, quote=True)`.
- `resolve_neighborhood(decision, indexed)` looks up related/supersedes/
  superseded_by IDs and marks broken links.

Convention: any value placed in `ctx` that originated from user data must be
escaped by the caller before being passed in. The single exception is HTML
that the caller pre-renders intentionally (e.g. the output of
`render_markdown`); those go under keys ending with `_raw` so the template
substitution does not double-escape them. The substitution itself is plain
string replacement, so escaping is the caller's responsibility.
"""

from __future__ import annotations

import html
from importlib.resources import files
from string import Template
from typing import Any


_TEMPLATES_PACKAGE = "king_context.web.templates"
_LAYOUT_NAME = "_layout.html"
_LAYOUT_CONTENT_KEY = "__layout_content__"


def html_escape(value: str) -> str:
    """Escape `value` for safe inclusion as HTML text or attribute."""
    return html.escape(value, quote=True)


def render_markdown(content_md: str) -> str:
    """Convert markdown to HTML using the `markdown` library.

    Best-effort: any failure falls back to the raw text wrapped in `<pre>`.
    Enables `fenced_code` and `tables` extensions.
    """
    if not content_md:
        return ""
    try:
        import markdown as _markdown
    except Exception:
        return f"<pre>{html_escape(content_md)}</pre>"
    try:
        return _markdown.markdown(
            content_md,
            extensions=["fenced_code", "tables"],
            output_format="html",
        )
    except Exception:
        return f"<pre>{html_escape(content_md)}</pre>"


def _read_template(template_name: str) -> str:
    return files(_TEMPLATES_PACKAGE).joinpath(template_name).read_text(encoding="utf-8")


def render_template(template_name: str, ctx: dict[str, str]) -> str:
    """Substitute `$var` / `${var}` placeholders in `template_name`.

    Missing placeholders raise `KeyError` (caller must provide every key the
    template references). Values must already be escaped: this function does
    not transform them.
    """
    raw = _read_template(template_name)
    return Template(raw).substitute(ctx)


def render_page(template_name: str, ctx: dict[str, str], *, title: str) -> bytes:
    """Render `template_name` and embed the result in `_layout.html`.

    `title` is HTML-escaped before insertion. Returns UTF-8 bytes ready to
    write to the HTTP response body.
    """
    content = render_template(template_name, ctx)
    layout_ctx = {
        "title": html_escape(title),
        _LAYOUT_CONTENT_KEY: content,
    }
    page = render_template(_LAYOUT_NAME, layout_ctx)
    return page.encode("utf-8")


def resolve_neighborhood(
    decision: dict[str, Any],
    indexed: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """For each ADR ID in `related`, `supersedes`, `superseded_by`, look up
    the indexed entry and return `{id, title, status, broken}` for each.

    `indexed` is the output of `context_cli.adr._load_indexed_decisions()`.
    Pass it from the caller to avoid repeated IO. IDs not present in the
    index are returned with `broken: True` and empty `title` / `status`.
    """
    by_id: dict[str, dict[str, Any]] = {
        str(item.get("id", "")): item for item in indexed if item.get("id")
    }

    def _lookup(ref_id: str) -> dict[str, Any]:
        entry = by_id.get(ref_id)
        if entry is None:
            return {"id": ref_id, "title": "", "status": "", "broken": True}
        return {
            "id": ref_id,
            "title": str(entry.get("title", "")),
            "status": str(entry.get("status", "")),
            "broken": False,
        }

    out: dict[str, list[dict[str, Any]]] = {}
    for key in ("related", "supersedes", "superseded_by"):
        ref_ids = [str(item) for item in decision.get(key, []) if item]
        out[key] = [_lookup(ref) for ref in ref_ids]
    return out
