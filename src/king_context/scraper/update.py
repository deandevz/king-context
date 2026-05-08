"""Incremental refresh of an indexed corpus.

Re-runs the scraper pipeline against the upstream of an existing
``data/<name>.json`` corpus, but reuses every section whose chunked content
is byte identical to what the previous scrape produced. Only chunks whose
``content_hash`` is new (added or changed) get sent to the LLM, so a typical
documentation refresh costs cents instead of dollars even on a large corpus.

The integrity unit is the chunk's ``sha256(content)`` from ADR-0012. When a
chunk's hash matches an existing section, the existing enrichment values
(``keywords``, ``use_cases``, ``tags``, ``priority``) are carried forward but
the structural fields (``title``, ``path``, ``url``) come from the fresh chunk
so a page reorganisation upstream is reflected accurately.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from scraper_providers import (
    ProviderUnavailableError,
    get_discovery_provider,
    get_fetch_provider,
    resolve_provider_name,
)

from king_context import PROJECT_ROOT
from king_context.scraper.chunk import Chunk, chunk_pages
from king_context.scraper.config import ScraperConfig, load_config
from king_context.scraper.discover import discover_urls, get_work_dir
from king_context.scraper.enrich import (
    EnrichedChunk,
    enrich_chunks,
    estimate_cost,
)
from king_context.scraper.export import export_to_json, save_and_index
from king_context.scraper.fetch import fetch_pages
from king_context.scraper.filter import filter_urls


@dataclass
class UpdatePlan:
    """Result of comparing a fresh scrape against the existing corpus."""
    reused_chunks: list[Chunk] = field(default_factory=list)
    new_chunks: list[Chunk] = field(default_factory=list)
    fresh_urls: set[str] = field(default_factory=set)
    corpus_urls: set[str] = field(default_factory=set)

    @property
    def removed_urls(self) -> list[str]:
        return sorted(self.corpus_urls - self.fresh_urls)

    @property
    def added_urls(self) -> list[str]:
        return sorted(self.fresh_urls - self.corpus_urls)


@dataclass
class UpdateReport:
    name: str
    reused: int
    enriched: int
    removed_urls: list[str]
    added_urls: list[str]
    total_sections: int


def _candidate_corpus_paths(name: str) -> list[Path]:
    return [
        PROJECT_ROOT / ".king-context" / "data" / f"{name}.json",
        PROJECT_ROOT / "data" / f"{name}.json",
    ]


def find_corpus(name: str) -> Path:
    for path in _candidate_corpus_paths(name):
        if path.exists():
            return path
    searched = "\n  ".join(str(p) for p in _candidate_corpus_paths(name))
    raise FileNotFoundError(f"Corpus '{name}' not found. Searched:\n  {searched}")


def _load_corpus(corpus_path: Path) -> dict:
    raw = corpus_path.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"corpus at {corpus_path} is not valid JSON: {exc}") from exc


def _section_hash(section: dict) -> str:
    """Resolve a section's content hash, falling back to a recompute for legacy corpora."""
    stored = section.get("_meta", {}).get("content_hash")
    if stored:
        return stored
    return hashlib.sha256(section.get("content", "").encode("utf-8")).hexdigest()


def _enrichment_from_section(section: dict) -> dict:
    return {
        "keywords": section["keywords"],
        "use_cases": section["use_cases"],
        "tags": section["tags"],
        "priority": section["priority"],
    }


def _resolve_source_url(corpus: dict) -> str:
    return (
        corpus.get("_meta", {}).get("source_url")
        or corpus.get("base_url")
        or ""
    )


def _build_reuse_index(corpus: dict) -> dict[str, dict]:
    """Map ``content_hash`` to its enrichment values, plus the URL that produced it."""
    out: dict[str, dict] = {}
    for s in corpus.get("sections", []):
        out[_section_hash(s)] = {
            **_enrichment_from_section(s),
            "_url": s.get("url", ""),
        }
    return out


def _plan_update(
    fresh_chunks: list[Chunk],
    fresh_urls: Iterable[str],
    reuse_index: dict[str, dict],
    corpus: dict,
) -> UpdatePlan:
    plan = UpdatePlan(
        fresh_urls=set(fresh_urls),
        corpus_urls={s.get("url", "") for s in corpus.get("sections", [])},
    )
    for chunk in fresh_chunks:
        if chunk.content_hash in reuse_index:
            plan.reused_chunks.append(chunk)
        else:
            plan.new_chunks.append(chunk)
    return plan


def _materialise_reused(
    chunks: list[Chunk], reuse_index: dict[str, dict]
) -> list[EnrichedChunk]:
    """Build EnrichedChunk objects from carried over enrichment metadata."""
    out: list[EnrichedChunk] = []
    for chunk in chunks:
        carried = reuse_index[chunk.content_hash]
        out.append(EnrichedChunk(
            title=chunk.title,
            path=chunk.path,
            url=chunk.source_url,
            content=chunk.content,
            keywords=list(carried["keywords"]),
            use_cases=list(carried["use_cases"]),
            tags=list(carried["tags"]),
            priority=carried["priority"],
            content_hash=chunk.content_hash,
        ))
    return out


