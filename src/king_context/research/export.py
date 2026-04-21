from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from king_context import PROJECT_ROOT
from king_context.scraper.enrich import EnrichedChunk
from king_context.scraper.export import _sanitize_path, export_to_json
from king_context.research.fetch import SourceDoc

log = logging.getLogger(__name__)

RESEARCH_DATA_DIR = PROJECT_ROOT / ".king-context" / "data" / "research"


def _slugify(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    s = _sanitize_path(s)
    return s[:40] or "research"


def _parse_authors(author: str | None) -> list[str] | None:
    if not author:
        return None
    author = author.strip()
    if not author:
        return None
    if "," in author:
        parts = [p.strip() for p in author.split(",")]
        parts = [p for p in parts if p]
        return parts or None
    return [author]


def _apply_research_fields(
    section: dict, sources_by_url: dict[str, SourceDoc]
) -> None:
    section["source_type"] = "research"
    source = sources_by_url.get(section["url"])
    if source is None:
        return

    authors = _parse_authors(source.author)
    if authors:
        section["authors"] = authors

    if source.published_date:
        section["published_date"] = source.published_date

    section["domain"] = source.domain
    section["discovery_iteration"] = source.discovery_iteration


def export_research_to_json(
    enriched: list[EnrichedChunk],
    sources_by_url: dict[str, SourceDoc],
    topic_slug: str,
    topic: str,
    base_url: str | None = None,
) -> Path:
    """Export enriched research chunks to .king-context/data/research/<slug>.json."""
    slug = _slugify(topic_slug)

    doc = export_to_json(
        enriched,
        doc_name=slug,
        display_name=topic,
        base_url=base_url or "",
        version="v1",
    )

    for section in doc["sections"]:
        _apply_research_fields(section, sources_by_url)

    RESEARCH_DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RESEARCH_DATA_DIR / f"{slug}.json"

    if output_path.exists():
        msg = f"Overwriting existing research export: {output_path}"
        log.warning(msg)
        print(msg)

    output_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
    return output_path


def auto_index(json_path: Path, store_dir: Path | None = None) -> None:
    """Index the exported research JSON into the kctx file-based store.
    Logs and swallows failures — never raises. Uses context_cli.STORE_DIR by default."""
    try:
        from context_cli import STORE_DIR
        from context_cli.indexer import index_doc

        target = store_dir if store_dir is not None else STORE_DIR
        result = index_doc(json_path, target)
        log.info("Indexed research doc '%s' at %s", result.doc_name, result.store_path)
    except Exception as exc:
        log.warning("auto_index failed for %s: %s", json_path, exc)
