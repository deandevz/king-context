import asyncio
import json
from unittest.mock import patch, MagicMock

from king_context.scraper.discover import discover_urls, DiscoveryResult
from king_context.scraper.config import ScraperConfig


def test_discover_urls(tmp_path, monkeypatch):
    monkeypatch.setattr("king_context.scraper.discover.TEMP_DOCS_DIR", tmp_path)

    mock_app = MagicMock()
    mock_app.map_url.return_value = [
        "https://docs.example.com/api",
        "https://docs.example.com/guide",
    ]

    with patch("king_context.scraper.discover.FirecrawlApp", return_value=mock_app):
        result = asyncio.run(
            discover_urls("https://docs.example.com", ScraperConfig(firecrawl_api_key="fc-test"))
        )

    assert isinstance(result, DiscoveryResult)
    assert result.base_url == "https://docs.example.com"
    assert result.total_urls == 2
    assert len(result.urls) == 2

    work_dir = tmp_path / "docs-example-com"
    assert (work_dir / "discovered_urls.json").exists()
    data = json.loads((work_dir / "discovered_urls.json").read_text())
    assert data["total_urls"] == 2
    assert data["base_url"] == "https://docs.example.com"


def test_discover_creates_work_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("king_context.scraper.discover.TEMP_DOCS_DIR", tmp_path)

    mock_app = MagicMock()
    mock_app.map_url.return_value = []

    with patch("king_context.scraper.discover.FirecrawlApp", return_value=mock_app):
        asyncio.run(
            discover_urls("https://docs.example.com", ScraperConfig(firecrawl_api_key="fc-test"))
        )

    work_dir = tmp_path / "docs-example-com"
    assert work_dir.exists()
    assert work_dir.is_dir()
