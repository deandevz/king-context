# The legacy MCP stack

King Context is a CLI-first, local-first retrieval layer for AI agents. This document covers the MCP server (`server.py` plus `db.py`), which is the legacy/secondary stack per [ADR-0001](../../.king-context/adr/0001-adopt-cli-first-architecture-for-agent-retrieval.md). The accepted decision states that the `kctx` CLI is the canonical product interface, and that MCP "remains useful and may continue to exist as an integration layer, but it should not define the primary architecture." The canonical stack is the flat-file store under `.king-context/` driven by `kctx`. The MCP stack described here uses an entirely separate engine: a SQLite database (`docs.db`) with FTS5 full-text search and SentenceTransformer embeddings. The two stacks do not share data.

This page exists to preserve the design detail of the MCP path. It is not a recommendation to build on it. See [ADR-0005](../../.king-context/adr/0005-local-ui-server-reads-cli-flat-file-surface-not-mcp-sqlite-layer.md) and the [rules for new code](#rules-for-new-code) below.

## Where it lives

| File | Role |
| --- | --- |
| `src/king_context/server.py` | FastMCP server entry point. Exposes 4 MCP tools, loads the embedding model, delegates to `db.py`. |
| `src/king_context/db.py` | Search engine and SQLite/FTS5/embedding layer. Holds the 4-table schema, `search_cascade()`, and embedding persistence. |
| `src/king_context/seed_data.py` | Indexes repo-local `data/*.json` into `docs.db`. |
| `scripts/run-seed-data.sh` | Wipes and reseeds `docs.db`. |
| `docs.db` (repo root) | The SQLite store for this stack. |
| `data/*.json`, `data/embeddings.npy`, `data/_internal/section_mapping.json` (repo root) | Raw doc JSON plus persisted embeddings for this stack. |

The CLI stack reads none of these. Its store is flat JSON under `.king-context/docs/` and `.king-context/research/`, with reverse-index keyword scoring in `src/context_cli/searcher.py`. There is no SQLite, no FTS5, and no embeddings on the CLI path.

## The MCP server

`server.py` builds a FastMCP server named `king-context` and exposes 4 tools, all of which delegate to `db.py`:

| Tool | Purpose | Backing call |
| --- | --- | --- |
| `search_docs(query, doc_name=None, max_results=5)` | Cascade search with full transparency. | `db.search_cascade()` |
| `list_docs()` | List all indexed docs with name, version, and section count. | `db.list_documentations()` |
| `show_context(query, doc_name=None)` | Show exactly what would be injected into context, with a rough token estimate (`len(context_preview) // 4`). | `db.search_cascade()` |
| `add_doc(doc_json)` | Validate required fields and insert a doc directly via MCP. | `db.insert_documentation()` |

`main()` is the entry point. It runs `init_db()`, then `_load_embeddings()`, then `mcp.run()`:

```bash
king-context-server            # via console script
python -m king_context.server  # via module
```

`_load_embeddings()` loads the `all-MiniLM-L6-v2` SentenceTransformer model into `db` module state, then tries to load `data/embeddings.npy` and `data/_internal/section_mapping.json`. Both loads are wrapped in `try/except` for graceful fallback: if the files are missing or corrupt, the embeddings and mapping stay empty and the cascade degrades to FTS-only (see below).

## The cascade search (`search_cascade`)

`db.search_cascade()` runs a 4-layer cascade and returns on the first hit. The query is normalized first (`_normalize_query` lowercases and strips). Each connection is opened by `_get_connection()`, which runs `PRAGMA foreign_keys = ON` per connection so that `ON DELETE CASCADE` is not a silent no-op.

| Layer | Function | Behavior |
| --- | --- | --- |
| 1. Cache | `_check_cache` | Looks up the normalized query in `query_cache`, joins to `sections`. On hit, increments `hit_count` and updates `last_used`. |
| 2. Metadata | `_search_metadata` | `LIKE` match against the `keywords`, `use_cases`, and `tags` JSON columns, ordered by `priority DESC`. |
| 3. FTS5 | `_search_fts` | BM25 full-text search over `sections_fts`. Requests ~20 candidates (not `max_results`) to feed the reranker. |
| 4. Hybrid rerank | `_rerank_with_embeddings` | Cosine similarity over `all-MiniLM-L6-v2` embeddings, threshold `0.3`, sorted descending. |

The flow:

1. Cache hit returns immediately with `method = "cache"` and `from_cache = True`.
2. On cache miss, metadata search runs. A hit caches its first result and returns with `method = "metadata"`.
3. On metadata miss, FTS5 runs. If it returns candidates, the reranker is attempted.
4. If the reranker returns results, `method = "hybrid_rerank"`. If embeddings are unavailable (`_embedding_model` or `_embeddings` is `None`) or every candidate is filtered out, the code falls back to the FTS5 results truncated to `max_results` with `method = "fts"`.

The reranker is the graceful-skip point: it returns `None` when embeddings are not loaded, which signals the fallback to FTS-only. Sections missing from `_section_id_to_idx` are skipped during reranking. The similarity threshold is `0.3` in both the docstring and the code (`if similarity >= 0.3`).

### The transparency object

Every `search_cascade()` response carries a `transparency` object so callers can see which layer answered:

```json
{
  "found": true,
  "chunks": [ ... ],
  "transparency": {
    "method": "metadata",
    "latency_ms": 1.4,
    "search_path": ["cache_miss", "metadata_hit"],
    "from_cache": false
  }
}
```

- `method`: which layer produced the result (`cache`, `metadata`, `hybrid_rerank`, or `fts`).
- `latency_ms`: wall time measured with `time.perf_counter()`.
- `search_path`: the ordered list of layer outcomes (for example `cache_miss`, `metadata_miss`, `fts_hit`).
- `from_cache`: whether the answer came from `query_cache`.

## The SQLite schema

`init_db()` creates 4 tables in `docs.db`:

| Table | Notes |
| --- | --- |
| `documentations` | Doc metadata. `name` is `UNIQUE`. |
| `sections` | Section content. `keywords`, `use_cases`, and `tags` are JSON columns, `priority` is an integer, `doc_id` references `documentations` with `ON DELETE CASCADE`. |
| `sections_fts` | FTS5 virtual table with external content (`content='sections'`, `content_rowid='id'`) over `title` and `content`. |
| `query_cache` | Maps a normalized query plus optional `doc_name` to a `section_id`. `UNIQUE(query_normalized, doc_name)`. |

Because `sections_fts` is an external-content FTS5 table, it does not auto-prune on `DELETE` or cascade. `insert_documentation()` maintains it by hand: before dropping a doc's existing sections, it issues the FTS5 `'delete'` protocol per row with the exact `title` and `content` that were originally indexed (NULL content was indexed as the empty string, so the delete must match byte for byte or term frequencies drift). It then deletes and reinserts the sections, reinserting each into `sections_fts`.

`insert_documentation()` is an upsert: the `documentations` row uses `INSERT ... ON CONFLICT(name) DO UPDATE`, preserving `created_at` while refreshing `display_name`, `version`, `base_url`, and `updated_at`.

## Embeddings

- Model: `all-MiniLM-L6-v2` (SentenceTransformer), loaded lazily in `server.py` into `db` module state.
- `data/embeddings.npy`: a numpy `float32` array, one row per section.
- `data/_internal/section_mapping.json`: maps section database IDs to embedding array indices (keys are serialized as strings, converted back to ints on load).

`_generate_and_save_embedding()` encodes a section's content, appends it to the in-memory `_embeddings` array, updates `_section_id_to_idx`, and persists both files. It is a no-op if `_embedding_model` is `None` (graceful skip).

Embeddings are written to disk only after the SQLite commit. `insert_documentation()` stages pending embeddings during the transaction and flushes them once the commit succeeds, so a rolled-back transaction never leaves orphaned numpy rows that disagree with the committed database. A failure during the embedding flush leaves the corpus with sections but no embedding rows, which the reranker handles via the FTS-only fallback.

## Seeding

`seed_data.py` indexes repo-local `data/*.json` into `docs.db`:

```bash
python -m king_context.seed_data   # init_db() + seed_all()
```

- `seed_all()` reads every `data/*.json` and calls `insert_documentation()` for each.
- `seed_one(path)` indexes a single file.

`scripts/run-seed-data.sh` resets the store by removing `docs.db` and rerunning the module:

```bash
./scripts/run-seed-data.sh
```

The scraper's `export.save_and_index()` still calls `seed_data.seed_one()` when `auto_seed=True` (the default in `src/king_context/scraper/export.py`), which writes into `docs.db`. This auto-seed path is the last live producer for the legacy store. The scraper-workflow skill steers agents away from it: it indexes into the CLI store with `kctx index` and instructs "NEVER use `seed_data` or `python -m king_context.seed_data`; that seeds the old MCP database." The `--no-auto-seed` flag suppresses the legacy write.

## Rules for new code

- New code must not couple to this stack. Per [ADR-0005](../../.king-context/adr/0005-local-ui-server-reads-cli-flat-file-surface-not-mcp-sqlite-layer.md), the local UI server reads exclusively from the CLI flat-file surface and must not import `king_context.db`, open `docs.db`, or load any embedding model. The reasons stated there apply broadly: importing `db.py` contradicts CLI-first, loads a ~500MB model at startup, depends on `docs.db` being populated separately, and fragments the retrieval contract (two surfaces can return different results for the same query).
- Do not use `seed_data` for the CLI store. The CLI store is built with `kctx index`; `seed_data` only writes the legacy SQLite database.
- Expose new retrieval capabilities through the CLI first, per ADR-0001. MCP support, if added, comes after the CLI primitive exists.

## See also

- [Architecture overview](overview.md)
- [CLI retrieval stack](cli-retrieval.md)
- [Local UI server](local-ui.md)
- [Storage layout](../reference/storage-layout.md)
- [Corpus schema](../reference/corpus-schema.md)
- [ADR workflow](../contributing/adr-workflow.md)
