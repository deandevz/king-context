# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `db.insert_documentation` (called by `seed_data.seed_one` and the scraper's
  auto-seed step) is now an upsert. Re-seeding the same corpus name no longer
  raises `sqlite3.IntegrityError` against `documentations.name UNIQUE`. The
  documentations row is upserted via `INSERT ... ON CONFLICT(name) DO UPDATE
  ... RETURNING id`, which keeps the original `created_at` and the existing
  `doc_id` stable across refreshes. Sections, their `query_cache` entries
  (via `ON DELETE CASCADE`), and their `sections_fts` index entries (via the
  FTS5 'delete' protocol) are then cleared and the fresh sections inserted
  in the same SQLite transaction. Embedding writes to `data/embeddings.npy`
  and `data/_internal/section_mapping.json` are deferred until after the
  commit, so a rollback never leaves the numpy sidecar ahead of the
  committed DB state. Closes #48.
- `db._get_connection` now executes `PRAGMA foreign_keys = ON` on every
  connection. Without this, `ON DELETE CASCADE` on `sections.doc_id` and
  `query_cache.section_id` was a silent no-op for everything outside
  `init_db`, leaving orphan rows after deletes. The upsert above relies on
  the cascade, but every other delete path benefits too.
- A single chunk's `ProviderError` no longer aborts the entire concurrent
  enrich batch (#47). `_enrich_one` is now contract-bound never to raise:
  non-transient primary errors break the retry loop early and fall through
  to the schema fallback (the layer designed to absorb malformed JSON);
  the schema fallback's own failures are absorbed; the chunk is dropped
  from the output and the batch keeps running. `enrich_chunks` adds
  `return_exceptions=True` to its `asyncio.gather` call as a defensive
  guard. Per-chunk failures and per-task `CancelledError`s emit a warning
  on stderr and a per-batch summary line (`batch NNNN: X enriched, Y
  dropped`) so contributors can see exactly how many chunks were lost.
- The schema fallback's enrichments are no longer cached under the
  primary client's cache key. Pre-fix, a successful schema-fallback
  response was written to `enrich_cache` keyed by the primary's model;
  next run with the primary healthy would short-circuit at the cache
  check and serve fallback content as if it were primary. The cache
  invariant is now: only successful primary responses are cached.
- `enrich_chunks` deduplicates the schema fallback when the primary is a
  `FallbackClient` whose own fallback leg points at the same underlying
  client. Pre-fix this configuration paid for two LLM calls against the
  same client per failed chunk; now the schema-fallback step is skipped
  and the FallbackClient's internal fallback is the only call.
- The bare `except Exception` in `_enrich_one` was narrowed to
  `(ProviderError, asyncio.TimeoutError, ValueError, json.JSONDecodeError)`
  so programming errors (`AttributeError`, `TypeError`, etc.) propagate
  instead of being silently retried as transient provider hiccups.

### Added

- `--no-fetch-cache` flag on `king-scrape` and `SCRAPE_CACHE_MODE` env
  var (#50). Bypasses the Crawl4AI provider's local cache (`~/.crawl4ai/`)
  for the duration of the run without wiping the cache directory by hand.
  `SCRAPE_CACHE_MODE` accepts `bypass`, `disabled`, `read_only`,
  `write_only`, or `default`/unset. The CLI flag is shorthand for
  `SCRAPE_CACHE_MODE=bypass` and uses `setdefault` semantics so an
  explicit pre-existing env value wins (mirrors `--provider`'s
  precedence). `main()` restores the prior env value on exit so the
  flag does not leak into an embedding application or test session.
  Honoured by the crawl4ai provider; firecrawl ignores it (its API
  defaults to fresh-fetch). Knob is global today; per-stage variants
  (`SCRAPE_DISCOVER_CACHE_MODE` / `SCRAPE_FETCH_CACHE_MODE`) deferred
  to a follow-up if real configurations need them. Lays the primitive
  `king-scrape update <name>` needs to make `force_refresh=True`
  actually fetch from the network.
- Content-hash provenance through every layer of the scraper pipeline
  (ADR-0012). `Chunk` and `EnrichedChunk` carry a `content_hash` field
  populated by `sha256(content)`. Each fetched page now writes a sidecar
  `pages/<slug>.meta.json` containing `{ url, slug, content_hash,
  fetched_at, byte_size }`. The exported `data/<name>.json` gains an
  optional `_meta.content_hash` per section and a top-level `_meta` with
  `schema_version`, `scraper_version`, `scraped_at`, `source_url`, and
  `section_count`. All `_meta` fields are optional; older corpora and
  consumers that don't recognise them continue to work unchanged.
- File-per-hash enrichment cache at
  `.king-context/cache/enrichment/<sha256>.json`. Cache key is
  `sha256(content + model_id + prompt_version)`. Writes are atomic via
  `tempfile` + `os.replace`. A rerun on unchanged content (or a rechunk
  that produces structurally identical chunks) pays zero LLM cost.
- `king-scrape audit <name>` subcommand (ADR-0013). Walks the URLs of
  an indexed corpus and classifies each by its final HTTP status:
  `fresh` (2xx), `moved` (redirect chain ending in 2xx, with the final
  URL captured), `broken` (final 404/410, including chains that
  redirect into a dead page), `throttled` (429, retried once with
  `Retry-After`), `auth_required` (401/403), or `unreachable`. URLs
  are canonicalised (fragment / trailing slash / host case) before
  dedupe and discovery diff. Optionally reruns discovery against the
  upstream and reports URLs added or removed since the corpus was
  indexed (`--no-discover` to skip). Read only, never mutates the
  corpus file or the database. No LLM cost. Markdown report lands at
  `.king-context/audit/<name>-<ts>.md`. Exit code is `0` on clean,
  `2` when at least one section is broken, so it can gate a CI job.
- `king-scrape update <name>` subcommand (ADR-0014). Refetches the
  upstream of an indexed corpus, rechunks, and reuses every section
  whose chunked content is byte identical to the previous scrape.
  Only new or changed chunks are sent to the LLM, so a typical
  refresh costs cents instead of dollars even on a large corpus.
  Reused sections carry forward `keywords`, `use_cases`, `tags`,
  `priority` from the existing corpus but adopt fresh `title`,
  `path`, `url` so a page reorganisation upstream is reflected.
  Cost preview before enrichment; `--yes` skips the prompt. Writes
  back to the same `data/<name>.json` path so `git diff` shows
  exactly what changed. Pre ADR-0012 corpora (no
  `_meta.content_hash`) are handled by recomputing the hash from
  `content`. The work directory is reset at the start of every
  update and the corpus JSON is written atomically (tempfile plus
  rename). `fetch_pages` gains a `force_refresh=True` flag so the
  update flow can refetch every URL regardless of cached state.

## [0.4.0] - 2026-05-06

### Added

- Pluggable scraper provider abstraction for `king-scrape`. Choose backend
  via `SCRAPE_PROVIDER` env var or `--provider` flag. Stage-aware overrides
  via `SCRAPE_DISCOVER_PROVIDER` and `SCRAPE_FETCH_PROVIDER`. Mirrors the
  layout of `src/llm_providers/` (ADR-0009, ADR-0010).
- Crawl4AI local backend (beta, ADR-0011). Bundled by default in the
  `[all]` extra that `npx @king-context/cli init` runs, so the package
  ships in the project venv. Activation only requires running
  `crawl4ai-setup` once to download the Playwright chromium.
- `.github/workflows/test.yml` with a `test` job (pytest on the firecrawl
  path) and a `smoke-crawl4ai` job that runs `scripts/smoke-crawl4ai.py`
  to detect API churn across `crawl4ai>=0.8.5,<0.9` minor versions.

### Changed

- `firecrawl-py` moved from core dependencies to the `[firecrawl]` extra.
  `npx @king-context/cli init` continues to install everything via the
  `[all]` extra, so the default flow is preserved with no breaking
  change.
- `installer/lib/python.js` now installs `king-context[all]` via PEP 508
  direct reference (`king-context[all] @ git+...`), so `init` and
  `update` keep pulling firecrawl-py and crawl4ai after the core
  dependency move.

## [0.3.2] - 2026-05-06

### Added

- `kctx ui` command: local read-only web UI (stdlib HTTP, port 7373 with
  auto-increment, bind 127.0.0.1 only) for browsing ADRs, indexed docs,
  and research stored under `.king-context/`. Reads through the CLI
  flat-file surface; no write paths in the MVP. Static assets and
  templates are bundled inside the Python wheel.
  ([#44](https://github.com/deandevz/king-context/pull/44))
- ADR-0005 to ADR-0008: record decisions on flat-file source of truth,
  read-only MVP scope, stdlib HTTP with adapter-swap design, and
  bundling UI assets in the Python wheel.
- `docs/ui-local.md` plus screenshots under `docs/assets/ui-local/`,
  linked from `README.md` and `docs/index.md`.
- `markdown>=3.5` runtime dependency for HTML rendering of stored
  Markdown.

### Changed

- `installer/templates/claude-md-snippet.md`: surface `kctx ui` to
  installed projects.

## [0.3.1] - 2026-05-06

### Added

- Windows support for the installer (beta). `king-context init`, `update`,
  and `doctor` now work on Windows: `py -3` detection, `Scripts\python.exe`
  resolution, `python -m pip` invocation, and `.cmd` shims for `kctx`,
  `king-scrape`, and `king-research`. Existing macOS and Linux behavior is
  preserved. Co-authored with @Vadelo (issue #19).
- ADR-0004: treat multi-OS compatibility (macOS, Linux, Windows) as a
  baseline development constraint.

### Changed

- Path helpers in `installer/lib/python.js` now use `path.win32` /
  `path.posix` based on `process.platform`, so Windows path assertions
  pass on any host.
- Removed orphan `installer/templates/wrapper-*.sh` files. Wrapper bodies
  are inlined in `scaffold.js` and the templates are no longer read.

## [0.3.0] - 2026-05-05

### Added

- Beta Ollama and local model support via a new pluggable provider layer
  in `src/llm_providers/`. `king-scrape`, `king-research`, and the new
  `kctx llm-doctor` command can now talk to OpenRouter, Ollama local
  (OpenAI-compatible), Ollama native/cloud, and an optional Ollama to
  OpenRouter fallback. Default behavior for existing OpenRouter users is
  unchanged. ([#40](https://github.com/deandevz/king-context/pull/40))
- Stage-aware provider configuration via new env vars: `ENRICH_*`,
  `FILTER_*`, `RESEARCH_*`, `OLLAMA_*`, `CONCURRENCY_*`, and
  `ENABLE_FALLBACK`. Centralized `.king-context/.env` and `.env` loading
  through `src/king_context/env.py`.
- `kctx llm-doctor` diagnostics command and a Node-side `doctor` Ollama
  hook (warning only) so users can verify provider, model, and
  reachability before running a stage.
- ADR-0003 recording the pluggable LLM provider decision, plus
  `docs/ollama.md` setup guide and updated `docs/CLI_GUIDE.md` LLM
  section, EN/PT-BR READMEs, installer env template, and king-context
  skills.

### Changed

- Bumped the Python package version from `0.2.0` to `0.3.0` so it matches
  the npm installer release and the `v0.3.0` GitHub tag. Code already
  shipped in v0.3.0, this is metadata only.
  ([#41](https://github.com/deandevz/king-context/pull/41))

### Removed

- Untracked `.specs/features/local-models-enrichment/human.md` that
  slipped through the `.specs/` gitignore rule in the previous PR. Local
  copy preserved on disk and now ignored as intended.
  ([#41](https://github.com/deandevz/king-context/pull/41))

## [0.2.1] - 2026-05-02

### Fixed

- Installer now passes `--no-cache-dir` (and `--force-reinstall --no-deps`
  on upgrade) when installing the `king-context` Python package from git.
  Previously, pip cached the built wheel under the unchanged version
  `0.1.0`, so `init`/`update` silently reused the stale wheel and missed
  new commits on `main` (e.g. the ADR commands shipped in 0.2.0). Bumped
  the Python package version to `0.2.0` so cached wheels from earlier
  installs are no longer matched.

## [0.2.0] - 2026-05-02

### Added

- ADR (Architecture Decision Record) memory for the CLI. New `kctx adr`
  subcommands let agents record, list, and recall architectural decisions
  across sessions. Two new skills (`king-decisions` and `king-record-decision`)
  plug into Claude Code so agents use the decision log without manual
  prompting. Installer now scaffolds an `.king-context/adr/` directory and
  seeds it with two example ADRs that document the project's own
  architectural choices.

### Changed

- Renamed the Python MCP server console script from `king-context` to
  `king-context-server`. The `king-context` name is reserved for the npm
  installer (`@king-context/cli`), which is the user facing entry point.
  Users with a Claude Code or Claude Desktop MCP config that points at
  `king-context` should update it to `king-context-server`. The
  `python -m king_context.server` invocation is unchanged.
