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
import shutil
import sys
import tempfile
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
from king_context.scraper._cache_mode import (
    add_cache_mode_argument,
    apply_cache_mode_flag,
    restore_cache_mode,
)
from king_context.scraper.chunk import Chunk, chunk_pages
from king_context.scraper.config import ScraperConfig, load_config
from king_context.scraper.discover import discover_urls, get_work_dir
from king_context.scraper.enrich import (
    EnrichedChunk,
    enrich_chunks,
    estimate_cost,
)
from king_context.scraper.export import export_to_json
from king_context.scraper.fetch import fetch_pages
from king_context.scraper.filter import filter_urls
from king_context.scraper.url_utils import canonicalize_url


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
    lost: int
    fetch_failed: int
    removed_urls: list[str]
    added_urls: list[str]
    total_sections: int


# Both thresholds are strict-`>` boundaries: exactly-on-the-line ratios PASS.
# A 1-of-10 fetch failure (0.10) is allowed; a 2-of-10 (0.20) aborts. A 50/50
# discover loss is allowed; 51% aborts. Locked in by the test suite — change
# the operator and the test names in lockstep.
FETCH_FAILURE_RATIO_THRESHOLD = 0.10
DISCOVER_LOSS_RATIO_THRESHOLD = 0.50


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
    """Resolve a section's content hash, falling back to a recompute for legacy corpora.

    The fallback assumes the JSON-stored ``content`` round-trips to the same bytes
    a fresh chunk produces; under the standard ``json.loads`` settings (NFC unicode,
    UTF-8 encoding) this holds. Corpora with non-NFC content will miss-match here
    and pay LLM cost on the first update; subsequent updates after that one
    rewrites the corpus carry the stored ``_meta.content_hash`` and cost nothing.
    """
    stored = section.get("_meta", {}).get("content_hash")
    if stored:
        return stored
    return hashlib.sha256(section.get("content", "").encode("utf-8")).hexdigest()


def _reset_work_dir(work_dir: Path) -> None:
    """Wipe per-stage state so update never inherits artifacts from a prior run.

    Critical for correctness: stale ``enriched/batch_*.json`` triggers the resume
    logic in ``enrich.py`` and silently returns the OLD batch contents instead of
    enriching the fresh chunks. Stale ``pages/*.md`` from URLs no longer present
    upstream would survive ``chunk_pages`` and resurface in the new corpus as
    "reused" because their content hash still matches the old sections.
    """
    for sub in ("pages", "chunks", "enriched"):
        target = work_dir / sub
        if target.exists():
            shutil.rmtree(target)
    manifest = work_dir / "manifest.json"
    if manifest.exists():
        manifest.unlink()


