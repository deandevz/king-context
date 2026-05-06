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
from context_cli.store import list_docs

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
_HINT_INDEX_DOCS = "Run `kctx index <url>` to populate .king-context/docs/"
_HINT_INDEX_RESEARCH = "Run `king-research <topic>` to populate .king-context/research/"
_HINT_INIT_PROJECT = "Run `npx @king-context/cli init` to scaffold .king-context/"


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


# ---------------------------------------------------------------------------
# Corpus endpoints (docs + research, parametrized by source_label)
# ---------------------------------------------------------------------------


_RESEARCH_FIELDS = ("source_type", "published_date", "domain")


def _project_root() -> Path:
    """Read PROJECT_ROOT through `context_cli.cli` so monkeypatch works.

    Mirrors the indirection used by `context_cli.adr._project_root`. The
    constants `STORE_DIR` / `RESEARCH_STORE_DIR` are bound at import time,
    so referencing them directly would defeat tests that swap PROJECT_ROOT.
    """
    import context_cli.cli as cli_mod
    from context_cli import PROJECT_ROOT as _DEFAULT_ROOT

    return getattr(cli_mod, "PROJECT_ROOT", _DEFAULT_ROOT)


def _store_dir_for(source_label: str) -> Path:
    """Resolve the `.king-context/{docs|research}/` directory for `source_label`.

    Raises ValueError for any other label so router-level typos surface
    as a real error instead of a silent dir_missing.
    """
    if source_label == "docs":
        return _project_root() / ".king-context" / "docs"
    if source_label == "research":
        return _project_root() / ".king-context" / "research"
    raise ValueError(f"unknown source_label: {source_label!r}")


def _hint_for(source_label: str, kind: str) -> str:
    if kind == "init":
        return _HINT_INIT_PROJECT
    if source_label == "docs":
        return _HINT_INDEX_DOCS
    return _HINT_INDEX_RESEARCH


def _safe_segment(value: str) -> str | None:
    """Validate a single URL path segment (corpus name or section path).

    Rejects empty input, `..`, leading `/`, backslashes, and segments that
    contain `/`. Returns the value unchanged when valid, else None.
    """
    if not value:
        return None
    if value == "." or value == "..":
        return None
    if value.startswith("/") or "\\" in value or "/" in value:
        return None
    if "\x00" in value:
        return None
    return value


def _resolve_within(base: Path, *parts: str) -> Path | None:
    """Resolve `base / parts` and ensure the result stays inside `base`.

    Returns None when resolution fails or the resolved path escapes `base`.
    """
    try:
        candidate = base.joinpath(*parts)
        resolved = candidate.resolve()
        base_resolved = base.resolve()
    except (OSError, RuntimeError):
        return None
    try:
        resolved.relative_to(base_resolved)
    except ValueError:
        return None
    return resolved


