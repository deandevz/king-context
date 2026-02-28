import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from firecrawl import FirecrawlApp

from king_context import PROJECT_ROOT
from king_context.scraper.config import ScraperConfig


TEMP_DOCS_DIR = PROJECT_ROOT / ".temp-docs"


@dataclass
class DiscoveryResult:
    base_url: str
    discovered_at: str
    total_urls: int
    urls: list[str]


def _get_work_dir_name(base_url: str) -> str:
    parsed = urlparse(base_url)
    hostname = parsed.netloc or parsed.path
    name = hostname.replace(".", "-").replace(":", "-").replace("/", "-").strip("-")
    return name or "unknown"


def get_work_dir(base_url: str) -> Path:
    return TEMP_DOCS_DIR / _get_work_dir_name(base_url)


def _load_manifest(work_dir: Path) -> dict:
    manifest_path = work_dir / "manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text())
    return {}


def _save_manifest(work_dir: Path, manifest: dict) -> None:
    manifest_path = work_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))


def _update_step(work_dir: Path, step: str, stats: dict) -> None:
    manifest = _load_manifest(work_dir)
    manifest[step] = stats
    _save_manifest(work_dir, manifest)


async def discover_urls(base_url: str, config: ScraperConfig) -> DiscoveryResult:
    work_dir = get_work_dir(base_url)
    work_dir.mkdir(parents=True, exist_ok=True)

    app = FirecrawlApp(api_key=config.firecrawl_api_key)
    loop = asyncio.get_running_loop()
    raw = await loop.run_in_executor(None, lambda: app.map_url(base_url))
    urls = raw if isinstance(raw, list) else raw.get("links", [])

    discovered_at = datetime.now(timezone.utc).isoformat()
    result = DiscoveryResult(
        base_url=base_url,
        discovered_at=discovered_at,
        total_urls=len(urls),
        urls=urls,
    )

    (work_dir / "discovered_urls.json").write_text(
        json.dumps(
            {
                "base_url": base_url,
                "discovered_at": discovered_at,
                "total_urls": len(urls),
                "urls": urls,
            },
            indent=2,
        )
    )

    _update_step(work_dir, "discovery", {
        "status": "done",
        "total_urls": len(urls),
        "discovered_at": discovered_at,
    })

    return result