def _atomic_write_json(path: Path, doc: dict) -> None:
    """Write JSON via tempfile + os.replace so an interrupted update never leaves a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(doc, indent=2, ensure_ascii=False)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_name, path)
        tmp_name = None
    finally:
        if tmp_name is not None and Path(tmp_name).exists():
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def _enrichment_from_section(section: dict) -> dict:
    # Defaults match a "no enrichment" shape so a malformed legacy section
    # (passes the `_meta` guard but lacks one of these fields) still produces
    # a reuse entry rather than crashing the whole update with KeyError. The
    # downstream effect is the chunk gets re-enriched, which is the safer
    # default — we pay LLM cost on a curated section that lost its metadata,
    # rather than aborting the entire refresh.
    return {
        "keywords": section.get("keywords") or [],
        "use_cases": section.get("use_cases") or [],
        "tags": section.get("tags") or [],
        "priority": section.get("priority", 0),
    }


def _resolve_source_url(corpus: dict) -> str:
    # `corpus.get("_meta") or {}` (not the default form) so an explicit
    # `"_meta": null` in the JSON still produces a dict for the chained
    # .get(...) instead of raising AttributeError. The legacy guard
    # upstream uses `"_meta" not in corpus`, which lets explicit-null
    # through.
    meta = corpus.get("_meta") or {}
    return meta.get("source_url") or corpus.get("base_url") or ""


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
    # Canonicalise both sides before set arithmetic so trailing slashes,
    # fragments, and host case differences do not inflate added_urls /
    # removed_urls. Without this, legacy corpora carrying slug-form URLs
    # and fresh discoveries carrying real https URLs would diff at 100%
    # mismatch even when pointing at identical resources.
    plan = UpdatePlan(
        fresh_urls={canonicalize_url(u) for u in fresh_urls if u},
        corpus_urls={
            canonicalize_url(s.get("url", ""))
            for s in corpus.get("sections", [])
            if s.get("url")
        },
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
    """Return the merged enriched list in the order of ``fresh_chunks``.

    If ``fresh_chunks`` contains two chunks with the same ``content_hash``
    (a real corpus example: shared boilerplate sections crossing multiple
    pages) the deduped output emits one section per unique content. The
    second occurrence is silently dropped — the corpus is content-keyed,
    not URL-keyed, so the duplicate would otherwise widen the section list
    with no new information.
    """
    by_hash: dict[str, EnrichedChunk] = {}
    for e in reused:
        by_hash[e.content_hash] = e
    for e in enriched:
        by_hash[e.content_hash] = e
    out: list[EnrichedChunk] = []
    seen: set[str] = set()
    for chunk in fresh_chunks:
        if chunk.content_hash in seen:
            continue
        e = by_hash.get(chunk.content_hash)
        if e is not None:
            out.append(e)
            seen.add(chunk.content_hash)
    return out


async def _confirm_cost(plan: UpdatePlan, config: ScraperConfig, *, yes: bool) -> bool:
    # Nothing to enrich means nothing to confirm. Skip the cost preview and
    # the prompt entirely so a no-op refresh does not nag the operator with a
    # "$0.0000" dialog.
    if not plan.new_chunks:
        print(
            f"  reused: {len(plan.reused_chunks)}, "
            f"new: 0, "
            f"removed URLs: {len(plan.removed_urls)}, "
            f"added URLs: {len(plan.added_urls)} "
            "(nothing to enrich)"
        )
        return True

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

    # Hard refuse on legacy corpora that lack ``_meta``. The fallback to
    # ``base_url`` (which on legacy files is the host root, not the original
    # entry point) silently triggers a full host rescrape, wipes the curated
    # section set, and spends LLM credits with no warning. Anchor the corpus
    # first with a fresh scrape and re-run update once ``_meta.source_url``
    # is set. (#55, confirmed via e2e against data/minimax-audio.json.)
    if "_meta" not in corpus:
        raise ValueError(
            f"corpus {corpus_path.name} has no _meta block "
            "(legacy pre-ADR-0012 shape). Re-scrape with "
            f"`king-scrape <url> --name {name}` first to anchor it; "
            "subsequent update runs will then refresh incrementally."
        )

    source_url = _resolve_source_url(corpus)
    if not source_url:
        raise ValueError(
            "corpus has _meta but no source_url and no base_url. "
            f"Re-scrape from scratch with `king-scrape <url> --name {name}`."
        )

    discovery_provider = get_discovery_provider(resolve_provider_name("discover"))
    fetch_provider = get_fetch_provider(resolve_provider_name("fetch"))

    work_dir = get_work_dir(source_url)
    work_dir.mkdir(parents=True, exist_ok=True)
    _reset_work_dir(work_dir)

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

    # Discover-divergence guard: if more than half the corpus URLs disappear
    # from the upstream's fresh discovery, abort BEFORE the fetch step so we
    # do not spend bandwidth + LLM credits on a corpus that just lost half
    # its surface. Growth is allowed; only loss is dangerous (correlates
    # with auth dropped, provider misconfigured, or upstream restructured).
    # Compares against ``discovery.urls`` (pre-filter): a URL silently dropped
    # by the filter is reachable on the network, so it does not count as
    # "missing upstream" — that is the report's job (``plan.removed_urls``).
    # At small N the threshold is intentionally sensitive (a 1-URL corpus
    # losing its one URL aborts at 100%); that is the safe direction.
    corpus_canon_urls = {
        canonicalize_url(s.get("url", ""))
        for s in corpus.get("sections", [])
        if s.get("url")
    }
    if corpus_canon_urls:
        fresh_canon_urls = {canonicalize_url(u) for u in discovery.urls if u}
        # Skip the ratio check when fresh discovery returned nothing; the
        # downstream "refuse to overwrite with empty corpus" guard has a
        # clearer message for the total-wipe case.
        if fresh_canon_urls:
            lost = corpus_canon_urls - fresh_canon_urls
            loss_ratio = len(lost) / len(corpus_canon_urls)
            if loss_ratio > DISCOVER_LOSS_RATIO_THRESHOLD:
                sample = sorted(lost)[:5]
                raise ValueError(
                    f"refused to update {corpus_path.name}: "
                    f"{len(lost)} of {len(corpus_canon_urls)} corpus URLs "
                    f"({loss_ratio:.0%}) are missing from the fresh discovery, "
                    f"above the {DISCOVER_LOSS_RATIO_THRESHOLD:.0%} threshold. "
                    "Investigate before retrying. Sample missing URLs: "
                    f"{sample}"
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

    # Fetch-failure threshold: if too many accepted URLs failed to fetch,
    # the resulting corpus would silently truncate. Refuse the writeback
    # so the existing corpus on disk stays intact.
    if filtered.accepted:
        fail_ratio = fetch_result.failed / len(filtered.accepted)
        if fail_ratio > FETCH_FAILURE_RATIO_THRESHOLD:
            raise ValueError(
                f"refused to update {corpus_path.name}: "
                f"{fetch_result.failed} of {len(filtered.accepted)} fetches "
                f"failed ({fail_ratio:.0%}), above the "
                f"{FETCH_FAILURE_RATIO_THRESHOLD:.0%} threshold. The existing "
                "corpus is untouched. Investigate before retrying."
            )

    print("[chunk] running...")
    fresh_chunks = chunk_pages(work_dir / "pages", work_dir, config)
    print(f"  produced {len(fresh_chunks)} chunks")

    # Refuse to wipe a non-empty corpus when discover/filter produced nothing.
    # Most often this is a network blip or an over-aggressive filter regex; the
    # original corpus is the safer artifact to preserve.
    if not fresh_chunks and corpus.get("sections"):
        raise ValueError(
            f"refused to overwrite {corpus_path} with an empty corpus "
            f"(discover/filter produced 0 URLs). The existing corpus is "
            "untouched. Investigate before retrying."
        )

    reuse_index = _build_reuse_index(corpus)
    plan = _plan_update(fresh_chunks, filtered.accepted, reuse_index, corpus)

    print("[plan]")
    proceed = await _confirm_cost(plan, config, yes=yes)
    if not proceed:
        print("aborted by user")
        raise SystemExit(1)

    if plan.new_chunks:
        print("[enrich] running...")
        enriched_new = await enrich_chunks(plan.new_chunks, config, work_dir)
        print(f"  enriched {len(enriched_new)} new chunks")
    else:
        print("[enrich] nothing to enrich (all chunks reused)")
        enriched_new = []

    lost = len(plan.new_chunks) - len(enriched_new)
    if lost > 0:
        print(
            f"warning: {lost} chunk(s) failed enrichment and are not in "
            "the output corpus"
        )

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
    _atomic_write_json(corpus_path, doc)

    return UpdateReport(
        name=name,
        reused=len(reused_enriched),
        enriched=len(enriched_new),
        lost=lost,
        fetch_failed=fetch_result.failed,
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
        "--corpus-path",
        type=Path,
        default=None,
        help=(
            "Explicit path to the corpus JSON. Bypasses the default lookup in "
            "data/<name>.json and .king-context/data/<name>.json."
        ),
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
    add_cache_mode_argument(parser)
    return parser


def update_main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)

    # Snapshot SCRAPE_PROVIDER state so `--provider` does not leak past the
    # call boundary. The flag wins over any pre-existing env DURING the run
    # (asymmetric with cli.main's setdefault, by design — `update` is an
    # explicit refresh action), but the prior state is restored on exit so
    # tests and embedding hosts see the same env they handed us.
    provider_was_set = "SCRAPE_PROVIDER" in os.environ
    provider_prior = os.environ.get("SCRAPE_PROVIDER")
    if args.provider:
        os.environ["SCRAPE_PROVIDER"] = args.provider

    cache_mode_was_set, cache_mode_prior = apply_cache_mode_flag(args)
    try:
        if args.corpus_path is not None:
            corpus_path = args.corpus_path
            if not corpus_path.exists():
                print(f"error: corpus path does not exist: {corpus_path}", file=sys.stderr)
                return 1
        else:
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
            # SystemExit(0) is a legitimate clean exit; only fall back to 1
            # when the code is unset/None. `int(exc.code or 1)` would coerce
            # 0 -> 1 because `0 or 1` evaluates to 1.
            if exc.code is None:
                return 1
            return int(exc.code)
    finally:
        restore_cache_mode(cache_mode_was_set, cache_mode_prior)
        if provider_was_set:
            os.environ["SCRAPE_PROVIDER"] = provider_prior  # type: ignore[assignment]
        else:
            os.environ.pop("SCRAPE_PROVIDER", None)

    extras: list[str] = []
    if report.lost > 0:
        extras.append(f"lost {report.lost}")
    if report.fetch_failed > 0:
        extras.append(f"fetch_failed {report.fetch_failed}")
    extras_str = (", " + ", ".join(extras)) if extras else ""
    print(
        f"update {report.name}: "
        f"{report.total_sections} sections "
        f"(reused {report.reused}, enriched {report.enriched}{extras_str}, "
        f"added {len(report.added_urls)} URLs, removed {len(report.removed_urls)} URLs)"
    )
    return 0
