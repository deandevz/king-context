# Architecture overview: the two retrieval stacks

King Context is a CLI-first, local-first retrieval layer for AI agents. This
document is the deep dive on how the codebase is actually organized: it hosts
**two parallel retrieval stacks** that do not share data. The high-level
four-piece model (scrape, research, index, search) lives in
[`../architecture.md`](../architecture.md). This page explains the two stacks,
why they are separate, the installable packages behind them, and where to read
next.

If you only read one thing: the `kctx` CLI stack is canonical, the MCP server
stack is legacy and secondary, per [ADR-0001](#why-two-stacks-adr-0001-and-adr-0005).

## The two stacks at a glance

| | Canonical CLI stack | Legacy MCP stack |
|---|---|---|
| Entry point | `kctx` (`context_cli.cli:main`) | `king-context-server` (`king_context.server:main`) |
| Package | `src/context_cli/` | `src/king_context/` (`server.py`, `db.py`, `seed_data.py`) |
| Storage | Flat JSON under `.king-context/` | `docs.db` SQLite file at project root |
| Retrieval | Reverse-index keyword scoring, pure Python | 4-layer cascade: cache, metadata, FTS5, embeddings |
| Dependencies for search | None beyond stdlib | `fastmcp`, `sentence-transformers`, `numpy` |
| Status | Canonical (ADR-0001) | Legacy / secondary integration surface |

The same query can return different results on each stack because they index
different data with different scoring. That is by design and is the central
reason the local UI is forbidden from touching the legacy stack
(see [ADR-0005](#why-two-stacks-adr-0001-and-adr-0005)).

## Canonical stack: the `kctx` CLI

The `kctx` CLI in `src/context_cli/` is the primary interface. It is pure
Python, file-based, and uses no SQLite and no embeddings.

### Storage

All data lives as flat JSON under `.king-context/`:

- `.king-context/docs/`: indexed documentation corpora (`STORE_DIR`).
- `.king-context/research/`: indexed research corpora (`RESEARCH_STORE_DIR`).
- `.king-context/decisions/`: the derived ADR decision index root
  (`DECISIONS_STORE_DIR`). The ADR layer writes the project index under
  `.king-context/decisions/project/` (`PROJECT_DECISIONS_DIR` in
  `src/context_cli/adr.py`, derived as `DECISIONS_STORE_DIR / "project"`).
- `.king-context/adr/`: human-readable ADR Markdown source files.

`STORE_DIR`, `RESEARCH_STORE_DIR`, and `DECISIONS_STORE_DIR` resolve from
`Path.cwd()` in `src/context_cli/__init__.py`, so paths are relative to the
project where King Context is installed.

`src/context_cli/indexer.py` converts a monolithic `data/<name>.json` export
into the exploded store layout: `index.json` (corpus metadata),
`sections/<path>.json` (one file per section, with a `token_estimate`), and the
three reverse indexes `keywords.json`, `use_cases.json`, and `tags.json`.

### Retrieval: reverse-index scoring

`src/context_cli/searcher.py` scores sections against the reverse indexes with a
fixed weighting (`_score_sections_in_doc`):

- keyword exact match: weight 3,
- use-case substring match: weight 2,
- tag exact match: weight 1,
- plus `priority * 0.5` added to the section's accumulated score.

Results are sorted by score descending and truncated to `--top`. There is no
full-text scan, no BM25, and no vector similarity. `src/context_cli/grep.py`
adds line-level case-insensitive regex search (`re.IGNORECASE`) over the same
section content, and `src/context_cli/reader.py` returns a single section with an
optional `--preview` (first ~150 words) plus fuzzy "did you mean" suggestions on
a miss.

### Command surface

`kctx` exposes 9 top-level subcommands wired in `src/context_cli/cli.py`:
`list`, `search`, `read`, `grep`, `topics`, `index`, `llm-doctor`, `adr`, `ui`.
Most read commands understand a multi-store model via
`--source {all,docs,research}` (default `all`). The full reference is in
[`../CLI_GUIDE.md`](../CLI_GUIDE.md), the retrieval mechanics in
[`cli-retrieval.md`](cli-retrieval.md).

The `adr` subcommand (`src/context_cli/adr.py`) is a sub-application of its own:
it parses YAML-frontmatter Markdown ADRs, maintains a reciprocal
supersedes/related graph, and rebuilds the JSON decision index. See
[`../contributing/adr-workflow.md`](../contributing/adr-workflow.md).

The `ui` command is the one place the CLI reaches outside `context_cli`:
`_cmd_ui` imports `king_context.web.server.main`. That web UI reads the CLI
flat-file surface only, never the legacy SQLite layer (ADR-0005). See
[`local-ui.md`](local-ui.md).

### Error convention

Commands that must abort print to stderr and call `sys.exit(1)`. The CLI uses
`sys.exit(1)` everywhere; it does not use the differentiated exit codes that the
scraper CLI defines. The ADR layer raises a typed error caught at the command
boundary and then exits 1.

## Legacy stack: the MCP server

The MCP stack is `server.py` plus `db.py` plus `seed_data.py`, all under
`src/king_context/`. It is the original "documentation server" surface. ADR-0001
demotes it to a secondary integration layer.

### Entry point and tools

`src/king_context/server.py` builds a FastMCP server (`mcp = FastMCP("king-context")`)
exposing 4 MCP tools that delegate to `db.py`:

- `search_docs`,
- `list_docs`,
- `show_context`,
- `add_doc`.

`main()` calls `init_db()`, then `_load_embeddings()` (which loads the
`all-MiniLM-L6-v2` SentenceTransformer model and the persisted numpy array, with
graceful fallback when files are missing), then `mcp.run()`. It is reachable as
the `king-context-server` console script or via `python -m king_context.server`.

### Storage and the cascade

`src/king_context/db.py` is the real engine. `init_db()` creates a 4-table
SQLite schema in `docs.db` (resolved as `DB_PATH = PROJECT_ROOT / "docs.db"`):

- `documentations`: corpus metadata,
- `sections`: section content plus JSON-serialized keywords/use_cases/tags,
- `sections_fts`: an FTS5 external-content virtual table
  (`content='sections'`, `content_rowid='id'`),
- `query_cache`: normalized query to section-id mapping.

`search_cascade()` runs the 4-layer cascade and stops at the first hit:

1. **cache**: exact normalized query previously executed,
2. **metadata**: match on keywords, use_cases, tags,
3. **FTS5**: BM25 full-text search over ~20 candidates,
4. **hybrid rerank**: cosine similarity over the embeddings, with FTS-only
   fallback when embeddings are unavailable or all candidates filter out.

Every response carries a `transparency` object (`method`, `latency_ms`,
`search_path`, `from_cache`). Embeddings persist to `data/embeddings.npy` and
`data/_internal/section_mapping.json`. The full mechanics are in
[`mcp-legacy.md`](mcp-legacy.md).

### The remaining write path

`src/king_context/seed_data.py` is still the live writer into `docs.db`:
`seed_one(path)` and `seed_all()` call `db.insert_documentation()`. The scraper's
`export.save_and_index()` defaults to `auto_seed=True`, which calls
`seed_data.seed_one()`. That write path is internal-legacy: the canonical index
path for the CLI stack is `kctx index`, which writes to `.king-context/` and
never touches `docs.db`.

## Why two stacks: ADR-0001 and ADR-0005

The split is a recorded architectural decision, not an accident. Read the
sources directly:

- [`.king-context/adr/0001-adopt-cli-first-architecture-for-agent-retrieval.md`](../../.king-context/adr/0001-adopt-cli-first-architecture-for-agent-retrieval.md)
  (ADR-0001, accepted 2026-05-02). The CLI is the canonical product interface
  for retrieval, indexing, validation, research, and decision memory. MCP "may
  continue to exist as an integration layer, but it should not define the
  primary architecture, block CLI capabilities, or require parity before CLI
  features ship."
- [`.king-context/adr/0005-local-ui-server-reads-cli-flat-file-surface-not-mcp-sqlite-layer.md`](../../.king-context/adr/0005-local-ui-server-reads-cli-flat-file-surface-not-mcp-sqlite-layer.md)
  (ADR-0005, accepted 2026-05-06). It states the two surfaces plainly: the
  legacy surface in `king_context/db.py` uses SQLite, FTS5, and a ~500MB
  SentenceTransformer model; the current surface in `context_cli/` uses flat
  JSON with reverse-index scoring. The local UI reads exclusively from the CLI
  surface and must not import `king_context.db`, must not open `docs.db`, and
  must not load an embedding model.

The two stacks do not share data: the CLI never reads `docs.db`, and the MCP
server never reads `.king-context/docs/`. ADR-0005 names this directly as a
reason to keep the UI off the legacy layer, since two surfaces can return
different results for the same query.

## The four installable packages

`pyproject.toml` builds four packages into the wheel
(`[tool.hatch.build.targets.wheel]`):

| Package | Role |
|---|---|
| `king_context` | Legacy MCP stack (`server.py`, `db.py`, `seed_data.py`), the scraper (`scraper/`), research (`research/`), and the local web UI (`web/`). |
| `context_cli` | The canonical `kctx` CLI: search, read, grep, topics, index, ADR memory, UI launcher. |
| `llm_providers` | Provider abstraction for LLM stages (OpenRouter, Ollama) used by the scraper and research, with config resolution and one-way fallback. |
| `scraper_providers` | Pluggable scraper backends (Firecrawl, Crawl4AI), registered via the `king_context.scraper_providers` entry-point group. |

`pyproject.toml` declares four console scripts (`[project.scripts]`):

| Script | Target | Stack |
|---|---|---|
| `kctx` | `context_cli.cli:main` | Canonical CLI |
| `king-scrape` | `king_context.scraper.cli:main` | Scraper pipeline |
| `king-research` | `king_context.research.cli:main` | Research pipeline |
| `king-context-server` | `king_context.server:main` | Legacy MCP server |

### Exit code note

Differentiated exit codes exist only in the scraper CLI
(`src/king_context/scraper/cli.py`): exit `3` for `ProviderUnavailableError` and
exit `2` for `ValueError`, so a CI job can distinguish a missing backend from a
bad argument. The `kctx` CLI uses `sys.exit(1)` everywhere and does not adopt
these codes.

## Where to read next

The remaining architecture deep-dives split the system by surface:

- [`cli-retrieval.md`](cli-retrieval.md): the canonical CLI retrieval engine in detail.
- [`scraper-pipeline.md`](scraper-pipeline.md): `king-scrape` discover, filter, fetch, chunk, enrich, export.
- [`research-pipeline.md`](research-pipeline.md): `king-research` topic-to-corpus flow.
- [`providers.md`](providers.md): the `llm_providers` and `scraper_providers` abstractions.
- [`local-ui.md`](local-ui.md): the read-only local web UI and why it reads the CLI surface (ADR-0005).
- [`mcp-legacy.md`](mcp-legacy.md): the legacy MCP server and SQLite cascade in depth.

Reference material:

- [`../reference/corpus-schema.md`](../reference/corpus-schema.md): the enriched section JSON schema.
- [`../reference/env-vars.md`](../reference/env-vars.md): environment variables.
- [`../reference/storage-layout.md`](../reference/storage-layout.md): the `.king-context/` layout.

Contributing:

- [`../contributing/code-style.md`](../contributing/code-style.md): style conventions, including the typing rule below.
- [`../contributing/testing.md`](../contributing/testing.md): test patterns per package.
- [`../contributing/commits-and-prs.md`](../contributing/commits-and-prs.md): commit and PR conventions.
- [`../contributing/adr-workflow.md`](../contributing/adr-workflow.md): recording decisions with `kctx adr`.
- [`../skills.md`](../skills.md): the Claude Code skills that drive these surfaces.

### A note on type hints

New code uses PEP 604 unions (`X | None`). Legacy core modules keep
`typing.Optional` for local consistency: the criterion is whether the
surrounding module already uses one style, not a fixed list of files. For
example, `db.py` is dense with `Optional[...]`, while newer CLI modules such as
`searcher.py` use `str | None`. Match the file you are editing.
