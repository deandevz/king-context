"""Tests for fetch resume support — skip pages already fetched."""

from unittest.mock import AsyncMock, patch

import pytest

from king_context.scraper.config import ScraperConfig
from king_context.scraper.fetch import (
    FetchResult,
    PageResult,
    _url_to_slug,
    fetch_pages,
)


def _make_config() -> ScraperConfig:
    return ScraperConfig(
        firecrawl_api_key="fake",
        openrouter_api_key="fake",
        concurrency=5,
    )


def _create_page_file(pages_dir, url: str) -> None:
    """Create a .md file in pages_dir matching the slug of the given URL."""
    slug = _url_to_slug(url)
    (pages_dir / f"{slug}.md").write_text(f"# Pre-existing content for {url}")


class TestFetchResume:
    """fetch_pages skips URLs whose page files already exist."""

    @pytest.mark.asyncio
    async def test_partial_resume_only_fetches_remaining(self, tmp_path):
        """If pages/ has some .md files matching URL slugs, only remaining URLs get fetched."""
        pages_dir = tmp_path / "pages"
        pages_dir.mkdir(parents=True)

        urls = [
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
        ]

        # Pre-create page for the first URL
        _create_page_file(pages_dir, urls[0])

        config = _make_config()
        fetched_urls = []

        async def _mock_fetch_one(url, semaphore, pages_dir, app):
            fetched_urls.append(url)
            return PageResult(url=url, markdown=f"# {url}", success=True, error=None)

        with patch(
            "king_context.scraper.fetch._fetch_one",
            new_callable=AsyncMock,
            side_effect=_mock_fetch_one,
        ), patch(
            "king_context.scraper.fetch._update_step",
        ), patch(
            "king_context.scraper.fetch.FirecrawlApp",
        ):
            result = await fetch_pages(urls, tmp_path, config)

        # Only URLs b and c should have been fetched
        assert len(fetched_urls) == 2
        assert urls[0] not in fetched_urls
        assert urls[1] in fetched_urls
        assert urls[2] in fetched_urls

    @pytest.mark.asyncio
    async def test_full_resume_no_fetch_needed(self, tmp_path):
        """If all URLs already have .md files, fetch returns immediately with correct counts."""
        pages_dir = tmp_path / "pages"
        pages_dir.mkdir(parents=True)

        urls = [
            "https://example.com/a",
            "https://example.com/b",
        ]

        # Pre-create pages for all URLs
        for url in urls:
            _create_page_file(pages_dir, url)

        config = _make_config()
        fetch_one_mock = AsyncMock()

        with patch(
            "king_context.scraper.fetch._fetch_one",
            fetch_one_mock,
        ), patch(
            "king_context.scraper.fetch._update_step",
        ), patch(
            "king_context.scraper.fetch.FirecrawlApp",
        ):
            result = await fetch_pages(urls, tmp_path, config)

        # _fetch_one should never have been called
        fetch_one_mock.assert_not_called()

        # Counts should reflect all pages as completed
        assert result.total == 2
        assert result.completed == 2
        assert result.failed == 0
        assert result.results == []

    @pytest.mark.asyncio
    async def test_fresh_start_fetches_all(self, tmp_path):
        """If pages/ is empty, all URLs get fetched."""
        urls = [
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
        ]

        config = _make_config()
        fetched_urls = []

        async def _mock_fetch_one(url, semaphore, pages_dir, app):
            fetched_urls.append(url)
            return PageResult(url=url, markdown=f"# {url}", success=True, error=None)

        with patch(
            "king_context.scraper.fetch._fetch_one",
            new_callable=AsyncMock,
            side_effect=_mock_fetch_one,
        ), patch(
            "king_context.scraper.fetch._update_step",
        ), patch(
            "king_context.scraper.fetch.FirecrawlApp",
        ):
            result = await fetch_pages(urls, tmp_path, config)

        # All 3 URLs should have been fetched
        assert len(fetched_urls) == 3
        assert result.total == 3
        assert result.completed == 3
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_correct_counts_include_preexisting(self, tmp_path):
        """FetchResult.completed includes pre-existing + newly fetched pages."""
        pages_dir = tmp_path / "pages"
        pages_dir.mkdir(parents=True)

        urls = [
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
            "https://example.com/d",
        ]

        # Pre-create pages for first two URLs
        _create_page_file(pages_dir, urls[0])
        _create_page_file(pages_dir, urls[1])

        config = _make_config()

        async def _mock_fetch_one(url, semaphore, pages_dir, app):
            return PageResult(url=url, markdown=f"# {url}", success=True, error=None)

        with patch(
            "king_context.scraper.fetch._fetch_one",
            new_callable=AsyncMock,
            side_effect=_mock_fetch_one,
        ), patch(
            "king_context.scraper.fetch._update_step",
        ), patch(
            "king_context.scraper.fetch.FirecrawlApp",
        ):
            result = await fetch_pages(urls, tmp_path, config)

        # total = all 4 URLs
        assert result.total == 4
        # completed = 2 pre-existing + 2 newly fetched
        assert result.completed == 4
        assert result.failed == 0
        # results list only contains newly fetched pages
        assert len(result.results) == 2
        result_urls = {r.url for r in result.results}
        assert result_urls == {"https://example.com/c", "https://example.com/d"}

    @pytest.mark.asyncio
    async def test_resume_prints_summary(self, tmp_path, capsys):
        """When pages are skipped, a resume summary is printed to stdout."""
        pages_dir = tmp_path / "pages"
        pages_dir.mkdir(parents=True)

        urls = [
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
        ]

        # Pre-create page for first URL
        _create_page_file(pages_dir, urls[0])

        config = _make_config()

        async def _mock_fetch_one(url, semaphore, pages_dir, app):
            return PageResult(url=url, markdown=f"# {url}", success=True, error=None)

        with patch(
            "king_context.scraper.fetch._fetch_one",
            new_callable=AsyncMock,
            side_effect=_mock_fetch_one,
        ), patch(
            "king_context.scraper.fetch._update_step",
        ), patch(
            "king_context.scraper.fetch.FirecrawlApp",
        ):
            await fetch_pages(urls, tmp_path, config)

        captured = capsys.readouterr()
        assert "Resuming: 1 pages already fetched, 2 remaining" in captured.out
