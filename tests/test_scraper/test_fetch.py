import asyncio
import json
import threading
from unittest.mock import patch, MagicMock

from king_context.scraper.fetch import fetch_pages, FetchResult
from king_context.scraper.config import ScraperConfig


def test_fetch_pages_success(tmp_path):
    config = ScraperConfig(firecrawl_api_key="fc-test")

    mock_app = MagicMock()
    mock_app.scrape_url.return_value = {"markdown": "# Page Content"}

    urls = [
        "https://docs.example.com/api/intro",
        "https://docs.example.com/guide/start",
    ]

    with patch("king_context.scraper.fetch.FirecrawlApp", return_value=mock_app):
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

    def side_effect(url):
        if "failing" in url:
            raise RuntimeError("Network error")
        return {"markdown": "# Good Page"}

    mock_app = MagicMock()
    mock_app.scrape_url.side_effect = side_effect

    urls = [
        "https://docs.example.com/api/good",
        "https://docs.example.com/failing/page",
    ]

    with patch("king_context.scraper.fetch.FirecrawlApp", return_value=mock_app):
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
    mock_app.scrape_url.side_effect = slow_scrape

    urls = [f"https://docs.example.com/page-{i}" for i in range(6)]

    with patch("king_context.scraper.fetch.FirecrawlApp", return_value=mock_app):
        asyncio.run(fetch_pages(urls, tmp_path, config))

    assert active["max"] <= 2


def test_fetch_updates_manifest(tmp_path):
    config = ScraperConfig(firecrawl_api_key="fc-test")

    mock_app = MagicMock()
    mock_app.scrape_url.return_value = {"markdown": "# Content"}

    urls = ["https://docs.example.com/api/intro"]

    with patch("king_context.scraper.fetch.FirecrawlApp", return_value=mock_app):
        asyncio.run(fetch_pages(urls, tmp_path, config))

    manifest_path = tmp_path / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert "fetch" in manifest
    assert manifest["fetch"]["completed"] == 1
    assert manifest["fetch"]["total"] == 1
