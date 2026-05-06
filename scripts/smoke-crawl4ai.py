#!/usr/bin/env python
"""Smoke test for the Crawl4AI scraper provider.

Run after `pip install -e ".[crawl4ai,dev]" && crawl4ai-setup`.
Manual only — not wired to CI by this task (Task 5 covers gated CI).
"""
from __future__ import annotations

import asyncio

from scraper_providers import get_discovery_provider, get_fetch_provider


async def main() -> None:
    fp = get_fetch_provider("crawl4ai")
    page = await fp.fetch_one("https://example.com")
    print(f"fetch ok — url={page.url} markdown_len={len(page.markdown)} title={page.title!r}")

    dp = get_discovery_provider("crawl4ai")
    urls = await dp.discover_urls("https://example.com")
    print(f"discover ok — found {len(urls)} urls")


if __name__ == "__main__":
    asyncio.run(main())