def _interleave_in_chunk_order(
    fresh_chunks: list[Chunk],
    reused: list[EnrichedChunk],
    enriched: list[EnrichedChunk],
) -> list[EnrichedChunk]:
    """Return the merged enriched list in the order of ``fresh_chunks``."""
    by_hash: dict[str, EnrichedChunk] = {}
    for e in reused:
        by_hash[e.content_hash] = e
    for e in enriched:
        by_hash[e.content_hash] = e
    out: list[EnrichedChunk] = []
    for chunk in fresh_chunks:
        e = by_hash.get(chunk.content_hash)
        if e is not None:
            out.append(e)
    return out


async def _confirm_cost(plan: UpdatePlan, config: ScraperConfig, *, yes: bool) -> bool:
    cost = estimate_cost(plan.new_chunks, config)
    print(
        f"  reused: {len(plan.reused_chunks)}, "
        f"new: {len(plan.new_chunks)}, "
        f"removed URLs: {len(plan.removed_urls)}, "
        f"added URLs: {len(plan.added_urls)}"
    )
    if cost.get("provider") == "openrouter":
        print(
            f"  cost estimate: ${cost['estimated_cost']:.4f} "
            f"({cost['total_chunks']} chunks, model: {cost['model']})"
        )
    else:
        print(
            f"  local model estimate: {cost['total_chunks']} chunks, "
            f"model: {cost['model']} (no estimated OpenRouter cost)"
        )
    if yes:
        return True
    answer = input("Proceed with enrichment? [y/N] ").strip().lower()
    return answer in ("y", "yes")


async def update_corpus(
    *,
    name: str,
    corpus_path: Path,
    config: ScraperConfig,
    yes: bool = False,
) -> UpdateReport:
    corpus = _load_corpus(corpus_path)
    source_url = _resolve_source_url(corpus)
    if not source_url:
        raise ValueError(
            "corpus has no source_url in _meta and no base_url. "
            "Re-scrape from scratch with `king-scrape <url> --name <name>`."
        )

    discovery_provider = get_discovery_provider(resolve_provider_name("discover"))
    fetch_provider = get_fetch_provider(resolve_provider_name("fetch"))

    work_dir = get_work_dir(source_url)
    work_dir.mkdir(parents=True, exist_ok=True)

    print(f"[update] target: {name} ({source_url})")
    print("[discover] running...")
    discovery = await discover_urls(source_url, config, discovery_provider)
    print(f"  found {discovery.total_urls} URLs")

    print("[filter] running...")
    filtered = filter_urls(discovery.urls, source_url, config)
    print(
        f"  accepted {len(filtered.accepted)}, "
        f"rejected {len(filtered.rejected)}, "
        f"maybe {len(filtered.maybe)}"
    )

    print("[fetch] running (force refresh)...")
    fetch_result = await fetch_pages(
        filtered.accepted,
        work_dir,
        config,
        fetch_provider,
        force_refresh=True,
    )
    print(f"  fetched {fetch_result.completed}, failed {fetch_result.failed}")

    print("[chunk] running...")
    fresh_chunks = chunk_pages(work_dir / "pages", work_dir, config)
    print(f"  produced {len(fresh_chunks)} chunks")

    reuse_index = _build_reuse_index(corpus)
    plan = _plan_update(fresh_chunks, filtered.accepted, reuse_index, corpus)

    print("[plan]")
    proceed = await _confirm_cost(plan, config, yes=yes)
    if not proceed:
        print("aborted by user")
        raise SystemExit(1)

    print("[enrich] running...")
    enriched_new = await enrich_chunks(plan.new_chunks, config, work_dir)
    print(f"  enriched {len(enriched_new)} new chunks")

    reused_enriched = _materialise_reused(plan.reused_chunks, reuse_index)
    final = _interleave_in_chunk_order(fresh_chunks, reused_enriched, enriched_new)

    doc = export_to_json(
        final,
        doc_name=corpus.get("name", name),
        display_name=corpus.get("display_name", name),
        base_url=corpus.get("base_url", source_url),
        version=corpus.get("version", "v1"),
    )

    print("[export] running...")
    save_and_index(doc, corpus_path, auto_seed=False)

    return UpdateReport(
        name=name,
        reused=len(reused_enriched),
        enriched=len(enriched_new),
        removed_urls=plan.removed_urls,
        added_urls=plan.added_urls,
        total_sections=len(final),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="king-scrape update",
        description=(
            "Incrementally refresh an indexed corpus. Reuses every section "
            "whose chunked content is unchanged; only new or changed chunks "
            "are sent to the LLM."
        ),
    )
    parser.add_argument("name", help="Doc name (matches data/<name>.json)")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the cost confirmation prompt before enrichment.",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Scraper provider name (e.g. 'firecrawl', 'crawl4ai').",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="OpenRouter model for enrichment.",
    )
    return parser


def update_main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    if args.provider:
        os.environ.setdefault("SCRAPE_PROVIDER", args.provider)

    try:
        corpus_path = find_corpus(args.name)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    config = load_config(enrichment_model=args.model)

    try:
        report = asyncio.run(update_corpus(
            name=args.name,
            corpus_path=corpus_path,
            config=config,
            yes=args.yes,
        ))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ProviderUnavailableError as exc:
        print(f"error: {exc.hint}", file=sys.stderr)
        return 3
    except SystemExit as exc:
        return int(exc.code or 1)

    print(
        f"update {report.name}: "
        f"{report.total_sections} sections "
        f"(reused {report.reused}, enriched {report.enriched}, "
        f"+{len(report.added_urls)} URLs / -{len(report.removed_urls)} URLs)"
    )
    return 0
