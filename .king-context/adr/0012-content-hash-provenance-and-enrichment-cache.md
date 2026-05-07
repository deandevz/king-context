---
id: ADR-0012
title: Content-hash provenance for chunks and a file per hash enrichment cache
status: accepted
date: 2026-05-07
areas:
  - scraper
  - corpus
  - cache
  - performance
supersedes: []
superseded_by: []
related:
  - ADR-0009
  - ADR-0010
keywords:
  - content-hash
  - provenance
  - enrichment-cache
  - sha256
  - delta-update
  - drift-detection
  - cache-key
  - prompt-version
tags:
  - architecture
  - scraper
  - cache
---


# ADR-0012: Content-hash provenance for chunks and a file-per-hash enrichment cache

## Context

`king-scrape` today is a one-shot pipeline. Re-running it against the same docs site silently skips any URL whose `<slug>.md` file already exists in `.king-context/_temp/<host>/pages/` (`src/king_context/scraper/fetch.py:61`), which makes "the upstream docs changed last week — refresh my corpus" a `rm -rf` operation. Re-`rm` forces a full re-fetch and a full re-enrichment. Enrichment is the expensive step (OpenRouter, $1-3 per FastAPI-sized corpus), and almost none of those calls are necessary: most sections do not change between scrapes.

Two follow on capabilities drift detection and incremental refresh both depend on knowing whether a given chunk's content is identical to what was previously enriched. The exported corpus (`data/<name>.json`) carries no such information today: no `content_hash`, no `fetched_at`, no `scraper_version`. The enrichment stage's resume logic (`src/king_context/scraper/enrich.py`) keys off batch position (`already_enriched = len(previous_data); chunks = chunks[already_enriched:]`), which silently misaligns enrichment with chunks if the upstream docs add or remove a section between runs.

ADR-0010 established that scraper providers stay thin and the pipeline owns checkpoint, concurrency, and disk IO. The work below sits in the pipeline layer for exactly that reason — it is independent of which scrape backend (Firecrawl, Crawl4AI) produced the markdown.

## Decision

Add content-hash provenance at every layer of the pipeline, and a small file-per-hash cache for enrichment outputs.

1. **Per-page sidecar.** For each fetched page, write `pages/<slug>.meta.json` next to `pages/<slug>.md` containing `{ url, slug, content_hash (sha256), fetched_at (UTC ISO), byte_size }`. Sidecars are atomic per-file, so they are race-free under the existing concurrent fetch model with no additional locking.
2. **`Chunk.content_hash`.** Extend `Chunk` (and `EnrichedChunk`) with a `content_hash` field populated by `sha256(content)` via `__post_init__`. The field auto-computes when constructors are called with the existing positional or keyword arguments, so every existing call site keeps working unchanged.
3. **Enriched checkpoint includes the hash.** The per-batch checkpoint files (`enriched/batch_NNNN.json`) gain a `content_hash` per item; the resume reader reads it back, falling back to recomputing from `content` when an old checkpoint lacks the field.
4. **Exported `_meta`.** Each section in `data/<name>.json` gains `_meta.content_hash`, and the top-level dict gains `_meta = { schema_version, scraper_version, scraped_at, source_url, section_count }`. All `_meta` fields are optional — consumers (the MCP server, `kctx`, existing readers) ignore unknown keys, so older corpora keep working with no migration.
5. **Enrichment cache.** A new module `src/king_context/scraper/enrich_cache.py` stores enrichment results at `.king-context/cache/enrichment/<sha256>.json`. The cache key is `sha256(content + "|" + model_id + "|" + prompt_version)`. Writes are atomic via `tempfile.NamedTemporaryFile` + `os.replace`; reads return `None` on miss, JSON decode error, or any IO error. The cache is wired into `_enrich_one` so a content/model/prompt-stable chunk pays zero LLM cost on subsequent runs. A `PROMPT_VERSION = "1"` constant in `enrich.py` is bumped when `ENRICHMENT_PROMPT` changes — that is the cache's correctness handle.

## Alternatives Considered

**`cachehash` PyPI library.** Considered as a backing store. Rejected on two grounds: (a) license, the package is published as "free for non commercial use only", which is incompatible with king-context's MIT license and would taint downstream consumers; (b) shape opaque SQLite key-value with eviction/TTL hooks we do not need, when the project ethos (ADR-0010) is pipeline owned IO with inspectable on disk artifacts. File per hash JSON gives `cat .king-context/cache/enrichment/<sha>.json` for free and lets a contributor invalidate one entry by deleting one file.

**SQLite index alongside files.** Discussed as a "best of both worlds" hybrid. Deferred until disk-stat overhead is shown by measurement to matter; for typical corpora (30-200 chunks), 200 stat calls is microseconds and the simpler layout wins.

**Single aggregated `pages/_manifest.json`.** Rejected in favour of per-page sidecars. A single manifest would need an in-memory lock or merge-on-write logic to be safe under the concurrent fetch model in `fetch.py`. Per-page files are atomic by construction. An aggregated view is trivially derivable on demand if a future stage needs one.

**Cache key without model + prompt version.** Rejected as a real footgun: a prompt edit or model swap would silently serve stale enrichments. Putting both into the key means changes invalidate the cache automatically.

## Consequences

A fresh scrape now produces richer artifacts (per-page sidecars, content hashes through every chunk, `_meta` in the exported JSON) without changing the public command, the schema consumed by `seed_data`, or the provider Protocols. Existing corpora (`data/*.json` shipped before this change) keep working — the optional `_meta` fields just aren't there.

The enrichment cache makes a re-run on unchanged content free, which is the foundation a future `--update` flag needs (ADR-0014). It is also a meaningful day-one win for contributors who scrape, tweak the chunker, and re-scrape — chunks whose content survives the re-chunk pay no LLM cost.

The cache directory grows monotonically under `.king-context/cache/enrichment/`. At ~2 KB per entry and typical corpus sizes, this is bounded enough to ignore for the foreseeable future. If it ever matters, `rm -rf .king-context/cache/enrichment/` is a complete, debuggable invalidation.

The hash on each chunk and section is the data dependency drift detection (ADR-0013) and incremental refresh (ADR-0014) build on. Without it, both are impossible to implement correctly. With it, both reduce to small focused PRs.

## Links

src/king_context/scraper/enrich_cache.py
src/king_context/scraper/chunk.py
src/king_context/scraper/fetch.py
src/king_context/scraper/enrich.py
src/king_context/scraper/export.py
