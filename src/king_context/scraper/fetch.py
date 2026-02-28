import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

from firecrawl import FirecrawlApp

from king_context.scraper.config import ScraperConfig
from king_context.scraper.discover import _update_step


@dataclass
class PageResult:
    url: str
    markdown: str
    success: bool
    error: str | None


@dataclass
class FetchResult:
    total: int
    completed: int
    failed: int
    results: list[PageResult]


def _url_to_slug(url: str) -> str:
    slug = re.sub(r"^https?://", "", url)
    slug = re.sub(r"[^a-zA-Z0-9]", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:200]


async def _fetch_one(
    url: str,
    semaphore: asyncio.Semaphore,
    pages_dir: Path,
    app: FirecrawlApp,
) -> PageResult:
    async with semaphore:
        try:
            loop = asyncio.get_running_loop()
            raw = await loop.run_in_executor(None, lambda: app.scrape(url, formats=["markdown"]))
            markdown = raw.markdown if hasattr(raw, "markdown") else (raw.get("markdown", "") if isinstance(raw, dict) else str(raw))
            slug = _url_to_slug(url)
            (pages_dir / f"{slug}.md").write_text(markdown)
            return PageResult(url=url, markdown=markdown, success=True, error=None)
        except Exception as e:
            return PageResult(url=url, markdown="", success=False, error=str(e))


async def fetch_pages(
    urls: list[str],
    output_dir: Path,
    config: ScraperConfig,
) -> FetchResult:
    pages_dir = output_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    app = FirecrawlApp(api_key=config.firecrawl_api_key)
    semaphore = asyncio.Semaphore(config.concurrency)

    tasks = [_fetch_one(url, semaphore, pages_dir, app) for url in urls]
    results: list[PageResult] = list(await asyncio.gather(*tasks))

    completed = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)

    _update_step(output_dir, "fetch", {
        "status": "done",
        "total": len(urls),
        "completed": completed,
        "failed": failed,
    })

    return FetchResult(
        total=len(urls),
        completed=completed,
        failed=failed,
        results=results,
    )
