# Scraper pipeline (`king-scrape`)

King Context is a CLI-first, local-first retrieval layer for AI agents. The
`king-scrape` command turns a documentation site into an enriched JSON corpus
that the `kctx` flat-file store can index and serve. This page documents the
pipeline internals: the six fixed stages, the orchestrator, checkpoint resume,
and the two extra subcommands (`audit` and `update`).

For the user-facing command reference, see the
[CLI guide](../CLI_GUIDE.md). For the system-level picture, see the
[architecture overview](overview.md). For provider resolution, see
[providers](providers.md). For the exported JSON shape, see the
[corpus schema reference](../reference/corpus-schema.md).

## Where the code lives

Everything in this page is in `src/king_context/scraper/`:

| File | Role |
| --- | --- |
| `cli.py` | Entry point `king-scrape`, orchestrator `run_pipeline()`, subcommand dispatch |
| `discover.py` | Stage 1, plus the work-dir and `manifest.json` helpers |
| `filter.py` | Stage 2, heuristic URL filter with LLM fallback |
| `fetch.py` | Stage 3, concurrent fetch with provenance sidecars |
| `chunk.py` | Stage 4, h2/h3 splitting with sha256 hashing |
| `enrich.py` | Stage 5, per-chunk LLM metadata |
| `enrich_cache.py` | Content-addressed enrichment cache |
| `export.py` | Stage 6, corpus JSON with `_meta` provenance |
| `audit.py` | `king-scrape audit` subcommand (ADR-0013) |
| `update.py` | `king-scrape update` subcommand (ADR-0014) |
| `config.py` | `ScraperConfig` and `load_config()` |
| `_cache_mode.py` | Shared `--no-fetch-cache` handling |
| `url_utils.py` | `canonicalize_url()` used by audit and update |

The console script is wired in `pyproject.toml` to
`king_context.scraper.cli:main`.

## The six fixed stages

`cli.py` defines the stage order as a fixed list:

```python
PIPELINE_STEPS = ["discover", "filter", "fetch", "chunk", "enrich", "export"]
```

Each stage is a thin module with a single primary function and an associated
dataclass. The orchestrator owns the loop, the checkpoints, and the provider
wiring; the stage modules do their own work and write their own checkpoint
artifacts.

### 1. discover

`discover_urls(base_url, config, provider)` in `discover.py` delegates URL
enumeration to the configured `DiscoveryProvider` (`provider.discover_urls`).
It wraps the result in a `DiscoveryResult` (`base_url`, `discovered_at`,
`total_urls`, `urls`), writes `discovered_urls.json` into the work dir, and
records a manifest entry under `discovery` with `status: "done"`.

### 2. filter

