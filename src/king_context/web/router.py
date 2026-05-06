"""HTTP path router for the local UI server.

Routes are registered as (method, pattern, handler). Patterns may be exact
("/api/health") or use a single trailing wildcard ("/static/{*rest}") that
captures the remainder of the path. Adding new routes for later tasks happens
in this same module by appending to ``_ROUTES``.

Handlers return ``(status, dict)`` for JSON responses or ``(status, bytes)``
for binary responses (Content-Type derived from the request path extension).
"""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Callable
from urllib.parse import unquote


_STATIC_DIR = Path(__file__).parent / "static"


_MIME_TYPES = {
    ".txt": "text/plain",
    ".js": "application/javascript",
    ".css": "text/css",
    ".html": "text/html",
    ".svg": "image/svg+xml",
    ".json": "application/json",
}


def _resolve_version() -> str:
    try:
        return version("king-context")
    except PackageNotFoundError:
        return "unknown"


def _content_type_for(path: str) -> str:
    ext = Path(path).suffix.lower()
    return _MIME_TYPES.get(ext, "application/octet-stream")


def _try_match(pattern: str, path: str) -> dict | None:
    """Return path params if `path` matches `pattern`, else None.

    Supported pattern forms:
      - exact: ``/api/health``
      - trailing wildcard: ``/static/{*rest}`` captures the remainder as a
        single value under the wildcard name (no per-segment URL decoding).
      - single-segment named param: ``/api/adrs/{id}`` captures one path
        segment and URL-decodes it before returning.

    A path matches a `{name}` segment for any non-empty value (including
    "graph"); ordering of route registration disambiguates overlap.
    """
    if "{*" in pattern:
        prefix, rest = pattern.split("{*", 1)
        if not rest.endswith("}"):
            return None
        wildcard_name = rest[:-1]
        if path.startswith(prefix):
            return {wildcard_name: path[len(prefix):]}
        return None

    if "{" not in pattern:
        if path == pattern:
            return {}
        return None

    pat_segments = pattern.split("/")
    path_segments = path.split("/")
    if len(pat_segments) != len(path_segments):
        return None

    params: dict[str, str] = {}
    for pat_seg, path_seg in zip(pat_segments, path_segments):
        if pat_seg.startswith("{") and pat_seg.endswith("}"):
            name = pat_seg[1:-1]
            if not path_seg:
                return None
            params[name] = unquote(path_seg)
        elif pat_seg != path_seg:
            return None
    return params


def _handle_health(path: str, query: dict, **_: object) -> tuple[int, dict]:
    """GET /api/health: server liveness and version probe."""
    return 200, {"status": "ok", "version": _resolve_version()}


def _handle_static(
    path: str, query: dict, *, rest: str = "", **_: object
) -> tuple[int, bytes] | tuple[int, dict]:
    """GET /static/{rest}: serve files from the bundled static directory.

    Rejects empty paths, absolute paths, backslashes, and any segment equal
    to "..". Resolves the target and verifies it stays inside _STATIC_DIR.
    """
    decoded = unquote(rest)
    if not decoded or decoded.startswith("/") or "\\" in decoded:
        return 404, {"error": "not_found"}
    if any(part == ".." for part in decoded.split("/")):
        return 404, {"error": "not_found"}

    base = _STATIC_DIR.resolve()
    try:
        target = (base / decoded).resolve()
    except (OSError, RuntimeError):
        return 404, {"error": "not_found"}
    try:
        target.relative_to(base)
    except ValueError:
        return 404, {"error": "not_found"}
    if not target.is_file():
        return 404, {"error": "not_found"}
    return 200, target.read_bytes()


def _import_handlers():
    """Lazy import to avoid pulling context_cli at module-load time."""
    from king_context.web import handlers as _handlers
    return _handlers


def _handle_adr_list(path: str, query: dict, **kw: object) -> tuple[int, dict]:
    return _import_handlers().adr_list(path, query, **kw)


def _handle_adr_graph(path: str, query: dict, **kw: object) -> tuple[int, dict]:
    return _import_handlers().adr_graph(path, query, **kw)


def _handle_adr_detail(path: str, query: dict, **kw: object) -> tuple[int, dict]:
    return _import_handlers().adr_detail(path, query, **kw)


def _handle_adr_page(path: str, query: dict, **kw: object) -> tuple[int, bytes]:
    return _import_handlers().adr_page(path, query, **kw)


def _handle_adr_detail_page(
    path: str, query: dict, **kw: object
) -> tuple[int, bytes]:
    return _import_handlers().adr_detail_page(path, query, **kw)


def _handle_corpus_index_docs(
    path: str, query: dict, **kw: object
) -> tuple[int, dict]:
    return _import_handlers().corpus_index("docs", path, query, **kw)


def _handle_corpus_index_research(
    path: str, query: dict, **kw: object
) -> tuple[int, dict]:
    return _import_handlers().corpus_index("research", path, query, **kw)


