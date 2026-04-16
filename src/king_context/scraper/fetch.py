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

    existing_slugs = {f.stem for f in pages_dir.glob("*.md")}
    pending_urls = [u for u in urls if _url_to_slug(u) not in existing_slugs]
    skipped = len(urls) - len(pending_urls)

    if skipped > 0:
        print(f"Resuming: {skipped} pages already fetched, {len(pending_urls)} remaining")

    app = FirecrawlApp(api_key=config.firecrawl_api_key)
    semaphore = asyncio.Semaphore(config.concurrency)

    total = len(urls)
    progress = {"completed": skipped, "failed": 0}

    async def _fetch_and_track(url: str) -> PageResult:
        result = await _fetch_one(url, semaphore, pages_dir, app)
        if result.success:
            progress["completed"] += 1
        else:
            progress["failed"] += 1
        _update_step(output_dir, "fetch", {
            "status": "in_progress",
            "total": total,
            "completed": progress["completed"],
            "failed": progress["failed"],
        })
        return result

    tasks = [_fetch_and_track(url) for url in pending_urls]
    results: list[PageResult] = list(await asyncio.gather(*tasks))

    completed = progress["completed"]
    failed = progress["failed"]

    _update_step(output_dir, "fetch", {
        "status": "done",
        "total": total,
        "completed": completed,
        "failed": failed,
    })

    return FetchResult(
        total=total,
        completed=completed,
        failed=failed,
        results=results,
    )