`filter_urls(urls, base_url, config)` in `filter.py` classifies each URL into
`accepted`, `rejected`, or `maybe` and writes `filtered_urls.json`. It is a
heuristic-first filter with an optional LLM fallback (covered in detail
[below](#heuristic-filter-with-llm-fallback)). The result is a `FilterResult`
(`accepted`, `rejected`, `maybe`, `filter_method`, `llm_fallback_used`).

### 3. fetch

`fetch_pages(urls, output_dir, config, provider)` in `fetch.py` downloads each
accepted URL through the configured `FetchProvider` concurrently. It writes
`<slug>.md` plus a `<slug>.meta.json` provenance sidecar per page into
`pages/`, and returns a `FetchResult` (`total`, `completed`, `failed`,
`results`). Concurrency and provenance are covered
[below](#concurrent-fetch).

### 4. chunk

`chunk_pages(pages_dir, output_dir, config)` in `chunk.py` reads every
`<slug>.md`, splits it at h2/h3 headers, sizes the chunks against
`chunk_max_tokens` / `chunk_min_tokens`, and computes a sha256 `content_hash`
per chunk. It writes one `chunks/<slug>.json` per page and returns a list of
`Chunk` objects. See [chunking](#chunking) for the split, subdivide, and merge
rules.

### 5. enrich

`enrich_chunks(chunks, config, output_dir)` in `enrich.py` asks an LLM to
produce `keywords`, `use_cases`, `tags`, and `priority` for each chunk. It
batches the work, checkpoints after each batch into `enriched/batch_*.json`,
uses a content-addressed cache, and falls back to a secondary client on schema
failures. It returns a list of `EnrichedChunk` objects. See
[enrichment](#enrichment).

### 6. export

`export_to_json(enriched, name, display_name, base_url)` in `export.py` builds
the King Context corpus dict (sections plus a `_meta` provenance block), and
`save_and_index(doc_data, output_path, auto_seed=...)` writes it to
`.king-context/data/<name>.json`. See [export](#export-and-auto_seed).

## The orchestrator: `run_pipeline()`

`run_pipeline(args, config)` in `cli.py` is an async function that walks
`PIPELINE_STEPS` in order. Its responsibilities:

1. **Resolve the corpus name.** From `--name`, or inferred from the URL host by
   `_name_from_url()` (it strips noise labels like `docs`, `api`, `www` and a
   trailing TLD).
2. **Apply `--provider`.** If the flag is set, it does
   `os.environ.setdefault("SCRAPE_PROVIDER", flag_provider)`. `setdefault`
   preserves an explicit pre-existing `SCRAPE_PROVIDER` and only overrides the
   implicit `firecrawl` default. Stage-specific envs still win (ADR-0009).
3. **Resolve providers up front.** It calls
   `get_discovery_provider(resolve_provider_name("discover"))` and
   `get_fetch_provider(resolve_provider_name("fetch"))` once, before any stage
   runs.
4. **Set up the work dir and manifest.** `get_work_dir(args.url)` and
   `_load_manifest(work_dir)`.
5. **Walk the stages**, skipping ones that are not active or already done,
   running the rest, and threading results between them.

### Per-host work directory

`get_work_dir(base_url)` in `discover.py` returns
`.king-context/_temp/<host-slug>/`, where the slug is the URL host with `.`,
`:`, and `/` replaced by `-`. `TEMP_DOCS_DIR` is
`PROJECT_ROOT / ".king-context" / "_temp"`, and `PROJECT_ROOT` is `Path.cwd()`
(`src/king_context/__init__.py`), so the work dir is resolved relative to the
current working directory at process start.

The work dir holds every stage's checkpoint:

```
.king-context/_temp/<host-slug>/
├── manifest.json           # per-stage status
├── discovered_urls.json    # discover output
├── filtered_urls.json      # filter output
├── pages/                  # <slug>.md + <slug>.meta.json
├── chunks/                 # <slug>.json per page
└── enriched/               # batch_0000.json, batch_0001.json, ...
```

For the full on-disk layout, see the
[storage layout reference](../reference/storage-layout.md).

### `manifest.json` checkpoints

`discover.py` owns the manifest helpers (`_load_manifest`, `_save_manifest`,
`_update_step`), which every stage imports. Each stage calls `_update_step` to
record its status under a stage-specific key. `cli.py` maps the CLI step name
to the manifest key:

```python
MANIFEST_KEYS = {
    "discover": "discovery",
    "filter": "filtering",
    "fetch": "fetch",
    "chunk": "chunking",
    "enrich": "enrichment",
    "export": "export",
}
```

A stage is considered complete when its manifest entry has
`status == "done"` (`_step_done()`). The fetch and enrich stages also write
intermediate `status: "in_progress"` entries with running counts so an
interrupted run leaves a useful record.

### Resume and stop: `--step` and `--stop-after`

Both flags accept any value in `PIPELINE_STEPS`.

- **`--step <stage>`** sets the start point. `run_pipeline()` computes
  `active_steps` as the slice of `PIPELINE_STEPS` from that stage onward.
  Stages before the start point are not run; instead their checkpoint
  artifacts are loaded from disk (`discovered_urls.json`, `filtered_urls.json`,
  the `chunks/` JSONs, or the last `enriched/batch_*.json`) so later stages
  still have their inputs.
- **`--stop-after <stage>`** halts the pipeline after the named stage
  completes. The loop breaks once `step == args.stop_after`.

In full-pipeline mode (no `--step`), the orchestrator also skips any stage that
is already marked `done` in the manifest, printing `[<step>] already done,
skipping` and loading that stage's checkpoint for downstream use. This is what
makes a re-run idempotent: a completed scrape that is run again does no extra
work.

The checkpoint is keyed by URL slug, not by provider, so resuming a partial run
with a different backend reuses already-fetched pages. See the
[providers](providers.md) page for the cross-provider resume behavior.

After the loop, `run_pipeline()` prints a summary listing every stage marked
`done` and, when the run reached export, the output path.

## Heuristic filter with LLM fallback

`filter.py` first deduplicates the discovered URLs (`_deduplicate` strips the
query string, fragment, and trailing slash before comparing). It then
classifies each URL by matching its **path** against two regex lists:

- `EXCLUDE_PATTERNS` (checked first): `/blog/`, `/changelog/`, `/pricing`,
  `/login`, `/tag/`, and similar non-doc paths route the URL to `rejected`.
- `INCLUDE_PATTERNS`: `/docs/`, `/api`, `/reference/`, `/guides`,
  `/tutorials`, `/quickstart`, and similar doc paths route the URL to
  `accepted`.
- Anything that matches neither list goes to `maybe`.

The LLM fallback runs only when `config.filter_llm_fallback` is true (it is by
default; `--no-llm-filter` turns it off) **and** the heuristic result looks
weak: fewer than 10 accepted URLs, or a rejected ratio above 0.6. When it
triggers, it sends the `maybe` URLs (plus the `rejected` URLs when accepted is
under 10) to the filter-stage LLM client via `get_client("filter", ...)`. The
model returns a label per URL (`doc`, `maybe`, or `skip`), which moves URLs
between the buckets. On success, `filter_method` becomes `heuristic+llm` and
`llm_fallback_used` is true.

The fallback is defensive: a `ConfigError` or `ProviderError` propagates (so a
misconfigured LLM is a hard error), but any other exception is swallowed and
the heuristic result is kept. The LLM call is bridged into the async stage with
a small `ThreadPoolExecutor` so it works whether or not an event loop is
already running.

The filter LLM client is resolved through the shared LLM provider abstraction
(`src/llm_providers/`). See [providers](providers.md) for stage-prefixed env
resolution and the Ollama to OpenRouter fallback.

## Concurrent fetch

`fetch_pages()` runs `provider.fetch_one(url)` for each URL concurrently, with
parallelism bounded by `asyncio.Semaphore(config.concurrency)` (default 5,
set with `--concurrency`). Each task acquires the semaphore, fetches one page,
and writes two files into `pages/`:

- `<slug>.md`: the page markdown.
- `<slug>.meta.json`: the provenance sidecar, written by `_write_page_meta()`
  with the real `url`, the `slug`, the `content_hash`
  (`sha256` of the UTF-8 markdown), `fetched_at`, and `byte_size`.

The slug comes from `_url_to_slug()`: the scheme is stripped, non-alphanumeric
characters become `-`, runs collapse, and the result is truncated to 200
characters.

A per-task failure never aborts the batch. `_fetch_one()` catches any exception
and returns a `PageResult` with `success=False` and the error string, so one
bad page does not cancel the rest. Progress is checkpointed into the manifest
after each page (`status: "in_progress"` with running `completed`/`failed`
counts), then finalized to `status: "done"`.

### Resume vs force refresh

By default `fetch_pages` is idempotent: it computes the slug for every URL and
skips any whose `<slug>.md` already exists, printing a `Resuming:` line. The
`force_refresh=True` argument disables this slug-skip and refetches every URL.
The full pipeline always uses the default (resume) behavior; the
[update](#the-update-subcommand) subcommand passes `force_refresh=True` so it
detects upstream content drift.

`force_refresh` only disables king-scrape's own slug-skip. The scraper
provider may still serve from its own on-disk cache. The shared
`--no-fetch-cache` flag (`_cache_mode.py`) sets `SCRAPE_CACHE_MODE=bypass`
to bypass that provider cache; only the crawl4ai provider honors it. The flag
uses `setdefault` so an explicit pre-existing `SCRAPE_CACHE_MODE` wins, and it
is always restored in a `finally` block so the env mutation never leaks past
the run.

## Chunking

`chunk_page(markdown, source_url, config)` splits a page at h2 (`## `) and h3
(`### `) header boundaries. Headers inside fenced code blocks are ignored
(the splitter tracks ```` ``` ```` toggles). A page with no headers becomes a
single chunk.

After the raw split, two sizing passes run:

- **Subdivide oversized chunks.** A chunk whose estimated token count exceeds
  `chunk_max_tokens` is split by paragraph via `_subdivide_chunk()`. Markdown
  tables are kept intact during the paragraph split
  (`_split_paragraphs_respecting_tables`).
- **Merge undersized chunks.** A chunk under `chunk_min_tokens` is merged into
  the previous chunk.

Token counts are estimated heuristically as `len(text.split()) * 1.33`. The
defaults are `--chunk-max-tokens 800` and `--chunk-min-tokens 50` (the CLI
defaults in `cli.py`; note `ScraperConfig` carries different field defaults of
1000 / 100 that the CLI overrides).

Each `Chunk` carries `title`, `breadcrumb` (the `h2 > h3` trail), `content`,
`source_url`, `path`, `token_count`, and a `content_hash`. The hash is the
sha256 of the chunk content, computed in `__post_init__` if not supplied. The
`source_url` is recovered from the fetch sidecar by `_resolve_page_url()`: it
prefers the real URL in `<slug>.meta.json` and falls back to the slug for
legacy work dirs that predate the sidecar.

## Enrichment

`enrich_chunks()` resolves its LLM clients via `get_stage_clients("enrich",
...)`, which returns a primary client and an optional schema-fallback client.
It then processes chunks in batches of `config.enrichment_batch_size` (10).

### Per-chunk flow

`_enrich_one()` enriches a single chunk and never raises; it returns `None` on
terminal failure so a batch can drop one chunk and keep going. For each chunk:

1. **Cache lookup.** A key is computed from the chunk content, model id, and
   `PROMPT_VERSION`, then `enrich_cache.get()` is checked. A cached value that
   still passes `validate_enrichment()` short-circuits the LLM call.
2. **Primary client, up to three attempts.** A successful, valid response is
   cached and returned. A transient `ProviderError` is retried within the
   budget; a non-transient one breaks early and falls through to the schema
   fallback. Validation failures use the full retry budget.
3. **Schema fallback.** If the primary exhausts its attempts and a schema
   fallback client exists, the prompt is retried once on it. A valid response
   is returned but **not** cached. Caching only successful primary responses
   keeps the cache from serving fallback output as if it were primary on the
   next run.

`validate_enrichment()` enforces the shape: 5 to 12 `keywords`, 2 to 7
`use_cases`, 1 to 5 `tags`, and an integer `priority` from 1 to 10.

### Batch resilience and checkpoints

`enrich_chunks()` gathers each batch with `return_exceptions=True`, so a stray
raise or a per-task cancellation is counted as a dropped chunk rather than
canceling the in-flight batch. After each batch it writes
`enriched/batch_NNNN.json` (the cumulative enriched list) and updates the
manifest. On a resumed run, it reads the last batch file, reconstructs the
already-enriched chunks, and continues from where the previous run stopped.

### The enrichment cache (`enrich_cache.py`)

The cache is content-addressed: one JSON file per key under
`.king-context/cache/enrichment/`. `make_key(content, model, prompt_version)`
hashes each component to a fixed-length sha256 digest, concatenates the
digests, and hashes again. Fixed-length digests avoid the delimiter-collision
risk that a character separator would create when content contains the
delimiter (markdown tables use `|`).

Because the key bakes in the model id and the prompt version, swapping the
model or editing the prompt silently invalidates prior entries.
`PROMPT_VERSION` is derived from the prompt text itself
(`sha256(ENRICHMENT_PROMPT)[:16]`), so any prompt edit auto-invalidates the
cache with no manual bump. Writes are atomic (`tempfile.mkstemp` plus
`os.replace`); reads return `None` on any failure, which callers treat as a
miss and re-enrich.

### Cost estimate

`estimate_cost()` computes a per-run estimate from chunk token counts and the
batch size, used for the confirmation prompt before enrichment runs (`--yes`
skips the prompt). When the resolved enrich provider is `openrouter`, it
reports a dollar figure; when the provider is Ollama, it reports a local-runtime
note instead, and warns if OpenRouter fallback is enabled. The dollar figure is
a fixed heuristic (the pricing constants in `enrich.py` are hardcoded) and is
not derived from the actual model's live pricing.

## Export and `auto_seed`

`export_to_json()` builds the corpus dict. Each section carries the retrieval
metadata (`title`, `path`, `url`, `keywords`, `use_cases`, `tags`, `priority`,
`content`) plus a per-section `_meta` block with the chunk `content_hash`. The
section `path` is sanitized so `/` becomes `-` (no accidental subdirectories at
index time).

The corpus also gets a top-level `_meta` provenance block (ADR-0012):

```json
"_meta": {
  "schema_version": 1,
  "scraper_version": "<king-context version>",
  "scraped_at": "<UTC ISO timestamp>",
  "source_url": "<base_url>",
  "section_count": <n>
}
```

`save_and_index()` writes the JSON to
`.king-context/data/<name>.json` and, when `auto_seed` is true (the default;
`--no-auto-seed` turns it off), calls `seed_data.seed_one()`.

**Important.** `auto_seed` feeds the **legacy** stack. `seed_one()` writes into
the SQLite `docs.db` used by the MCP server (`server.py` plus `db.py`), which
is the legacy/secondary stack per ADR-0001. It does **not** populate the
canonical `kctx` flat-file store under `.king-context/docs/`. The two stacks do
not share data. The shipped scraper-workflow skill therefore instructs agents
to pass `--no-auto-seed` and then run `kctx index .king-context/data/<name>.json`
to index into the canonical CLI store. For the MCP stack, see
[mcp-legacy](mcp-legacy.md); for the CLI retrieval store, see
[cli-retrieval](cli-retrieval.md).

## Subcommand dispatch

`king-scrape` does not use argparse subparsers for `audit` and `update`.
`cli.main()` sniffs `sys.argv[1]`: if it is `audit` it calls
`audit_main(sys.argv[2:])`, if it is `update` it calls
`update_main(sys.argv[2:])`, and otherwise it parses the bare
`king-scrape <url>` form and runs `run_pipeline()`. The subcommand modules are
imported lazily inside `main()` so the default scrape path stays lean.

### Exit codes

The scrape path in `cli.main()` maps two exceptions to non-zero exit codes:

| Exit code | Cause |
| --- | --- |
| `2` | `ValueError` (for example an invalid argument surfaced by `load_config`) |
| `3` | `ProviderUnavailableError` (a selected provider is not installed; the error's `hint` is printed) |

Non-zero exit codes other than `1` exist only in the scraper CLI. Each
subcommand owns its own scheme, so the same integer can mean different things:
the scrape path in `cli.py` uses `2` for `ValueError` and `3` for
`ProviderUnavailableError`; `update_main` (`update.py`) uses `1` for a
`ValueError` or user abort and `3` for `ProviderUnavailableError`; `audit_main`
(`audit.py`) uses `1` for a load failure and `2` to signal broken URLs (it never
returns `3`). The `kctx` CLI uses `sys.exit(1)` everywhere instead.

## The `audit` subcommand

`king-scrape audit <name>` (ADR-0013) is a read-only drift check. It never
mutates the corpus JSON or any database, and the URL health pass needs no
provider key, so it is safe to run on a CI cron.

`audit_main()` in `audit.py`:

1. Resolves the corpus with `find_corpus()`, which searches
   `.king-context/data/<name>.json` first, then the repo-local
   `data/<name>.json`.
2. Extracts the unique section URLs (deduped by `canonicalize_url`).
3. Probes each URL concurrently (`--concurrency`, default 10) with an httpx
   client. It tries HEAD first, retries as GET on 405/501, and on a 429 honors
   `Retry-After` (capped at 30s) once before re-probing.
4. Classifies each URL by its **final** HTTP status:

| Status | Meaning |
| --- | --- |
| `fresh` | 2xx, no redirect |
| `moved` | redirect chain ending in 2xx (the final URL is captured) |
| `broken` | 404 / 410, including chains that redirect into a dead page |
| `throttled` | 429 |
| `auth_required` | 401 / 403 |
| `unreachable` | timeout, network error, or other 5xx |

When discovery is enabled (the default; `--no-discover` skips it), it calls the
configured `DiscoveryProvider` to remap the upstream and diffs the result
against the corpus URLs by canonical form, reporting `new` (upstream-added) and
`orphan` (corpus-only) URLs.

It writes a Markdown report to `.king-context/audit/<name>-<timestamp>.md`
(`--report-dir` overrides the directory; the timestamp is UTC with microsecond
precision and a trailing `Z`). The exit code is **`2`** if any URL is `broken`
and **`0`** otherwise, so the audit can gate a CI job. A corpus that cannot be
found or parsed returns `1`.

## The `update` subcommand

`king-scrape update <name>` (ADR-0014) is an incremental refresh that pays LLM
cost only for new or changed chunks.

`update_corpus()` in `update.py` re-runs discover, filter, fetch (with
`force_refresh=True`), and chunk against the corpus's source URL, then reuses
every section whose chunk `content_hash` is unchanged. The integrity unit is
the same `sha256(content)` used everywhere else (ADR-0012).

The flow:

1. **Load and validate the corpus.** It refuses a legacy corpus that lacks a
   `_meta` block (raising `ValueError`), because the `base_url` fallback on
   such files would trigger a full host rescrape. The source URL is resolved
   from `_meta.source_url`, falling back to `base_url`.
2. **Reset the work dir.** `_reset_work_dir()` wipes `pages/`, `chunks/`,
   `enriched/`, and `manifest.json` so stale state from a prior run cannot leak
   into the new corpus (in particular, stale enrich batches would otherwise
   trigger the resume path and return old content).
3. **Discover, filter, fetch (force refresh), chunk.**
4. **Plan the diff.** `_build_reuse_index()` maps each existing section's
   `content_hash` to its enrichment values; `_plan_update()` sorts fresh chunks
   into `reused` (hash hit) and `new` (hash miss), and computes added/removed
   URL sets by canonical form.
5. **Confirm cost.** It prints reused / new / removed / added counts plus a
   cost estimate, then prompts unless `--yes`.
6. **Enrich only the new chunks**, carry forward enrichment for reused chunks
   (taking fresh `title` / `path` / `url` so an upstream reorganization is
   reflected), and interleave the result in fresh-chunk order.
7. **Write atomically.** `_atomic_write_json()` (tempfile plus `os.replace`)
   overwrites the same corpus path, so an interrupted update never leaves a
   partial file and `git diff` shows exactly what changed.

### Guard rails

`update` refuses to write back when the refresh looks unsafe, preserving the
existing corpus on disk:

| Guard | Threshold | Behavior |
| --- | --- | --- |
| Discover loss | `DISCOVER_LOSS_RATIO_THRESHOLD = 0.50` | Abort before fetch if more than half the corpus URLs are missing from fresh discovery |
| Fetch failure | `FETCH_FAILURE_RATIO_THRESHOLD = 0.10` | Abort before writeback if more than 10% of accepted URLs failed to fetch |
| Empty result | n/a | Abort if discover/filter produced zero chunks over a non-empty corpus |
| Missing `_meta` | n/a | Refuse a legacy pre-ADR-0012 corpus |

Both ratio thresholds are strict-`>` boundaries, so a value exactly on the line
passes (a 1-of-10 fetch failure at 0.10 is allowed; 2-of-10 aborts).

### `auto_seed` is off for update

Unlike the full pipeline, `update` does not auto-seed. It writes back to the
corpus JSON only. After a successful update, refresh the canonical CLI store
with `kctx index .king-context/data/<name>.json` (or `kctx index --all`).

`update_main()` snapshots `SCRAPE_PROVIDER` so `--provider` does not leak past
the call boundary (the flag wins during the run, but the prior env is restored
on exit). It returns `1` on a `ValueError` or user abort, `3` on a
`ProviderUnavailableError`, and `0` on success.

## Related ADRs

- **ADR-0012** content-hash provenance and the enrichment cache
  (`content_hash`, `_meta` blocks, `enrich_cache.py`).
- **ADR-0013** the corpus drift audit subcommand.
- **ADR-0014** incremental corpus refresh.

Use `kctx adr read ADR-0012` (and `ADR-0013`, `ADR-0014`) to read the full
decisions. See the [ADR workflow](../contributing/adr-workflow.md) for how
decisions are recorded.

## See also

- [Architecture overview](overview.md)
- [Providers](providers.md)
- [CLI retrieval store](cli-retrieval.md)
- [Research pipeline](research-pipeline.md)
- [MCP legacy stack](mcp-legacy.md)
- [Corpus schema reference](../reference/corpus-schema.md)
- [Environment variables reference](../reference/env-vars.md)
- [Storage layout reference](../reference/storage-layout.md)
- [CLI guide](../CLI_GUIDE.md)
- [Claude Code skills](../skills.md): the scraper-workflow skill that drives this pipeline
