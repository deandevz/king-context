import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

from king_context import PROJECT_ROOT
from king_context.scraper.chunk import Chunk, chunk_pages
from king_context.scraper.config import ScraperConfig, load_config
from king_context.scraper.discover import (
    DiscoveryResult,
    _load_manifest,
    _update_step,
    discover_urls,
    get_work_dir,
)
from king_context.scraper.enrich import EnrichedChunk, enrich_chunks, estimate_cost
from king_context.scraper.export import export_to_json, save_and_index
from king_context.scraper.fetch import fetch_pages
from king_context.scraper.filter import FilterResult, filter_urls

PIPELINE_STEPS = ["discover", "filter", "fetch", "chunk", "enrich", "export"]

MANIFEST_KEYS = {
    "discover": "discovery",
    "filter": "filtering",
    "fetch": "fetch",
    "chunk": "chunking",
    "enrich": "enrichment",
    "export": "export",
}


def _name_from_url(url: str) -> str:
    """Infer a short doc name from a URL.

    Examples:
        https://docs.stripe.com  → stripe
        https://api.stripe.com   → stripe
        https://reactjs.org      → reactjs
    """
    parsed = urlparse(url)
    hostname = (parsed.netloc or parsed.path).split(":")[0]
    parts = hostname.split(".")
    noise = {"docs", "api", "www", "developer", "dev", "help", "support"}
    tlds = {"com", "org", "io", "net", "dev", "co", "app", "uk", "us", "eu"}
    parts = [p for p in parts if p not in noise]
    if len(parts) > 1 and parts[-1] in tlds:
        parts = parts[:-1]
    return parts[0] if parts else hostname.replace(".", "-")


def _step_done(manifest: dict, step: str) -> bool:
    key = MANIFEST_KEYS[step]
    return manifest.get(key, {}).get("status") == "done"


def _load_chunks_from_checkpoints(work_dir: Path) -> list[Chunk]:
    chunks_dir = work_dir / "chunks"
    all_chunks: list[Chunk] = []
    for json_file in sorted(chunks_dir.glob("*.json")):
        data = json.loads(json_file.read_text())
        for c in data:
            all_chunks.append(Chunk(
                title=c["title"],
                breadcrumb=c["breadcrumb"],
                content=c["content"],
                source_url=c["source_url"],
                path=c["path"],
                token_count=c["token_count"],
            ))
    return all_chunks


def _load_enriched_from_checkpoints(work_dir: Path) -> list[EnrichedChunk]:
    enriched_dir = work_dir / "enriched"
    batch_files = sorted(enriched_dir.glob("batch_*.json"))
    if not batch_files:
        return []
    data = json.loads(batch_files[-1].read_text())
    return [EnrichedChunk(**c) for c in data]


