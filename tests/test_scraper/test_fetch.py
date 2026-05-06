import asyncio
import json
import threading
from unittest.mock import patch, MagicMock, AsyncMock

from king_context.scraper.fetch import fetch_pages, FetchResult
from king_context.scraper.config import ScraperConfig


def test_fetch_pages_success(tmp_path):
    config = ScraperConfig(firecrawl_api_key="fc-test")

    mock_app = MagicMock()
    mock_app.scrape.return_value = {"markdown": "# Page Content"}

    urls = [
        "https://docs.example.com/api/intro",
        "https://docs.example.com/guide/start",
    ]

    with patch("king_context.scraper.fetch.FirecrawlApp", return_value=mock_app):
        with patch(
            "king_context.scraper.fetch.probe_url_state",
            new_callable=AsyncMock,
            return_value={"ok": True, "etag": '"abc"', "last_modified": "Mon, 01 Jan 2026 00:00:00 GMT", "probe_hash": None, "content_length": 123},
        ):
            result = asyncio.run(fetch_pages(urls, tmp_path, config))

    assert isinstance(result, FetchResult)
    assert result.total == 2
    assert result.completed == 2
    assert result.failed == 0

    pages_dir = tmp_path / "pages"
    assert pages_dir.exists()
    md_files = list(pages_dir.glob("*.md"))
    assert len(md_files) == 2


def test_fetch_handles_failure(tmp_path):
    config = ScraperConfig(firecrawl_api_key="fc-test")

    def side_effect(url, **kwargs):
        if "failing" in url:
            raise RuntimeError("Network error")
        return {"markdown": "# Good Page"}

    mock_app = MagicMock()
    mock_app.scrape.side_effect = side_effect

    urls = [
        "https://docs.example.com/api/good",
        "https://docs.example.com/failing/page",
    ]

    with patch("king_context.scraper.fetch.FirecrawlApp", return_value=mock_app):
        with patch(
            "king_context.scraper.fetch.probe_url_state",
            new_callable=AsyncMock,
            return_value={"ok": True, "etag": None, "last_modified": None, "probe_hash": "bodyhash", "content_length": 12},
        ):
            result = asyncio.run(fetch_pages(urls, tmp_path, config))

    assert result.total == 2
    assert result.completed == 1
    assert result.failed == 1
    assert any(r.success for r in result.results)
    assert any(not r.success for r in result.results)


def test_fetch_respects_concurrency(tmp_path):
    config = ScraperConfig(firecrawl_api_key="fc-test", concurrency=2)

    lock = threading.Lock()
    active = {"count": 0, "max": 0}

    def slow_scrape(url):
        import time
        with lock:
            active["count"] += 1
            active["max"] = max(active["max"], active["count"])
        time.sleep(0.05)
        with lock:
            active["count"] -= 1
        return {"markdown": "# Content"}

    mock_app = MagicMock()
    mock_app.scrape.side_effect = slow_scrape

    urls = [f"https://docs.example.com/page-{i}" for i in range(6)]

    with patch("king_context.scraper.fetch.FirecrawlApp", return_value=mock_app):
        with patch(
            "king_context.scraper.fetch.probe_url_state",
            new_callable=AsyncMock,
            return_value={"ok": True, "etag": '"etag"', "last_modified": None, "probe_hash": None, "content_length": 10},
        ):
            asyncio.run(fetch_pages(urls, tmp_path, config))

    assert active["max"] <= 2


def test_fetch_updates_manifest(tmp_path):
    config = ScraperConfig(firecrawl_api_key="fc-test")

    mock_app = MagicMock()
    mock_app.scrape.return_value = {"markdown": "# Content"}

    urls = ["https://docs.example.com/api/intro"]

    with patch("king_context.scraper.fetch.FirecrawlApp", return_value=mock_app):
        with patch(
            "king_context.scraper.fetch.probe_url_state",
            new_callable=AsyncMock,
            return_value={"ok": True, "etag": None, "last_modified": None, "probe_hash": "bodyhash", "content_length": 10},
        ):
            asyncio.run(fetch_pages(urls, tmp_path, config))

    manifest_path = tmp_path / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert "fetch" in manifest
    assert manifest["fetch"]["completed"] == 1
    assert manifest["fetch"]["total"] == 1
    page_manifest = json.loads((tmp_path / "page_manifest.json").read_text())
    assert page_manifest["page_count"] == 1
