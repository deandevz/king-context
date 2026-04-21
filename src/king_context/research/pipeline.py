"""Research pipeline orchestrating the 5-step: generate, search, chunk, enrich, export."""
from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

from king_context.research.config import ResearchConfig
from king_context.research.deepen import run_deepening_loop
from king_context.research.export import (
    _slugify,
    auto_index,
    export_research_to_json,
)
from king_context.research.fetch import SourceDoc
from king_context.scraper.chunk import Chunk, chunk_page
from king_context.scraper.config import ConfigError
from king_context.scraper.discover import TEMP_DOCS_DIR, _update_step
from king_context.scraper.enrich import EnrichedChunk, enrich_chunks, estimate_cost

log = logging.getLogger(__name__)

RESEARCH_STEPS = ["generate", "search", "chunk", "enrich", "export"]

MANIFEST_KEYS = {
    "generate": "generate",
    "search": "search",
    "chunk": "chunking",
    "enrich": "enrichment",
    "export": "export",
}


def _source_slug(url: str) -> str:
    s = re.sub(r"^https?://", "", url)
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-")
    return (s[:200] or "page").lower()


def _validate_config(config: ResearchConfig) -> None:
    if not config.exa_api_key:
        raise ConfigError(
            "EXA_API_KEY not set — add it to .env or .king-context/.env"
        )
    if not config.scraper.openrouter_api_key:
        raise ConfigError(
            "OPENROUTER_API_KEY not set — add it to .env or .king-context/.env"
        )


def _write_page_artifacts(source: SourceDoc, pages_dir: Path) -> None:
    slug = _source_slug(source.url)
    md_path = pages_dir / f"{slug}.md"
    json_path = pages_dir / f"{slug}.json"
    try:
        md_path.write_text(source.content or "", encoding="utf-8")
        sidecar = {
            "url": source.url,
            "title": source.title,
            "author": source.author,
            "published_date": source.published_date,
            "domain": source.domain,
            "discovery_iteration": source.discovery_iteration,
            "query": source.query,
            "fetch_path": source.fetch_path,
        }
        json_path.write_text(
            json.dumps(sidecar, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        log.warning("Failed to persist page artifacts for %s: %s", source.url, exc)


def _write_chunk_checkpoint(
    source: SourceDoc, page_chunks: list[Chunk], chunks_dir: Path
) -> None:
    slug = _source_slug(source.url)
    try:
        data = [
            {
                "title": c.title,
                "breadcrumb": c.breadcrumb,
                "content": c.content,
                "source_url": c.source_url,
                "path": c.path,
                "token_count": c.token_count,
            }
            for c in page_chunks
        ]
        (chunks_dir / f"{slug}.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        log.warning("Failed to write chunk checkpoint for %s: %s", source.url, exc)


async def run_pipeline(args: argparse.Namespace, config: ResearchConfig) -> Path:
    """Orchestrate the 5-step research pipeline and return the exported JSON path."""
    _validate_config(config)

    slug = args.name or _slugify(args.topic)
    work_dir = TEMP_DOCS_DIR / "research" / slug
    work_dir.mkdir(parents=True, exist_ok=True)

    target_step = getattr(args, "step", None)
    stop_after = getattr(args, "stop_after", None)

    if target_step and target_step not in RESEARCH_STEPS:
        raise ValueError(f"Unknown step: {target_step}")
    if stop_after and stop_after not in RESEARCH_STEPS:
        raise ValueError(f"Unknown stop-after step: {stop_after}")

    if target_step:
        log.warning(
            "--step=%s requested; resume not implemented in P1, "
            "earlier steps will be skipped without state rehydration",
            target_step,
        )

    sources: list[SourceDoc] = []
    chunks: list[Chunk] = []
    enriched: list[EnrichedChunk] = []
    output_path: Path | None = None

    for step in RESEARCH_STEPS:
        if target_step and RESEARCH_STEPS.index(step) < RESEARCH_STEPS.index(target_step):
            continue

        print(f"[{step}] running...")

        if step == "generate":
            _update_step(
                work_dir,
                MANIFEST_KEYS["generate"],
                {"status": "done", "topic": args.topic, "slug": slug},
            )
            log.info("generate: prepared work_dir for topic '%s' (slug=%s)", args.topic, slug)

        elif step == "search":
            sources = await run_deepening_loop(
                args.topic, args.effort, config, work_dir
            )
            if not sources:
                raise RuntimeError(
                    f"No sources found for topic '{args.topic}' — "
                    "refine the topic and retry."
                )
            _update_step(
                work_dir,
                MANIFEST_KEYS["search"],
                {"status": "done", "total_sources": len(sources)},
            )
            print(f"  found {len(sources)} sources")

        elif step == "chunk":
            pages_dir = work_dir / "pages"
            chunks_dir = work_dir / "chunks"
            pages_dir.mkdir(parents=True, exist_ok=True)
            chunks_dir.mkdir(parents=True, exist_ok=True)

            chunks = []
            for source in sources:
                _write_page_artifacts(source, pages_dir)
                page_chunks = chunk_page(
                    source.content or "", source.url, config.scraper
                )
                _write_chunk_checkpoint(source, page_chunks, chunks_dir)
                chunks.extend(page_chunks)

            _update_step(
                work_dir,
                MANIFEST_KEYS["chunk"],
                {"status": "done", "total_chunks": len(chunks)},
            )
            print(f"  created {len(chunks)} chunks")

        elif step == "enrich":
            cost = estimate_cost(chunks, config.scraper)
            print(
                f"Enrichment cost estimate: ${cost['estimated_cost']:.4f} "
                f"({cost['total_chunks']} chunks, model: {cost['model']})"
            )
            if not getattr(args, "yes", False):
                confirm = input("Proceed? [y/N] ").strip().lower()
                if confirm != "y":
                    print("  Enrichment cancelled.")
                    return work_dir / "manifest.json"

            enriched = await enrich_chunks(
                chunks, config.scraper, output_dir=work_dir
            )
            _update_step(
                work_dir,
                MANIFEST_KEYS["enrich"],
                {"status": "done", "total_enriched": len(enriched)},
            )
            print(f"  enriched {len(enriched)} chunks")

        elif step == "export":
            sources_by_url: dict[str, SourceDoc] = {s.url: s for s in sources}
            output_path = export_research_to_json(
                enriched,
                sources_by_url,
                slug,
                args.topic,
                base_url=None,
            )
            if not getattr(args, "no_auto_index", False):
                auto_index(output_path)
            _update_step(
                work_dir,
                MANIFEST_KEYS["export"],
                {"status": "done", "output": str(output_path)},
            )
            print(f"  exported to {output_path}")

        if stop_after and step == stop_after:
            print(f"  Stopped after '{step}' as requested.")
            if output_path is not None:
                return output_path
            return work_dir / "manifest.json"

    if output_path is None:
        return work_dir / "manifest.json"
    return output_path
