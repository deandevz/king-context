"""Tests for king_context.web (server, router, handlers)."""

from __future__ import annotations

import json
import socket
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from king_context.web import router
from king_context.web import server as web_server


# ---------------------------------------------------------------------------
# find_free_port
# ---------------------------------------------------------------------------


class TestFindFreePort:
    def test_returns_default_when_free(self):
        # Use an ephemeral range very unlikely to be in use.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        free_port = sock.getsockname()[1]
        sock.close()
        # Now `free_port` should be free again.
        port = web_server.find_free_port("127.0.0.1", free_port, span=1)
        assert port == free_port

    def test_increments_when_busy(self):
        # Bind a port to mark it busy, then ask find_free_port to start there.
        busy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        busy.bind(("127.0.0.1", 0))
        busy_port = busy.getsockname()[1]
        try:
            port = web_server.find_free_port("127.0.0.1", busy_port, span=20)
            assert port != busy_port
            assert busy_port < port < busy_port + 20
        finally:
            busy.close()

    def test_raises_when_range_exhausted(self):
        # Bind two consecutive ports, then ask find_free_port for span=2 starting
        # from the first. Both candidates are busy, so it must raise.
        s1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s1.bind(("127.0.0.1", 0))
        p1 = s1.getsockname()[1]

        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s2.bind(("127.0.0.1", p1 + 1))
        except OSError:
            # If the next port is not free for unrelated reasons, skip this test.
            s1.close()
            s2.close()
            pytest.skip("Could not reserve consecutive ports for the test.")

        try:
            with pytest.raises(OSError, match="No free port"):
                web_server.find_free_port("127.0.0.1", p1, span=2)
        finally:
            s1.close()
            s2.close()


# ---------------------------------------------------------------------------
# router.dispatch — health and not_found
# ---------------------------------------------------------------------------


class TestRouterHealth:
    def test_health_endpoint(self):
        status, headers, body = router.dispatch("GET", "/api/health", {})
        assert status == 200
        assert headers["Content-Type"] == "application/json; charset=utf-8"
        payload = json.loads(body)
        assert payload["status"] == "ok"
        assert isinstance(payload["version"], str)

    def test_unknown_path_returns_404(self):
        status, _, body = router.dispatch("GET", "/api/unknown", {})
        assert status == 404
        payload = json.loads(body)
        assert payload == {"error": "not_found"}

    def test_post_to_known_path_returns_405(self):
        status, _, body = router.dispatch("POST", "/api/health", {})
        assert status == 405
        payload = json.loads(body)
        assert payload == {"error": "method_not_allowed"}


# ---------------------------------------------------------------------------
# router.dispatch — static handler
# ---------------------------------------------------------------------------


class TestStaticHandler:
    def test_serves_placeholder(self):
        status, headers, body = router.dispatch(
            "GET", "/static/placeholder.txt", {}
        )
        assert status == 200
        assert headers["Content-Type"] == "text/plain"
        assert b"static asset server reachable" in body

    def test_blocks_path_traversal(self):
        status, _, body = router.dispatch(
            "GET", "/static/../etc/passwd", {}
        )
        assert status == 404
        assert json.loads(body) == {"error": "not_found"}

    def test_blocks_url_encoded_traversal(self):
        # %2E%2E decodes to ".."
        status, _, _ = router.dispatch(
            "GET", "/static/%2E%2E/etc/passwd", {}
        )
        assert status == 404

    def test_blocks_absolute_path(self):
        status, _, _ = router.dispatch(
            "GET", "/static//etc/passwd", {}
        )
        assert status == 404

    def test_returns_404_for_missing_file(self):
        status, _, body = router.dispatch(
            "GET", "/static/does-not-exist.txt", {}
        )
        assert status == 404
        assert json.loads(body) == {"error": "not_found"}

    def test_sets_content_type_by_extension(self, tmp_path, monkeypatch):
        # Build a temp static dir with a few extensions and re-point router.
        (tmp_path / "a.css").write_text("body{}")
        (tmp_path / "a.js").write_text("var x=1;")
        (tmp_path / "a.html").write_text("<html></html>")
        (tmp_path / "a.svg").write_text("<svg></svg>")
        (tmp_path / "a.json").write_text("{}")
        (tmp_path / "a.bin").write_bytes(b"\x00\x01\x02")

        monkeypatch.setattr(router, "_STATIC_DIR", tmp_path)

        cases = {
            "/static/a.css": "text/css",
            "/static/a.js": "application/javascript",
            "/static/a.html": "text/html",
            "/static/a.svg": "image/svg+xml",
            "/static/a.json": "application/json",
            "/static/a.bin": "application/octet-stream",
        }
        for path, expected in cases.items():
            status, headers, _ = router.dispatch("GET", path, {})
            assert status == 200, f"failed for {path}"
            assert headers["Content-Type"] == expected, f"failed for {path}"


# ---------------------------------------------------------------------------
# Integration: main() + real HTTP request
# ---------------------------------------------------------------------------


@pytest.fixture
def running_server():
    """Start web_server.main() in a thread bound to an ephemeral port. Yield base URL."""
    web_server._server_ready.clear()

    thread = threading.Thread(
        target=web_server.main,
        args=(["--no-open", "--port", "0", "--host", "127.0.0.1"],),
        daemon=True,
    )
    thread.start()

    if not web_server._server_ready.wait(timeout=5):
        pytest.fail("Server did not become ready in time")

    httpd = web_server._active_server
    assert httpd is not None
    host, port = httpd.server_address[0], httpd.server_address[1]
    base_url = f"http://{host}:{port}"

    try:
        yield base_url
    finally:
        if web_server._active_server is not None:
            web_server._active_server.shutdown()
        thread.join(timeout=5)


class TestMainIntegration:
    def test_main_starts_and_serves_health(self, running_server):
        with urlopen(f"{running_server}/api/health", timeout=5) as resp:
            assert resp.status == 200
            ctype = resp.headers.get("Content-Type", "")
            assert "application/json" in ctype
            payload = json.loads(resp.read().decode("utf-8"))
            assert payload["status"] == "ok"
            assert isinstance(payload["version"], str)

    def test_main_serves_static_placeholder(self, running_server):
        with urlopen(f"{running_server}/static/placeholder.txt", timeout=5) as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Type") == "text/plain"
            assert b"static asset server reachable" in resp.read()

    def test_main_returns_404_for_unknown(self, running_server):
        with pytest.raises(HTTPError) as exc:
            urlopen(f"{running_server}/api/unknown", timeout=5)
        assert exc.value.code == 404

    def test_main_returns_405_for_post(self, running_server):
        req = Request(
            f"{running_server}/api/health", data=b"", method="POST"
        )
        with pytest.raises(HTTPError) as exc:
            urlopen(req, timeout=5)
        assert exc.value.code == 405

    def test_main_handles_query_with_special_chars(self, running_server):
        # Edge case: special characters in query string don't crash the adapter.
        with urlopen(
            f"{running_server}/api/health?foo=%20bar&baz=a%2Bb", timeout=5
        ) as resp:
            assert resp.status == 200

    def test_main_rejects_zero_zero_zero_zero_bind(self, capsys):
        rc = web_server.main(["--host", "0.0.0.0", "--no-open"])
        assert rc == 2
        captured = capsys.readouterr()
        assert "0.0.0.0" in captured.err