def _handle_section_list_docs(
    path: str, query: dict, **kw: object
) -> tuple[int, dict]:
    return _import_handlers().section_list("docs", path, query, **kw)


def _handle_section_list_research(
    path: str, query: dict, **kw: object
) -> tuple[int, dict]:
    return _import_handlers().section_list("research", path, query, **kw)


def _handle_section_detail_docs(
    path: str, query: dict, **kw: object
) -> tuple[int, dict]:
    return _import_handlers().section_detail("docs", path, query, **kw)


def _handle_section_detail_research(
    path: str, query: dict, **kw: object
) -> tuple[int, dict]:
    return _import_handlers().section_detail("research", path, query, **kw)


def _handle_corpus_page_docs(
    path: str, query: dict, **kw: object
) -> tuple[int, bytes]:
    return _import_handlers().corpus_page("docs", path, query, **kw)


def _handle_corpus_page_research(
    path: str, query: dict, **kw: object
) -> tuple[int, bytes]:
    return _import_handlers().corpus_page("research", path, query, **kw)


def _handle_section_page_docs(
    path: str, query: dict, **kw: object
) -> tuple[int, bytes]:
    return _import_handlers().section_page("docs", path, query, **kw)


def _handle_section_page_research(
    path: str, query: dict, **kw: object
) -> tuple[int, bytes]:
    return _import_handlers().section_page("research", path, query, **kw)


_HTML = "text/html; charset=utf-8"


# Route tuple: (method, pattern, handler, content_type_override).
# `content_type_override=None` means: derive from response body type
# (`dict` → JSON, `bytes` → MIME by path extension).
_ROUTES: list[tuple[str, str, Callable[..., tuple], str | None]] = [
    ("GET", "/api/health", _handle_health, None),
    # Order matters: register the exact-path /api/adrs/graph before the
    # parameterized /api/adrs/{id} so "graph" is not captured as an id.
    ("GET", "/api/adrs", _handle_adr_list, None),
    ("GET", "/api/adrs/graph", _handle_adr_graph, None),
    ("GET", "/api/adrs/{id}", _handle_adr_detail, None),
    ("GET", "/adrs", _handle_adr_page, _HTML),
    ("GET", "/adrs/{id}", _handle_adr_detail_page, _HTML),
    # Corpus JSON endpoints (docs + research).
    ("GET", "/api/docs", _handle_corpus_index_docs, None),
    ("GET", "/api/docs/{name}/sections", _handle_section_list_docs, None),
    (
        "GET",
        "/api/docs/{name}/sections/{section_path}",
        _handle_section_detail_docs,
        None,
    ),
    ("GET", "/api/research", _handle_corpus_index_research, None),
    (
        "GET",
        "/api/research/{name}/sections",
        _handle_section_list_research,
        None,
    ),
    (
        "GET",
        "/api/research/{name}/sections/{section_path}",
        _handle_section_detail_research,
        None,
    ),
    # Corpus HTML pages.
    ("GET", "/docs/{name}", _handle_corpus_page_docs, _HTML),
    ("GET", "/docs/{name}/{section_path}", _handle_section_page_docs, _HTML),
    ("GET", "/research/{name}", _handle_corpus_page_research, _HTML),
    (
        "GET",
        "/research/{name}/{section_path}",
        _handle_section_page_research,
        _HTML,
    ),
    ("GET", "/static/{*rest}", _handle_static, None),
]


def _error_response(status: int, code: str) -> tuple[int, dict, bytes]:
    body = json.dumps({"error": code}).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Length": str(len(body)),
    }
    return status, headers, body


def dispatch(
    method: str, path: str, query: dict
) -> tuple[int, dict, bytes]:
    """Route a request and return (status, headers, body_bytes).

    If a path pattern matches but the method does not, returns 405. If no
    pattern matches at all, returns 404.
    """
    matched_path = False
    matched_handler: Callable[..., tuple] | None = None
    matched_params: dict = {}
    matched_content_type: str | None = None

    for r_method, pattern, handler, content_type in _ROUTES:
        params = _try_match(pattern, path)
        if params is None:
            continue
        matched_path = True
        if r_method == method:
            matched_handler = handler
            matched_params = params
            matched_content_type = content_type
            break

    if matched_handler is None:
        return _error_response(405 if matched_path else 404,
                               "method_not_allowed" if matched_path else "not_found")

    status, body = matched_handler(path, query, **matched_params)

    if isinstance(body, (bytes, bytearray)):
        ctype = matched_content_type or _content_type_for(path)
        headers = {"Content-Type": ctype}
        body_bytes = bytes(body)
    elif isinstance(body, dict):
        body_bytes = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8"}
    else:
        return _error_response(500, "internal_error")

    headers["Content-Length"] = str(len(body_bytes))
    return status, headers, body_bytes
