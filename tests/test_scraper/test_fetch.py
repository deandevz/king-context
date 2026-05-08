import asyncio
import json
import threading
from datetime import datetime, timezone

from scraper_providers import PageContent

from king_context.scraper.fetch import fetch_pages, FetchResult
from king_context.scraper.config import ScraperConfig


def _page(url: str, markdown: str = "# Page Content") -> PageContent:
    return PageContent(
        url=url,
        markdown=markdown,
        title=None,
        fetched_at=datetime.now(timezone.utc),
    )


class _FakeFetchProvider:
    name = "fake"

    def __init__(self, side_effect=None, fixed_markdown: str = "# Content"):
        self._side_effect = side_effect
        self._fixed_markdown = fixed_markdown

    async def fetch_one(self, url: str) -> PageContent:
        if self._side_effect is not None:
            return self._side_effect(url)
        return _page(url, self._fixed_markdown)


def test_fetch_pages_success(tmp_path):
    config = ScraperConfig(firecrawl_api_key="fc-test")
    provider = _FakeFetchProvider(fixed_markdown="# Page Content")

    urls = [
        "https://docs.example.com/api/intro",
        "https://docs.example.com/guide/start",
    ]

    result = asyncio.run(fetch_pages(urls, tmp_path, config, provider))

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

    def side_effect(url: str) -> PageContent:
        if "failing" in url:
            raise RuntimeError("Network error")
        return _page(url, "# Good Page")

    provider = _FakeFetchProvider(side_effect=side_effect)

    urls = [
        "https://docs.example.com/api/good",
        "https://docs.example.com/failing/page",
    ]

    result = asyncio.run(fetch_pages(urls, tmp_path, config, provider))

    assert result.total == 2
    assert result.completed == 1
    assert result.failed == 1
    assert any(r.success for r in result.results)
    assert any(not r.success for r in result.results)


def test_fetch_respects_concurrency(tmp_path):
    config = ScraperConfig(firecrawl_api_key="fc-test", concurrency=2)

    lock = threading.Lock()
    active = {"count": 0, "max": 0}

    class _SlowProvider:
        name = "slow-fake"

        async def fetch_one(self, url: str) -> PageContent:
            with lock:
                active["count"] += 1
                active["max"] = max(active["max"], active["count"])
            await asyncio.sleep(0.05)
            with lock:
                active["count"] -= 1
            return _page(url)

    urls = [f"https://docs.example.com/page-{i}" for i in range(6)]

    asyncio.run(fetch_pages(urls, tmp_path, config, _SlowProvider()))

    assert active["max"] <= 2


def test_fetch_updates_manifest(tmp_path):
    config = ScraperConfig(firecrawl_api_key="fc-test")
    provider = _FakeFetchProvider()

    urls = ["https://docs.example.com/api/intro"]

    asyncio.run(fetch_pages(urls, tmp_path, config, provider))

    manifest_path = tmp_path / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert "fetch" in manifest
    assert manifest["fetch"]["completed"] == 1
    assert manifest["fetch"]["total"] == 1


def test_fetch_writes_page_meta_sidecar(tmp_path):
    config = ScraperConfig(firecrawl_api_key="fc-test")
    provider = _FakeFetchProvider(fixed_markdown="# Hello\n\nbody")

    urls = ["https://docs.example.com/api/intro"]
    asyncio.run(fetch_pages(urls, tmp_path, config, provider))

    pages_dir = tmp_path / "pages"
    md_files = list(pages_dir.glob("*.md"))
    assert len(md_files) == 1

    sidecars = list(pages_dir.glob("*.meta.json"))
    assert len(sidecars) == 1

    meta = json.loads(sidecars[0].read_text())
    assert meta["url"] == urls[0]
    assert meta["slug"] == md_files[0].stem
    assert len(meta["content_hash"]) == 64
    assert meta["byte_size"] == len("# Hello\n\nbody".encode("utf-8"))
    assert "fetched_at" in meta
