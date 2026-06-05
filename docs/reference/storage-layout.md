# Storage layout

King Context is a CLI-first, local-first retrieval layer for AI agents. Everything it stores lives on disk under a single project directory, `.king-context/`, resolved from the current working directory. This reference maps every directory in that tree, says which ones are authoritative for the CLI stack, and explains the separate, legacy repo-root locations that belong only to the MCP server.

## Where paths come from

Both the Python CLI and the Node installer resolve all paths from the process working directory.

- The CLI defines its roots in `src/context_cli/__init__.py`:

  ```python
  PROJECT_ROOT = Path.cwd()
  STORE_DIR = PROJECT_ROOT / ".king-context" / "docs"
  RESEARCH_STORE_DIR = PROJECT_ROOT / ".king-context" / "research"
  DECISIONS_STORE_DIR = PROJECT_ROOT / ".king-context" / "decisions"
  ```

- The scraper and research packages resolve from the same `PROJECT_ROOT = Path.cwd()` (`src/king_context/__init__.py`). For example `TEMP_DOCS_DIR = PROJECT_ROOT / ".king-context" / "_temp"` (`src/king_context/scraper/discover.py`) and `DEFAULT_CACHE_DIR = PROJECT_ROOT / ".king-context" / "cache" / "enrichment"` (`src/king_context/scraper/enrich_cache.py`).

- The installer mirrors this on the Node side: every operation targets `process.cwd()` and never asks for or records an absolute install path.

The practical implication: run `kctx`, `king-scrape`, and `king-research` from the project root. If you invoke them from a subdirectory, `Path.cwd()` points there and the tools will look for (or create) a `.king-context/` tree in the wrong place.

## The `.king-context/` tree

The installer's `createDirs()` step creates nine directories (`installer/lib/scaffold.js`, `DIRS`):

```
.king-context/
  bin/         CLI wrapper shims (kctx, king-scrape, king-research)
  core/        Python virtual environment (core/venv)
  data/        Raw corpus JSON exported by the scraper and research tools
  docs/        Per-doc flat-file retrieval store (the CLI search surface)
  adr/         Architecture Decision Records as human-readable markdown
  decisions/   Derived, indexed ADR store (decisions/project/)
  research/    Per-topic flat-file research store (parallel to docs/)
  _learned/    Agent self-learning shortcuts
  _temp/       Scraper work directories
```

Two more directories appear at runtime and are not created by the installer:

```
  cache/       Scraper enrichment cache (cache/enrichment/, content-hashed)
  data/research/  Research raw corpus JSON (created by king-research export)
```

The sections below describe each directory in turn.

### `bin/` (wrapper shims)

`writeWrappers()` (`installer/lib/scaffold.js`) writes three POSIX `sh` shims here, each mode `0755`:

| Shim | Runs |
| --- | --- |
| `kctx` | `core/venv/bin/python -m context_cli.cli` |
| `king-scrape` | `core/venv/bin/python -m king_context.scraper.cli` |
| `king-research` | `core/venv/bin/python -m king_context.research.cli` |

On Windows the same step also writes `.cmd` companions that point at `core/venv/Scripts/python.exe`. The shims are thin: they resolve their own directory and `exec` the venv Python with the matching module. The real executables live in the venv (see `core/`), not here.

### `core/` (virtual environment)

`createVenv()` runs `<python> -m venv .king-context/core/venv` (`installer/lib/python.js`), then `installPackage()` pip-installs `king-context[all]` into it. The console scripts (`kctx`, `king-scrape`, `king-research`, and the legacy `king-context-server`) land in `core/venv/bin/` on POSIX or `core/venv/Scripts/` on Windows. This is the only directory holding executable Python; the `bin/` shims forward into it.

### `docs/` (the CLI search surface)

`docs/` is the authoritative content store for `kctx`, holding product and API documentation. It is a flat-file store, not a database: each indexed corpus is its own subdirectory named after the corpus, for example `docs/exa/`.

A per-doc directory contains:

```
docs/<name>/
  index.json        Corpus metadata (name, display_name, version, base_url,
                    section_count, indexed_at)
  keywords.json     Reverse index: keyword -> [section path, ...]
  tags.json         Reverse index: tag -> [section path, ...]
  use_cases.json    Reverse index: use case -> [section path, ...]
  sections/         One JSON file per section
    <slug>.json     title, path, url, keywords, use_cases, tags,
                    priority, content
```

The reverse indexes (`keywords.json`, `tags.json`, `use_cases.json`) power fast metadata lookups before any full section read, supporting the progressive-disclosure workflow. `kctx` keys every store off `index.json`: a directory is treated as a valid doc only when `<name>/index.json` exists (`src/context_cli/cli.py`). For the JSON shape of each file, see [corpus-schema.md](corpus-schema.md).

Content reaches this store in two steps. The scraper exports raw corpus JSON to `data/<name>.json`, then `kctx index` builds the flat-file `docs/<name>/` tree from it. See [cli-retrieval.md](../architecture/cli-retrieval.md) and [scraper-pipeline.md](../architecture/scraper-pipeline.md).

### `research/` (parallel store)

`research/` is the second store `kctx` searches by default, holding open-web research corpora. It is structurally identical to `docs/`: one subdirectory per topic (for example `research/prompt-engineering-techniques/`) with the same `index.json` plus `keywords.json` / `tags.json` / `use_cases.json` reverse indexes and a `sections/` directory. The difference is provenance, carried in the raw export rather than the indexed store: research export JSON tags each section with `"source_type": "research"` (`src/king_context/research/export.py`), which `kctx index` reads via `_detect_source()` (`src/context_cli/cli.py`) to route the corpus into this store instead of `docs/`. See [research-pipeline.md](../architecture/research-pipeline.md).

