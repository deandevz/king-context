import json
from pathlib import Path

from king_context import seed_data
from king_context.scraper.enrich import EnrichedChunk


def export_to_json(
    enriched_chunks: list[EnrichedChunk],
    doc_name: str,
    display_name: str,
    base_url: str,
    version: str = "v1",
) -> dict:
    """Build a King Context documentation dict from enriched chunks.

    The returned dict matches the schema expected by seed_data.seed_one().
    """
    sections = [
        {
            "title": chunk.title,
            "path": chunk.path,
            "url": chunk.url,
            "keywords": chunk.keywords,
            "use_cases": chunk.use_cases,
            "tags": chunk.tags,
            "priority": chunk.priority,
            "content": chunk.content,
        }
        for chunk in enriched_chunks
    ]
    return {
        "name": doc_name,
        "display_name": display_name,
        "version": version,
        "base_url": base_url,
        "sections": sections,
    }


def save_and_index(doc_data: dict, output_path: Path, auto_seed: bool = True) -> None:
    """Save doc_data as JSON to output_path and optionally index into the database."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(doc_data, indent=2, ensure_ascii=False))
    if auto_seed:
        seed_data.seed_one(output_path)