def _read_section_file(section_path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(section_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_tags_index(corpus_dir: Path) -> dict[str, list[str]]:
    """Return the reverse `tag -> [section_path,...]` index for a corpus.

    Falls back to an empty mapping when `tags.json` is missing or invalid.
    """
    tags_path = corpus_dir / "tags.json"
    if not tags_path.exists():
        return {}
    try:
        data = json.loads(tags_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[str]] = {}
    for tag, paths in data.items():
        if not isinstance(paths, list):
            continue
        out[str(tag)] = [str(p) for p in paths if isinstance(p, str)]
    return out


def _section_list_payload(
    source_label: str, name: str
) -> tuple[dict[str, Any], Path | None]:
    """Build the SectionListItem payload for `{source_label}/{name}`.

    Returns (payload, corpus_dir_or_None). `corpus_dir` is None on empty
    states so callers can short-circuit downstream work. The payload always
    matches the EmptyState envelope `{items, reason?, hint?}`.
    """
    store_dir = _store_dir_for(source_label)
    if not store_dir.exists():
        return _empty("dir_missing", _hint_for(source_label, "init")), None

    safe_name = _safe_segment(name)
    if safe_name is None:
        return _empty("dir_missing", _hint_for(source_label, "init")), None

    corpus_dir = _resolve_within(store_dir, safe_name)
    if corpus_dir is None or not corpus_dir.is_dir():
        return _empty("dir_missing", _hint_for(source_label, "init")), None

    if not (corpus_dir / "index.json").exists():
        return _empty("parse_error", _hint_for(source_label, "index")), corpus_dir

    sections_dir = corpus_dir / "sections"
    if not sections_dir.is_dir():
        return _empty("not_indexed", _hint_for(source_label, "index")), corpus_dir

    items: list[dict[str, Any]] = []
    for entry in sorted(sections_dir.glob("*.json")):
        data = _read_section_file(entry)
        if data is None or not isinstance(data, dict):
            continue
        items.append(
            {
                "path": str(data.get("path", entry.stem)),
                "title": str(data.get("title", "")),
                "tags": list(data.get("tags") or []),
                "priority": int(data.get("priority") or 0),
            }
        )
    if not items:
        return _empty("not_indexed", _hint_for(source_label, "index")), corpus_dir

    items.sort(key=lambda it: (-it["priority"], it["title"]))
    return {"items": items}, corpus_dir


def corpus_index(
    source_label: str, path: str, query: dict, **_: object
) -> tuple[int, dict]:
    """GET /api/{docs|research}: list of CorpusInfo entries for the source."""
    store_dir = _store_dir_for(source_label)
    if not store_dir.exists():
        return 200, _empty("dir_missing", _hint_for(source_label, "init"))

    docs = list_docs(store_dir)
    if not docs:
        return 200, _empty("not_indexed", _hint_for(source_label, "index"))

    items = [
        {
            "name": d.name,
            "display_name": d.display_name,
            "version": d.version,
            "section_count": d.section_count,
            "base_url": d.base_url,
        }
        for d in docs
    ]
    return 200, {"items": items}


def section_list(
    source_label: str, path: str, query: dict, **path_params: object
) -> tuple[int, dict]:
    """GET /api/{docs|research}/{name}/sections: light list, no `content`."""
    name = str(path_params.get("name", ""))
    payload, _corpus_dir = _section_list_payload(source_label, name)
    return 200, payload


def section_detail(
    source_label: str, path: str, query: dict, **path_params: object
) -> tuple[int, dict]:
    """GET /api/{docs|research}/{name}/sections/{section_path}: full section."""
    name = str(path_params.get("name", ""))
    raw_path = str(path_params.get("section_path", ""))

    safe_name = _safe_segment(name)
    safe_path = _safe_segment(raw_path)
    if safe_name is None or safe_path is None:
        return 200, _empty("dir_missing", _hint_for(source_label, "init"))

    store_dir = _store_dir_for(source_label)
    if not store_dir.exists():
        return 200, _empty("dir_missing", _hint_for(source_label, "init"))

    section_file = _resolve_within(
        store_dir, safe_name, "sections", f"{safe_path}.json"
    )
    if section_file is None or not section_file.is_file():
        return 200, _empty("dir_missing", _hint_for(source_label, "init"))

    data = _read_section_file(section_file)
    if data is None or not isinstance(data, dict):
        return 200, _empty("parse_error", _hint_for(source_label, "index"))

    content_md = str(data.get("content", ""))
    content_html = render_markdown(content_md)

    section: dict[str, Any] = {
        "path": str(data.get("path", safe_path)),
        "title": str(data.get("title", "")),
        "url": str(data.get("url", "")),
        "keywords": list(data.get("keywords") or []),
        "use_cases": list(data.get("use_cases") or []),
        "tags": list(data.get("tags") or []),
        "priority": int(data.get("priority") or 0),
        "content_md": content_md,
        "content_html": content_html,
    }
    for field in _RESEARCH_FIELDS:
        if field in data and data.get(field) not in (None, ""):
            section[field] = data[field]

    return 200, {"section": section}


# ---------------------------------------------------------------------------
# Corpus HTML pages
# ---------------------------------------------------------------------------


def _section_link(source_label: str, corpus_name: str, section_path: str) -> str:
    return (
        f"/{source_label}/"
        f"{quote(corpus_name, safe='')}/"
        f"{quote(section_path, safe='')}"
    )


def _build_sidebar_html(
    source_label: str,
    corpus_name: str,
    list_payload: dict,
    tags_index: dict[str, list[str]],
) -> str:
    items = list_payload.get("items") or []
    if not items:
        reason = list_payload.get("reason", "")
        hint = list_payload.get("hint", "")
        return (
            '<div class="kctx-empty">'
            f'<p class="kctx-empty-reason">{html_escape(str(reason))}</p>'
            f'<p class="kctx-empty-hint">{html_escape(str(hint))}</p>'
            '</div>'
        )

    by_path: dict[str, dict[str, Any]] = {
        str(it.get("path", "")): it for it in items if it.get("path")
    }

    groups: dict[str, list[str]] = {}
    seen_paths: set[str] = set()
    for tag, paths in tags_index.items():
        members = [p for p in paths if p in by_path]
        if not members:
            continue
        groups[tag] = members
        seen_paths.update(members)

    untagged = [p for p in by_path.keys() if p not in seen_paths]
    if untagged:
        groups.setdefault("untagged", []).extend(untagged)

    parts: list[str] = ['<nav class="kctx-corpus-nav">']
    for tag in sorted(groups.keys()):
        parts.append('<section class="kctx-tag-group">')
        parts.append(
            f'<h3 class="kctx-tag-label">{html_escape(tag)}</h3>'
        )
        parts.append('<ul class="kctx-section-list">')
        members = sorted(
            groups[tag],
            key=lambda p: (
                -int(by_path[p].get("priority") or 0),
                str(by_path[p].get("title", "")),
            ),
        )
        for path in members:
            item = by_path[path]
            title = str(item.get("title", "")) or path
            priority = int(item.get("priority") or 0)
            link = _section_link(source_label, corpus_name, path)
            parts.append(
                '<li class="kctx-section-item">'
                f'<a href="{html_escape(link)}" class="kctx-section-link">'
                f'<span class="kctx-section-title">{html_escape(title)}</span>'
                f' <span class="kctx-section-priority">'
                f'{html_escape(str(priority))}</span>'
                '</a>'
                '</li>'
            )
        parts.append('</ul></section>')
    parts.append('</nav>')
    return "".join(parts)


def _build_viewer_html(detail_payload: dict | None) -> str:
    if detail_payload is None:
        return (
            '<div class="kctx-viewer-hint">'
            '<p>Choose a section from the left to read its content.</p>'
            '</div>'
        )
    section = detail_payload.get("section")
    if not section:
        reason = detail_payload.get("reason", "")
        hint = detail_payload.get("hint", "")
        return (
            '<div class="kctx-empty">'
            f'<p class="kctx-empty-reason">{html_escape(str(reason))}</p>'
            f'<p class="kctx-empty-hint">{html_escape(str(hint))}</p>'
            '</div>'
        )

    parts: list[str] = ['<article class="kctx-section-detail">']
    parts.append(
        f'<h2 class="kctx-section-detail-title">'
        f'{html_escape(str(section.get("title", "")))}'
        '</h2>'
    )

    meta_parts: list[str] = []
    priority = section.get("priority")
    if priority is not None:
        meta_parts.append(
            f'Priority: <strong>{html_escape(str(priority))}</strong>'
        )
    source_type = section.get("source_type")
    if source_type:
        meta_parts.append(
            f'Source: {html_escape(str(source_type))}'
        )
    domain = section.get("domain")
    if domain:
        meta_parts.append(f'Domain: {html_escape(str(domain))}')
    published = section.get("published_date")
    if published:
        meta_parts.append(f'Published: {html_escape(str(published))}')
    if meta_parts:
        parts.append(
            '<p class="kctx-section-meta">'
            + ' <span class="kctx-sep">.</span> '.join(meta_parts)
            + '</p>'
        )

    tags = section.get("tags") or []
    if tags:
        badges = "".join(
            f'<span class="kctx-tag-badge">{html_escape(str(t))}</span>'
            for t in tags
        )
        parts.append(f'<p class="kctx-section-tags">{badges}</p>')

    url = section.get("url")
    if url:
        parts.append(
            f'<p class="kctx-section-source">'
            f'<a href="{html_escape(str(url))}" rel="noopener" target="_blank">'
            f'{html_escape(str(url))}</a></p>'
        )

    content_html = str(section.get("content_html", ""))
    parts.append(
        f'<section class="kctx-section-content">{content_html}</section>'
    )
    parts.append('</article>')
    return "".join(parts)


def _corpus_subtitle(source_label: str, corpus_name: str) -> str:
    if source_label == "research":
        return f"Research corpus: {corpus_name}"
    return f"Documentation corpus: {corpus_name}"


def _render_corpus_page(
    source_label: str,
    corpus_name: str,
    list_payload: dict,
    detail_payload: dict | None,
    corpus_dir: Path | None,
) -> bytes:
    tags_index = _read_tags_index(corpus_dir) if corpus_dir is not None else {}
    sidebar_html = _build_sidebar_html(
        source_label, corpus_name, list_payload, tags_index
    )
    viewer_html = _build_viewer_html(detail_payload)
    title_value = corpus_name or source_label
    ctx = {
        "source_label": html_escape(source_label),
        "corpus_title": html_escape(title_value),
        "corpus_subtitle": html_escape(_corpus_subtitle(source_label, corpus_name)),
        "sections_grouped_html_raw": sidebar_html,
        "section_view_html_raw": viewer_html,
    }
    page_title = f"{title_value} - King Context"
    return render_page("corpus.html", ctx, title=page_title)


def corpus_page(
    source_label: str, path: str, query: dict, **path_params: object
) -> tuple[int, bytes]:
    """GET /{docs|research}/{name}: sidebar populated, viewer empty hint."""
    name = str(path_params.get("name", ""))
    list_payload, corpus_dir = _section_list_payload(source_label, name)
    body = _render_corpus_page(
        source_label, name, list_payload, None, corpus_dir
    )
    return 200, body


def section_page(
    source_label: str, path: str, query: dict, **path_params: object
) -> tuple[int, bytes]:
    """GET /{docs|research}/{name}/{section_path}: sidebar + populated viewer."""
    name = str(path_params.get("name", ""))
    list_payload, corpus_dir = _section_list_payload(source_label, name)
    _status, detail_payload = section_detail(
        source_label, path, query, **path_params
    )
    body = _render_corpus_page(
        source_label, name, list_payload, detail_payload, corpus_dir
    )
    return 200, body