### `adr/` and `decisions/` (the ADR pair)

Architecture decisions are stored as two coordinated views:

- `adr/` holds the human-readable Architecture Decision Records as markdown, one file per decision (for example `adr/0001-adopt-cli-first-architecture-for-agent-retrieval.md`).
- `decisions/` holds the derived, indexed store the CLI reads. In this project it is `decisions/project/`, a flat-file store shaped like `docs/` (`index.json`, `keywords.json`, `tags.json`, `use_cases.json`, and `sections/<id>.json`) plus two ADR-specific files: `graph.json` (decision nodes and their supersede/related links) and `timeline.json` (ordered decision history with `supersedes` / `superseded_by` / `related`).

`DECISIONS_STORE_DIR` is defined in `src/context_cli/__init__.py`. Do not hand-edit either side. Create and query ADRs through `kctx adr` and the `king-record-decision` / `king-decisions` skills. See [adr-workflow.md](../contributing/adr-workflow.md).

### `data/` (raw corpus JSON)

`data/` holds the raw exported corpus JSON that feeds `kctx index`. It is the scraper and research export target, not a search surface.

- The scraper writes `data/<name>.json` (`src/king_context/scraper/cli.py`).
- `king-research` writes its export under `data/research/<slug>.json` (`RESEARCH_DATA_DIR = PROJECT_ROOT / ".king-context" / "data" / "research"`, `src/king_context/research/export.py`).

These JSON files follow the corpus schema described in [corpus-schema.md](corpus-schema.md).

### `_temp/` (scraper work directories)

`TEMP_DOCS_DIR = PROJECT_ROOT / ".king-context" / "_temp"` (`src/king_context/scraper/discover.py`). Each scrape gets a work directory named after the base URL (for example `_temp/www-python-httpx-org/`). A work directory accumulates the intermediate pipeline artifacts: `discovered_urls.json`, `filtered_urls.json`, `pages/`, `chunks/`, `enriched/`, and a `manifest.json` that tracks step status so a run can resume with `king-scrape <url> --step <step>`. These are scratch files for a single scrape and are safe to delete between runs.

### `cache/enrichment/` (enrichment cache)

Created on first use, not by the installer. `DEFAULT_CACHE_DIR = PROJECT_ROOT / ".king-context" / "cache" / "enrichment"` (`src/king_context/scraper/enrich_cache.py`). Each entry is a JSON file named by a content-addressed key: a SHA-256 of the chunk content combined with the model id and the prompt version (`make_key()`). The file stores the LLM-generated enrichment (`keywords` / `use_cases` / `tags` / `priority`) for that chunk. Because the content is part of the key, re-scraping unchanged pages reuses cached enrichment instead of paying the LLM cost again. Because the model id and prompt version are also part of the key, swapping the model or editing the prompt invalidates prior entries.

### `_learned/` (agent shortcuts)

A space for agent self-learning shortcuts: short markdown notes an agent can write and read back (for example `_learned/minimax-tts.md`). The installer creates the directory; its contents are produced at runtime.

## Authoritative paths for the CLI stack

For day-to-day retrieval, these are the paths that matter:

| Purpose | Path |
| --- | --- |
| Documentation search store | `.king-context/docs/<name>/` |
| Research search store | `.king-context/research/<slug>/` |
| ADR index the CLI reads | `.king-context/decisions/project/` |
| ADR source markdown | `.king-context/adr/` |
| Raw corpus JSON (scraper export, `kctx index` input) | `.king-context/data/<name>.json` |
| Raw research JSON (`king-research` export) | `.king-context/data/research/<slug>.json` |
| Scraper work directories | `.king-context/_temp/<site>/` |
| Enrichment cache | `.king-context/cache/enrichment/` |

The generic retrieval commands (`kctx search`, `kctx read`, `kctx grep`, `kctx topics`, `kctx list`) operate on the `docs/` and `research/` flat-file stores only. The `decisions/` store is read through the separate `kctx adr` subcommands.

## Legacy repo-root store (MCP only)

Per [ADR-0001](../../.king-context/adr/0001-adopt-cli-first-architecture-for-agent-retrieval.md), King Context is CLI-first. The MCP server (`src/king_context/server.py` plus `src/king_context/db.py`) is the legacy, secondary stack, and it uses an entirely different, separate set of locations rooted at the repository root rather than under `.king-context/`:

| File | Defined in | Purpose |
| --- | --- | --- |
| `docs.db` | `DB_PATH = PROJECT_ROOT / "docs.db"` (`src/king_context/db.py`) | SQLite database with FTS5 full-text search |
| `data/*.json` | `DATA_DIR = PROJECT_ROOT / "data"` (`src/king_context/seed_data.py`) | Raw documentation JSON seeded into SQLite |
| `data/embeddings.npy` | `EMBEDDINGS_PATH` (`src/king_context/db.py`) | NumPy float32 embedding matrix |
| `data/_internal/section_mapping.json` | `SECTION_MAPPING_PATH` (`src/king_context/db.py`) | Maps section DB ids to embedding rows |

These belong only to the MCP stack. The two stacks do not share data: the CLI never reads `docs.db` or the embeddings, and the MCP server never reads the `.king-context/` flat-file stores. The repo-root `data/` directory (seeded into `docs.db`) is distinct from `.king-context/data/` (the scraper export target for the CLI). See [mcp-legacy.md](../architecture/mcp-legacy.md) for the full description of that stack.

## Related references

- [corpus-schema.md](corpus-schema.md): the JSON shape of corpus files and section records.
- [env-vars.md](env-vars.md): environment variables that configure scraping, enrichment, and research.
- [overview.md](../architecture/overview.md): how the pieces fit together.
- [cli-retrieval.md](../architecture/cli-retrieval.md): how the CLI searches the flat-file stores.
