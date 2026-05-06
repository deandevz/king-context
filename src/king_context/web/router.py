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
    """Return path params if path matches pattern, else None."""
    if "{*" in pattern:
        prefix, _ = pattern.split("{*", 1)
        if path.startswith(prefix):
            return {"rest": path[len(prefix):]}
        return None
    if path == pattern:
        return {}
    return None


def _handle_health(path: str, query: dict, **_: object) -> tuple[int, dict]:
    """GET /api/health — server liveness and version probe."""
    return 200, {"status": "ok", "version": _resolve_version()}


def _handle_static(
    path: str, query: dict, *, rest: str = "", **_: object
) -> tuple[int, bytes] | tuple[int, dict]:
    """GET /static/{rest} — serve files from the bundled static directory.

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


_ROUTES: list[tuple[str, str, Callable[..., tuple]]] = [
    ("GET", "/api/health", _handle_health),
    ("GET", "/static/{*rest}", _handle_static),
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

    for r_method, pattern, handler in _ROUTES:
        params = _try_match(pattern, path)
        if params is None:
            continue
        matched_path = True
        if r_method == method:
            matched_handler = handler
            matched_params = params
            break

    if matched_handler is None:
        return _error_response(405 if matched_path else 404,
                               "method_not_allowed" if matched_path else "not_found")

    status, body = matched_handler(path, query, **matched_params)

    if isinstance(body, (bytes, bytearray)):
        headers = {"Content-Type": _content_type_for(path)}
        body_bytes = bytes(body)
    elif isinstance(body, dict):
        body_bytes = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8"}
    else:
        return _error_response(500, "internal_error")

    headers["Content-Length"] = str(len(body_bytes))
    return status, headers, body_bytes