async def run_pipeline(args: argparse.Namespace, config: ScraperConfig) -> None:
    """Orchestrate the full scraping pipeline with checkpoint resume support.

    If args.step is set, the pipeline starts from that step (loading earlier
    stages from checkpoints). Without args.step, all stages run in sequence,
    skipping any already marked as done in the manifest.
    """
    name = args.name or _name_from_url(args.url)
    display_name = getattr(args, "display_name", None) or name.replace("-", " ").title()

    work_dir = get_work_dir(args.url)
    work_dir.mkdir(parents=True, exist_ok=True)

    manifest = _load_manifest(work_dir)

    target_step = getattr(args, "step", None)
    if target_step:
        start_idx = PIPELINE_STEPS.index(target_step)
        active_steps = set(PIPELINE_STEPS[start_idx:])
    else:
        active_steps = set(PIPELINE_STEPS)

    discovery_result: DiscoveryResult | None = None
    filter_result: FilterResult | None = None
    chunks: list[Chunk] = []
    enriched: list[EnrichedChunk] = []

    for step in PIPELINE_STEPS:
        if step not in active_steps:
            # Load checkpoint data for skipped steps so later stages can use it
            if step == "discover":
                disc_file = work_dir / "discovered_urls.json"
                if disc_file.exists():
                    discovery_result = DiscoveryResult(**json.loads(disc_file.read_text()))
            elif step == "filter":
                filt_file = work_dir / "filtered_urls.json"
                if filt_file.exists():
                    filter_result = FilterResult(**json.loads(filt_file.read_text()))
            elif step == "chunk":
                if (work_dir / "chunks").exists():
                    chunks = _load_chunks_from_checkpoints(work_dir)
            elif step == "enrich":
                enriched = _load_enriched_from_checkpoints(work_dir)
            continue

        # In full-pipeline mode, skip steps already completed
        if not target_step and _step_done(manifest, step):
            print(f"[{step}] already done, skipping")
            if step == "discover":
                discovery_result = DiscoveryResult(**json.loads(
                    (work_dir / "discovered_urls.json").read_text()
                ))
            elif step == "filter":
                filter_result = FilterResult(**json.loads(
                    (work_dir / "filtered_urls.json").read_text()
                ))
            elif step == "chunk":
                chunks = _load_chunks_from_checkpoints(work_dir)
            elif step == "enrich":
                enriched = _load_enriched_from_checkpoints(work_dir)
            continue

        print(f"[{step}] running...")

        if step == "discover":
            discovery_result = await discover_urls(args.url, config)
            print(f"  found {discovery_result.total_urls} URLs")

        elif step == "filter":
            if discovery_result is None:
                discovery_result = DiscoveryResult(**json.loads(
                    (work_dir / "discovered_urls.json").read_text()
                ))
            filter_result = filter_urls(discovery_result.urls, args.url, config)
            print(
                f"  accepted {len(filter_result.accepted)}, "
                f"rejected {len(filter_result.rejected)}, "
                f"maybe {len(filter_result.maybe)}"
            )

        elif step == "fetch":
            if filter_result is None:
                filter_result = FilterResult(**json.loads(
                    (work_dir / "filtered_urls.json").read_text()
                ))
            urls_to_fetch = filter_result.accepted[:]
            if getattr(args, "include_maybe", False):
                urls_to_fetch += filter_result.maybe
            fetch_result = await fetch_pages(urls_to_fetch, work_dir, config)
            print(f"  fetched {fetch_result.completed}/{fetch_result.total} pages")

        elif step == "chunk":
            pages_dir = work_dir / "pages"
            chunks = chunk_pages(pages_dir, work_dir, config)
            _update_step(work_dir, "chunking", {"status": "done", "total_chunks": len(chunks)})
            print(f"  created {len(chunks)} chunks")

        elif step == "enrich":
            if not chunks:
                chunks = _load_chunks_from_checkpoints(work_dir)
            cost = estimate_cost(chunks, config)
            print(
                f"  cost estimate: ${cost['estimated_cost']:.4f} "
                f"({cost['total_chunks']} chunks, model: {cost['model']})"
            )
            confirm = input("  Proceed with enrichment? [y/N] ").strip().lower()
            if confirm != "y":
                print("  Enrichment cancelled.")
                return
            enriched = await enrich_chunks(chunks, config, output_dir=work_dir)
            _update_step(work_dir, "enrichment", {"status": "done", "total_enriched": len(enriched)})
            print(f"  enriched {len(enriched)} chunks")

        elif step == "export":
            if not enriched:
                enriched = _load_enriched_from_checkpoints(work_dir)
            doc_data = export_to_json(enriched, name, display_name, args.url)
            output_path = PROJECT_ROOT / "data" / f"{name}.json"
            auto_seed = not getattr(args, "no_auto_seed", False)
            save_and_index(doc_data, output_path, auto_seed=auto_seed)
            _update_step(work_dir, "export", {"status": "done", "output": str(output_path)})
            print(f"  saved {len(enriched)} sections to {output_path}")

    manifest = _load_manifest(work_dir)
    print("\n=== Pipeline Summary ===")
    for s in PIPELINE_STEPS:
        key = MANIFEST_KEYS[s]
        if manifest.get(key, {}).get("status") == "done":
            print(f"  {s}: done")
    if not target_step or target_step == "export":
        print(f"  Output: data/{name}.json")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="king-scrape",
        description="Scrape and index documentation for King Context",
    )
    parser.add_argument("url", help="Base URL of the documentation to scrape")
    parser.add_argument(
        "--name",
        default=None,
        help="Documentation name (inferred from URL if omitted)",
    )
    parser.add_argument(
        "--display-name",
        dest="display_name",
        default=None,
        help="Display name for the documentation",
    )
    parser.add_argument(
        "--step",
        choices=PIPELINE_STEPS,
        default=None,
        help="Start the pipeline from this step (loads earlier stages from checkpoints)",
    )
    parser.add_argument(
        "--model",
        default="google/gemini-3-flash-preview", # Cheap and Fast Model for enrichment.
        help="LLM model to use for enrichment (default: google/gemini-3-flash-preview)", ##  default name in cli.
    )
    parser.add_argument(
        "--chunk-max-tokens",
        dest="chunk_max_tokens",
        type=int,
        default=800,
        help="Maximum tokens per chunk (default: 800)",
    )
    parser.add_argument(
        "--chunk-min-tokens",
        dest="chunk_min_tokens",
        type=int,
        default=50,
        help="Minimum tokens per chunk before merging (default: 50)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Number of concurrent fetch requests (default: 5)",
    )
    parser.add_argument(
        "--no-llm-filter",
        dest="no_llm_filter",
        action="store_true",
        help="Disable LLM fallback in URL filtering",
    )
    parser.add_argument(
        "--no-auto-seed",
        dest="no_auto_seed",
        action="store_true",
        help="Do not index the output into the database after export",
    )
    parser.add_argument(
        "--include-maybe",
        dest="include_maybe",
        action="store_true",
        help="Include URLs classified as 'maybe' in the fetch step",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    config = load_config(
        enrichment_model=args.model,
        chunk_max_tokens=args.chunk_max_tokens,
        chunk_min_tokens=args.chunk_min_tokens,
        concurrency=args.concurrency,
        filter_llm_fallback=not args.no_llm_filter,
    )
    asyncio.run(run_pipeline(args, config))
