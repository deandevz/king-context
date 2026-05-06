import asyncio
import json

from king_context.scraper.discover import discover_urls, DiscoveryResult
from king_context.scraper.config import ScraperConfig


class _FakeDiscoveryProvider:
    name = "fake"

    def __init__(self, urls: list[str]):
        self._urls = urls

    async def discover_urls(self, base_url: str) -> list[str]:
        return self._urls


def test_discover_urls(tmp_path, monkeypatch):
    monkeypatch.setattr("king_context.scraper.discover.TEMP_DOCS_DIR", tmp_path)

    provider = _FakeDiscoveryProvider([
        "https://docs.example.com/api",
        "https://docs.example.com/guide",
    ])

    result = asyncio.run(
        discover_urls(
            "https://docs.example.com",
            ScraperConfig(firecrawl_api_key="fc-test"),
            provider,
        )
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

    provider = _FakeDiscoveryProvider([])

    asyncio.run(
        discover_urls(
            "https://docs.example.com",
            ScraperConfig(firecrawl_api_key="fc-test"),
            provider,
        )
    )

    work_dir = tmp_path / "docs-example-com"
    assert work_dir.exists()
    assert work_dir.is_dir()
