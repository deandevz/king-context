import json
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path

from king_context import seed_data
from king_context.scraper.enrich import EnrichedChunk


CORPUS_SCHEMA_VERSION = 1


def _sanitize_path(path: str) -> str:
    """Sanitize section path for filesystem safety — replace / with - to avoid subdirs."""
    return path.replace("/", "-").strip("-")


def _scraper_version() -> str:
    try:
        return _pkg_version("king-context")
    except PackageNotFoundError:
        return "unknown"


def export_to_json(
    enriched_chunks: list[EnrichedChunk],
    doc_name: str,
    display_name: str,
    base_url: str,
    version: str = "v1",
) -> dict:
    """Build a King Context documentation dict from enriched chunks.

    The returned dict matches the schema expected by seed_data.seed_one(). The
    optional ``_meta`` fields carry provenance (content hashes, scrape timestamp,
    scraper version) used by drift detection and incremental refresh; consumers
    that don't recognise them ignore them.
    """
    sections = [
        {
            "title": chunk.title,
            "path": _sanitize_path(chunk.path),
            "url": chunk.url,
            "keywords": chunk.keywords,
            "use_cases": chunk.use_cases,
            "tags": chunk.tags,
            "priority": chunk.priority,
            "content": chunk.content,
            "_meta": {
                "content_hash": chunk.content_hash,
            },
        }
        for chunk in enriched_chunks
    ]
    return {
        "name": doc_name,
        "display_name": display_name,
        "version": version,
        "base_url": base_url,
        "sections": sections,
        "_meta": {
            "schema_version": CORPUS_SCHEMA_VERSION,
            "scraper_version": _scraper_version(),
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "source_url": base_url,
            "section_count": len(sections),
        },
    }


def save_and_index(doc_data: dict, output_path: Path, auto_seed: bool = True) -> None:
    """Save doc_data as JSON to output_path and optionally index into the database."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(doc_data, indent=2, ensure_ascii=False))
    if auto_seed:
        seed_data.seed_one(output_path)
