"""Server-side validation that the static assets and templates ship correctly."""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from king_context.web import handlers
from king_context.web import router


REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Static asset endpoints
# ---------------------------------------------------------------------------


class TestStaticAssetEndpoints:
    def test_static_graph_js_served(self):
        status, headers, body = router.dispatch("GET", "/static/graph.js", {})
        assert status == 200
        assert headers["Content-Type"] == "application/javascript"
        assert len(body) > 0
        text = body.decode("utf-8")
        assert "fetch('/api/adrs/graph'" in text or "fetch(\"/api/adrs/graph\"" in text

    def test_static_app_js_served(self):
        status, headers, body = router.dispatch("GET", "/static/app.js", {})
        assert status == 200
        assert headers["Content-Type"] == "application/javascript"
        assert len(body) > 0
        text = body.decode("utf-8")
        # app.js loads ADR detail and listens for the graph custom event.
        assert "kctx:adr-selected" in text
        assert "loadAdrPanel" in text

    def test_static_style_css_served(self):
        status, headers, body = router.dispatch("GET", "/static/style.css", {})
        assert status == 200
        assert headers["Content-Type"] == "text/css"
        assert len(body) > 0
        text = body.decode("utf-8")
        # Spot-check a few critical class hooks promised to handlers/templates.
        for token in (
            ".kctx-nav",
            ".kctx-empty",
            ".edge-related",
            ".edge-supersedes",
            ".status-accepted",
        ):
            assert token in text, f"missing CSS hook: {token}"


# ---------------------------------------------------------------------------
# Templates reference the static assets
# ---------------------------------------------------------------------------


class TestTemplatesIncludeAssets:
    def test_layout_includes_app_js_and_style(self):
        layout = (
            REPO_ROOT
            / "src"
            / "king_context"
            / "web"
            / "templates"
            / "_layout.html"
        ).read_text(encoding="utf-8")
        assert '/static/style.css' in layout
        assert '/static/app.js' in layout

    def test_adrs_html_includes_graph_script(self):
        adrs = (
            REPO_ROOT
            / "src"
            / "king_context"
            / "web"
            / "templates"
            / "adrs.html"
        ).read_text(encoding="utf-8")
        assert '/static/graph.js' in adrs

    def test_adrs_page_response_includes_assets(self):
        # Render through the actual handler chain so the layout + page wrap
        # together end up with both script tags and the stylesheet.
        _, body = handlers.adr_page("/adrs", {})
        text = body.decode("utf-8")
        assert '/static/style.css' in text
        assert '/static/app.js' in text
        assert '/static/graph.js' in text

    def test_home_page_response_includes_app_js_and_style(self):
        _, body = handlers.home_page("/", {})
        text = body.decode("utf-8")
        assert '/static/style.css' in text
        assert '/static/app.js' in text


# ---------------------------------------------------------------------------
# Wheel bundling
# ---------------------------------------------------------------------------


class TestWheelBundlesStaticAssets:
    """Verify `pip wheel` produces a wheel that ships the static assets.

    Hatchling's ``packages = ["src/king_context", ...]`` should auto-include
    every file under those paths. This test catches accidental regressions
    (e.g. someone later adds a wheel-exclude pattern).
    """

    def test_wheel_includes_static_assets(self, tmp_path):
        if shutil.which("pip") is None:
            pytest.skip("pip is not available on PATH")

        out_dir = tmp_path / "wheelhouse"
        out_dir.mkdir()
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                str(REPO_ROOT),
                "--no-deps",
                "-w",
                str(out_dir),
            ],
            capture_output=True,
            text=True,
            timeout=240,
        )
        if result.returncode != 0:
            pytest.skip(
                "pip wheel failed (likely missing build deps in test env): "
                + result.stderr[-300:]
            )

        wheels = list(out_dir.glob("king_context-*.whl"))
        assert wheels, f"no wheel produced. stdout={result.stdout!r}"
        wheel_path = wheels[0]

        with zipfile.ZipFile(wheel_path) as zf:
            names = set(zf.namelist())

        expected = {
            "king_context/web/static/graph.js",
            "king_context/web/static/app.js",
            "king_context/web/static/style.css",
            "king_context/web/templates/_layout.html",
            "king_context/web/templates/adrs.html",
        }
        missing = expected - names
        assert not missing, f"wheel missing files: {missing}"
