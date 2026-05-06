"""Local UI HTTP server.

Thin adapter on top of stdlib http.server. Exposes ``main()`` as the entry
point invoked by ``kctx ui``. All routing and rendering lives in
``king_context.web.router``; this module is responsible only for parsing
CLI flags, picking a free port, opening the browser, and translating between
``BaseHTTPRequestHandler`` and ``router.dispatch``.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from king_context.web import router


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7373
PORT_SPAN = 20


# Test hooks: tests can wait on _server_ready and call _active_server.shutdown()
# to stop a server started via main() in a background thread.
_server_ready = threading.Event()
_active_server: HTTPServer | None = None


def find_free_port(host: str, start: int, span: int = PORT_SPAN) -> int:
    """Return the first free port in ``[start, start + span)``.

    Tries to bind each candidate. Releases the socket immediately after a
    successful bind. Raises OSError with a hint suggesting ``--port`` if no
    port in the range is free.
    """
    last_err: Exception | None = None
    for port in range(start, start + span):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((host, port))
        except OSError as exc:
            last_err = exc
            continue
        finally:
            sock.close()
        return port
    raise OSError(
        f"No free port found in range {start}-{start + span - 1}. "
        "Try `kctx ui --port <PORT>` to override."
    ) from last_err


class WebRequestHandler(BaseHTTPRequestHandler):
    """Bridge between BaseHTTPRequestHandler and router.dispatch."""

    server_version = "KingContextUI/0.1"

    def _handle(self, method: str) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        try:
            status, headers, body = router.dispatch(method, parsed.path, query)
        except Exception:
            body = b'{"error":"internal_error"}'
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._handle("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._handle("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._handle("DELETE")

    def do_PATCH(self) -> None:  # noqa: N802
        self._handle("PATCH")

    def do_HEAD(self) -> None:  # noqa: N802
        self._handle("HEAD")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._handle("OPTIONS")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        sys.stderr.write(f"[king-context-ui] {format % args}\n")


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kctx ui", add_help=True)
    parser.add_argument("--port", type=int, default=None,
                        help="Port to bind (default: 7373; auto-increment if busy)")
    parser.add_argument("--host", default=None,
                        help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--no-open", action="store_true",
                        help="Do not open the browser automatically")
    return parser


def _resolve_start_port(args: argparse.Namespace) -> int | None:
    if args.port is not None:
        return args.port
    env_port = os.environ.get("KCTX_UI_PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            sys.stderr.write(f"Invalid KCTX_UI_PORT: {env_port!r}\n")
            return None
    return DEFAULT_PORT


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    global _active_server

    args = _build_argparser().parse_args(argv)

    host = args.host or DEFAULT_HOST
    if host == "0.0.0.0":
        sys.stderr.write(
            "Bind to 0.0.0.0 requires --confirm-public (not supported in MVP).\n"
        )
        return 2

    start_port = _resolve_start_port(args)
    if start_port is None:
        return 2

    try:
        port = find_free_port(host, start_port)
    except OSError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2

    try:
        httpd = HTTPServer((host, port), WebRequestHandler)
    except OSError as exc:
        sys.stderr.write(f"Failed to bind {host}:{port}: {exc}\n")
        return 2

    bound_port = httpd.server_address[1]
    url = f"http://{host}:{bound_port}"
    print(f"King Context UI on {url} (Ctrl+C to stop)", flush=True)

    if not args.no_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    _active_server = httpd
    _server_ready.set()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _server_ready.clear()
        _active_server = None
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
