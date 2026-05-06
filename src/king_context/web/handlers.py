"""Domain handlers for the local UI server.

Each handler matches the router contract:

    (path, query, **path_params) -> (status, dict | bytes)

Returning a `dict` produces a JSON response. Returning `bytes` produces an
HTML (or other binary) response with Content-Type derived from the request
path extension.

Empty / failed-but-expected states return 200 with an `EmptyState` shape:

    {"items": [], "reason": "dir_missing" | "not_indexed" | "parse_error",
     "hint": "..."}

Handlers reuse `context_cli.adr` for parsing and indexed lookups. They never
import or write SQLite: the UI is read-only on top of the flat-file store.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import quote

from context_cli.adr import (
    AdrError,
    _adr_dir,
    _decisions_dir,
    _load_indexed_decisions,
    _normalize_id,
    _source_path_by_id,
    parse_adr,
)

from king_context.web.render import (
    html_escape,
    render_markdown,
    render_page,
    resolve_neighborhood,
)


_HINT_INDEX = "Run `kctx adr index`"
_HINT_INIT = "Run `kctx adr index` to populate from .king-context/adr/*.md"
_HINT_GRAPH = "Run `kctx adr index` to generate the graph"
_HINT_VALIDATE = "Run `kctx adr validate` to inspect the broken ADR"


def _empty(reason: str, hint: str) -> dict[str, Any]:
    return {"items": [], "reason": reason, "hint": hint}


def _adr_link(adr_id: str) -> str:
    return f"/adrs/{quote(adr_id, safe='')}"


def _strip_frontmatter(text: str) -> str:
    """Return `text` with a leading YAML frontmatter block removed.

    The ADR `content` stored in indexed JSON includes the full source file
    (frontmatter + body). For HTML rendering we want the body only, so the
    page does not show the YAML as a paragraph.
    """
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---", 4)
    if end == -1:
        return text
    body = text[end + 4:]
    if body.startswith("\n"):
        body = body[1:]
    return body


# ---------------------------------------------------------------------------
# JSON endpoints
# ---------------------------------------------------------------------------


def adr_list(path: str, query: dict, **_: object) -> tuple[int, dict]:
    """GET /api/adrs: list of ADRListItem entries (no `content`)."""
    decisions_dir = _decisions_dir()
    if not decisions_dir.exists():
        return 200, _empty("dir_missing", _HINT_INIT)
    sections_dir = decisions_dir / "sections"
    if not sections_dir.exists():
        return 200, _empty("not_indexed", _HINT_INDEX)

    indexed = _load_indexed_decisions()
    if not indexed:
        return 200, _empty("not_indexed", _HINT_INDEX)

    items = []
    for entry in indexed:
        items.append(
            {
                "id": entry.get("id", ""),
                "title": entry.get("title", ""),
                "status": entry.get("status", ""),
                "date": entry.get("date", ""),
                "areas": list(entry.get("areas") or []),
                "related_count": len(entry.get("related") or []),
                "supersedes_count": len(entry.get("supersedes") or []),
                "superseded_by_count": len(entry.get("superseded_by") or []),
            }
        )
    items.sort(key=lambda item: (item.get("date", ""), item.get("id", "")))
    return 200, {"items": items}


def _decision_dict_from_md(md_path: Path) -> dict[str, Any]:
    return asdict(parse_adr(md_path))


def _find_md_candidate(adr_id: str) -> Path | None:
    """Find an ADR `.md` whose filename matches the ID's number prefix.

    Used as a probe to distinguish "no such ADR" from "ADR file exists but
    parse failed". Returns the first matching path or None.
    """
    adr_dir = _adr_dir()
    if not adr_dir.exists():
        return None
    number = adr_id.split("-")[-1]
    for candidate in sorted(adr_dir.glob(f"{number}-*.md")):
        return candidate
    return None


def adr_detail(path: str, query: dict, **path_params: object) -> tuple[int, dict]:
    """GET /api/adrs/{id}: full ADR + neighborhood lookup."""
    raw_id = str(path_params.get("id", ""))
    try:
        adr_id = _normalize_id(raw_id)
    except AdrError:
        return 200, _empty("dir_missing", _HINT_INIT)

    decision_data: dict[str, Any] | None = None

    md_path = _source_path_by_id(adr_id)
    if md_path is not None:
        decision_data = _decision_dict_from_md(md_path)
    else:
        # Either no .md exists at all for this ID, or the matching .md has
        # invalid frontmatter. Probe the filesystem to disambiguate.
        candidate = _find_md_candidate(adr_id)
        if candidate is not None:
            try:
                decision_data = _decision_dict_from_md(candidate)
                if decision_data.get("id") != adr_id:
                    decision_data = None
            except AdrError:
                return 200, _empty("parse_error", _HINT_VALIDATE)

    indexed = _load_indexed_decisions()
    if decision_data is None:
        for entry in indexed:
            if entry.get("id") == adr_id:
                decision_data = dict(entry)
                break

    if decision_data is None:
        return 200, _empty("dir_missing", _HINT_INIT)

    raw_content = str(decision_data.get("content", ""))
    content_md = _strip_frontmatter(raw_content)
    content_html = render_markdown(content_md)
    neighborhood = resolve_neighborhood(decision_data, indexed)

    adr_full = {
        "id": decision_data.get("id", ""),
        "title": decision_data.get("title", ""),
        "status": decision_data.get("status", ""),
        "date": decision_data.get("date", ""),
        "areas": list(decision_data.get("areas") or []),
        "keywords": list(decision_data.get("keywords") or []),
        "tags": list(decision_data.get("tags") or []),
        "related": list(decision_data.get("related") or []),
        "supersedes": list(decision_data.get("supersedes") or []),
        "superseded_by": list(decision_data.get("superseded_by") or []),
        "content_md": content_md,
        "content_html": content_html,
    }
    return 200, {"adr": adr_full, "neighborhood": neighborhood}


def adr_graph(path: str, query: dict, **_: object) -> tuple[int, dict]:
    """GET /api/adrs/graph: pass-through of decisions/project/graph.json."""
    graph_path = _decisions_dir() / "graph.json"
    if not graph_path.exists():
        return 200, _empty("not_indexed", _HINT_GRAPH)
    try:
        data = json.loads(graph_path.read_text())
    except (OSError, json.JSONDecodeError):
        return 200, _empty("not_indexed", _HINT_GRAPH)
    if not isinstance(data, dict) or "nodes" not in data or "edges" not in data:
        return 200, _empty("not_indexed", _HINT_GRAPH)
    return 200, data


# ---------------------------------------------------------------------------
# HTML pages
# ---------------------------------------------------------------------------


def _build_list_html(payload: dict) -> str:
    items = payload.get("items") or []
    if not items:
        reason = payload.get("reason", "")
        hint = payload.get("hint", "")
        return (
            '<div class="kctx-empty">'
            f'<p class="kctx-empty-reason">{html_escape(str(reason))}</p>'
            f'<p class="kctx-empty-hint">{html_escape(str(hint))}</p>'
            '</div>'
        )
    parts = ['<ul class="kctx-adr-items">']
    for item in items:
        adr_id = str(item.get("id", ""))
        title = str(item.get("title", ""))
        status = str(item.get("status", ""))
        date = str(item.get("date", ""))
        link = _adr_link(adr_id)
        parts.append(
            '<li class="kctx-adr-item">'
            f'<a href="{html_escape(link)}" class="kctx-adr-link">'
            f'<span class="kctx-adr-id">{html_escape(adr_id)}</span> '
            f'<span class="kctx-adr-title">{html_escape(title)}</span>'
            '</a> '
            f'<span class="kctx-adr-status status-{html_escape(status)}">'
            f'{html_escape(status)}</span> '
            f'<span class="kctx-adr-date">{html_escape(date)}</span>'
            '</li>'
        )
    parts.append('</ul>')
    return "".join(parts)


def _build_panel_html(payload: dict) -> str:
    adr = payload.get("adr")
    if not adr:
        reason = payload.get("reason", "")
        hint = payload.get("hint", "")
        return (
            '<div class="kctx-empty">'
            f'<p class="kctx-empty-reason">{html_escape(str(reason))}</p>'
            f'<p class="kctx-empty-hint">{html_escape(str(hint))}</p>'
            '</div>'
        )
    neighborhood = payload.get("neighborhood") or {}
    parts = ['<article class="kctx-adr-detail">']
    parts.append(
        f'<h2 class="kctx-adr-detail-title">'
        f'{html_escape(str(adr.get("id", "")))}: '
        f'{html_escape(str(adr.get("title", "")))}'
        '</h2>'
    )
    parts.append(
        '<p class="kctx-adr-detail-meta">'
        f'Status: <strong>{html_escape(str(adr.get("status", "")))}</strong> '
        f'<span class="kctx-sep">.</span> '
        f'Date: {html_escape(str(adr.get("date", "")))}'
        '</p>'
    )
    areas = adr.get("areas") or []
    if areas:
        parts.append(
            '<p class="kctx-adr-detail-areas">Areas: '
            f'{html_escape(", ".join(str(a) for a in areas))}'
            '</p>'
        )

    content_html = str(adr.get("content_html", ""))
    parts.append(f'<section class="kctx-adr-content">{content_html}</section>')

    sections = (
        ("Related", "related"),
        ("Supersedes", "supersedes"),
        ("Superseded by", "superseded_by"),
    )
    for label, key in sections:
        refs = neighborhood.get(key) or []
        if not refs:
            continue
        parts.append('<section class="kctx-adr-refs">')
        parts.append(f'<h3>{html_escape(label)}</h3>')
        parts.append('<ul>')
        for ref in refs:
            ref_id = str(ref.get("id", ""))
            ref_title = str(ref.get("title", ""))
            broken = bool(ref.get("broken"))
            if broken:
                parts.append(
                    '<li class="kctx-adr-ref broken">'
                    f'<span title="link broken">{html_escape(ref_id)} '
                    '(broken)</span></li>'
                )
            else:
                link = _adr_link(ref_id)
                label_text = ref_id if not ref_title else f"{ref_id}: {ref_title}"
                parts.append(
                    '<li class="kctx-adr-ref">'
                    f'<a href="{html_escape(link)}">{html_escape(label_text)}</a>'
                    '</li>'
                )
        parts.append('</ul></section>')
    parts.append('</article>')
    return "".join(parts)


def _render_adrs_page(list_payload: dict, panel_payload: dict | None) -> bytes:
    list_html = _build_list_html(list_payload)
    panel_html = _build_panel_html(panel_payload) if panel_payload else ""
    ctx = {
        "adr_list_html_raw": list_html,
        "adr_panel_html_raw": panel_html,
    }
    return render_page("adrs.html", ctx, title="ADRs - King Context")


def adr_page(path: str, query: dict, **_kwargs: object) -> tuple[int, bytes]:
    """GET /adrs: server-rendered list page; panel is empty."""
    _status, list_payload = adr_list(path, query)
    return 200, _render_adrs_page(list_payload, None)


def adr_detail_page(
    path: str, query: dict, **path_params: object
) -> tuple[int, bytes]:
    """GET /adrs/{id}: same template as `/adrs` with the panel populated."""
    _status, list_payload = adr_list(path, query)
    _detail_status, detail_payload = adr_detail(path, query, **path_params)
    return 200, _render_adrs_page(list_payload, detail_payload)
