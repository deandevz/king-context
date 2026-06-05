# Research pipeline internals

King Context is a CLI-first, local-first retrieval layer for AI agents. Where
the [scraper pipeline](scraper-pipeline.md) turns a documentation site into a
corpus, the research pipeline (`king-research`, entry point
`king_context.research.cli:main`) turns an open-ended topic into the same
shape of corpus by searching the open web, then exports it into the `kctx`
flat-file store under `.king-context/`.

The two pipelines deliberately share code. Only the search stage is
research-specific. Chunking, enrichment, cost estimation, and the base export
all reuse the scraper's implementations, so a research corpus has the exact
same section schema as a scraped one and is retrieved the same way through
`kctx search` and `kctx read`.

This document covers the pipeline internals. For the command-line surface and
flags, see the [CLI guide](../CLI_GUIDE.md). For where files land on disk, see
[storage layout](../reference/storage-layout.md). For the LLM provider layer
shared with the scraper, see [providers](providers.md).

## The five stages

`run_pipeline()` in `src/king_context/research/pipeline.py` walks a fixed list
of steps:

```python
RESEARCH_STEPS = ["generate", "search", "chunk", "enrich", "export"]
```

| Stage | Module | What it does |
| --- | --- | --- |
| `generate` | `pipeline.py` | Prepare the per-topic work directory and write the first manifest entry. No LLM call. |
| `search` | `research/deepen.py` | Run the deepening loop: LLM query generation, Exa search, Jina fallback. Produces `SourceDoc` objects. |
| `chunk` | reuses `scraper/chunk.py` | Split each source's markdown into sections via `chunk_page`. |
| `enrich` | reuses `scraper/enrich.py` | Annotate each chunk with `keywords`, `use_cases`, `tags`, `priority` via `enrich_chunks`, after a cost preview from `estimate_cost`. |
| `export` | `research/export.py` | Build the corpus JSON, write it to `.king-context/data/research/<slug>.json`, and auto-index it into the CLI store. |

Each stage writes a checkpoint manifest entry via the scraper's
`_update_step`. The manifest keys are remapped so the on-disk status names
match the scraper's vocabulary:

```python
MANIFEST_KEYS = {
    "generate": "generate",
    "search": "search",
    "chunk": "chunking",
    "enrich": "enrichment",
    "export": "export",
}
```

The work directory lives at `.king-context/_temp/research/<slug>/`, where
`<slug>` is `--name` if given, otherwise derived from the topic by
`export._slugify` (lowercased, non-alphanumeric runs collapsed to hyphens,
truncated to 40 characters). The deepening loop writes per-iteration source
snapshots into it, and the chunk stage writes `pages/` and `chunks/`
artifacts alongside the manifest.

Stages fail loudly when their input is empty. A search that finds no sources,
a chunk stage that produces no sections, an enrichment that returns nothing,
or an export with no enriched sections each raise `RuntimeError` rather than
writing an empty corpus over a good one.

## EXA_API_KEY is required

`load_research_config()` in `src/king_context/research/config.py` raises
`ConfigError` if `EXA_API_KEY` is not set, and `run_pipeline` re-validates it
through `_validate_config` before doing any work. `cli.main()` catches
`ConfigError` and routes it through `argparse`'s `parser.error`, so a missing
key fails fast with a usage-style message. `JINA_API_KEY` is optional: Jina
Reader is used as a fallback fetcher and its requests work without a key (the
`Authorization` header is only attached when a key is present).

Note on exit codes: the dedicated exit codes `2` (`ValueError`) and `3`
(`ProviderUnavailableError`) belong to the scraper CLI
(`src/king_context/scraper/cli.py`). The research and `kctx` CLIs do not use
that scheme.

## Stage 1: generate

The `generate` stage is bookkeeping. It creates
`.king-context/_temp/research/<slug>/`, writes a `done` manifest entry
recording the topic and slug, and logs that the work directory is prepared. No
network or LLM call happens here. The real query generation runs inside the
search stage on demand.

## Stage 2: search and the deepening loop

`run_deepening_loop()` in `src/king_context/research/deepen.py` is the heart of
the research-specific work. It runs one round of initial queries followed by
zero or more deepening iterations, accumulating `SourceDoc` results and
deduplicating by URL at the end.

The structure:

1. Resolve an `EffortProfile` from the effort level (see below).
2. Generate `initial_queries` queries for the topic with no prior context.
3. Fetch all initial queries concurrently (iteration `0`), snapshot them.
4. For each deepening iteration `1..iterations`: build condensed summaries of
   everything found so far, ask the LLM for `followups_per_iteration` deeper
   queries that avoid the queries already issued, fetch them concurrently,
   snapshot them.
5. Return `_dedup_by_url(all_docs)`.

A single shared `httpx.AsyncClient` is opened for the whole loop and reused for
all Jina fallback fetches. Each iteration's results are written to
`iteration_<n>.json` in the work directory. Per-iteration fetches run through
`_fetch_batch`, which gathers `fetch_for_query` calls with
`return_exceptions=True` and logs and skips any query that raised, so one
failing query never aborts the iteration.

The loop stops early in two cases: if the initial query generation fails or
returns nothing, the loop returns an empty list (and the pipeline then raises);
if a deepening iteration's query generation fails or returns no new queries,
the loop breaks and returns whatever it has gathered so far.

### Effort levels

The effort flags map to an `EffortProfile` of three numbers via
`effort_profile()` in `config.py`. Each profile controls the initial query
count, the number of deepening iterations, and the follow-up query count per
iteration:

| Flag | Initial queries | Deepening iterations | Follow-ups per iteration |
| --- | --- | --- | --- |
| `--basic` | 3 | 0 | 0 |
| `--medium` (default) | 5 | 1 | 3 |
| `--high` | 8 | 2 | 5 |
| `--extrahigh` | 12 | 3 | 8 |

`--basic` runs a single round of queries with no deepening. The other levels
add iterations that feed prior findings back into the next round of query
generation. The default when no flag is passed is `--medium`
(`_resolve_effort` in `cli.py`).

Every number above is a default that can be overridden by environment
variables read in `load_research_config`:
`RESEARCH_BASIC_QUERIES`, `RESEARCH_MEDIUM_QUERIES`,
`RESEARCH_MEDIUM_ITERATIONS`, `RESEARCH_MEDIUM_FOLLOWUPS`,
`RESEARCH_HIGH_QUERIES`, `RESEARCH_HIGH_ITERATIONS`,
`RESEARCH_HIGH_FOLLOWUPS`, `RESEARCH_EXTRAHIGH_QUERIES`,
`RESEARCH_EXTRAHIGH_ITERATIONS`, `RESEARCH_EXTRAHIGH_FOLLOWUPS`. See
[env vars](../reference/env-vars.md) for the full list.

### Query generation (queries.py)

`generate_queries()` in `src/king_context/research/queries.py` asks the LLM for
search queries. It uses the shared LLM provider layer through `get_client`,
selecting the `research` stage so the provider and model resolve from the
`RESEARCH_*` environment chain (see [providers](providers.md)). The
model override comes from `config.research_model` (set by `RESEARCH_MODEL`,
with `OPENROUTER_MODEL_RESEARCH` as an alternate name), and the OpenRouter key
is threaded through from the scraper config.

The system prompt forces a strict JSON object with a single `queries` array.
The user prompt varies by call:

- Initial call: just the topic and the requested count.
- Follow-up call: also lists the queries already issued (with an instruction to
  avoid any substring or close rewording) and a condensed view of what was
  already found, asking the model to dig deeper into promising themes rather
  than re-retrieve the same pages.

Responses are tolerant: `_extract_queries` strips a Markdown code fence if
present, accepts either a bare JSON array or a `{"queries": [...]}` object, and
keeps only non-empty string items. `_dedup` then normalizes each query
(lowercase, collapsed whitespace, trailing punctuation stripped), drops
anything matching a previously issued query, and truncates the result to the
requested `count`.

Reliability is built in. The call retries up to `_MAX_ATTEMPTS` (3) with
backoff delays `[1.0, 2.0]`, but only on transient `ProviderError`s: a
non-transient provider error or a JSON parse failure (`QueryGenerationError`)
is raised immediately. After exhausting retries it raises
`QueryGenerationError`, which the deepening loop catches and treats as a clean
stop.

### Exa search (exa.py)

`search()` in `src/king_context/research/exa.py` runs exactly one
`Exa.search_and_contents` call per query. Because the `exa_py` client is
synchronous, the call is dispatched to a thread via
`loop.run_in_executor`. The request uses `type="auto"`,
`num_results=config.exa_results_per_query` (default `10`, `EXA_RESULTS_PER_QUERY`),
full-verbosity text capped at `config.exa_max_chars` (default `15000`,
`EXA_MAX_CHARS`) with navigation, footer, and sidebar sections excluded,
highlights, and `livecrawl="always"`. Each result is parsed defensively into an
`ExaResult` dataclass (url, title, text, highlights, author, published_date,
score).

Exa errors are classified by HTTP status into a four-way taxonomy, then handled
by behavior:

| Error class | Trigger status | Behavior |
| --- | --- | --- |
| `ExaTransientError` | 429, 5xx, network errors, unknown/unclassified | Retry up to 3 attempts with backoff `[1.0, 2.0]`, then raise. |
| `ExaPermanentError` | 422 (per-query problem) | Log and return an empty list for that query; the run continues. |
| `ExaBudgetError` | 402 (credits exhausted) | Raise immediately. Fatal to the whole run. |
| `ExaConfigError` | 400 or 401 (bad request or invalid key) | Raise immediately. Fatal to the whole run. |

`_extract_status` reads the status from a `status_code` or `status` attribute
on the exception, falling back to a regex over the string form, and treats a
missing status as transient.

### Jina fallback fetch (jina.py)

Exa returns text directly, but some results come back thin. The `fetch` stage
falls those short results back to the Jina Reader (`https://r.jina.ai/`),
implemented in `src/king_context/research/jina.py`.

`fetch()` makes up to three attempts, escalating the rendering engine and
timeout each time:

| Attempt | Engine | Jina timeout (s) |
| --- | --- | --- |
| 1 | `direct` | 30 |
| 2 | `browser` | 30 |
| 3 | `browser` | 60 |

The HTTP client timeout is the Jina timeout plus 5 seconds. Each request asks
for Markdown output with `network-idle` timing, links and images dropped, and a
fixed set of chrome selectors (`nav, footer, aside, .ad, .cookie-banner,
.sidebar`) removed. The `Authorization: Bearer` header is only attached when a
`JINA_API_KEY` is present.

Jina responses are classified into three error types:

| Error class | Trigger | Behavior |
| --- | --- | --- |
| `JinaPermanentError` | 400, 401, 403, 404, 422 | Raise immediately, skip this URL. |
| `JinaTransientError` | 429, 5xx, unexpected status, client timeout, connect error | Retry with the escalated engine, delays `[2.0, 5.0]`. |
| `JinaDegradedError` | 200 OK but content below `WORD_COUNT_THRESHOLD` (50 words) | Retry with the escalated engine. |

The escalation is the point of the degraded path: a `direct` fetch that returns
too little content gets a second and third shot with the heavier `browser`
engine before the URL is given up on.

### SourceDoc stitching (fetch.py)

`fetch_for_query()` in `src/king_context/research/fetch.py` is what binds Exa
and Jina together for a single query. It runs one Exa search, then routes each
result by content length:

- Results with `len(result.text) >= MIN_CONTENT_CHARS` (600) are kept directly
  and wrapped into a `SourceDoc` with `fetch_path="exa"`.
- Shorter results are queued for a Jina fallback fetch.

Fallback fetches run concurrently under an `asyncio.Semaphore` sized to
`config.scraper.concurrency`, sharing the single `httpx.AsyncClient` opened by
the deepening loop. A successful Jina fetch produces a `SourceDoc` with
`fetch_path="jina"`, carrying the Jina content and title but reusing the Exa
result's author, published date, and score. A Jina failure (any of the three
Jina errors, or an unexpected exception) is logged and dropped: the original
short Exa result is not kept. The function returns the direct Exa docs plus the
successful Jina fallbacks.

The `SourceDoc` dataclass is the unit that flows out of the search stage:

```python
@dataclass
class SourceDoc:
    url: str
    title: str
    content: str
    author: str | None
    published_date: str | None
    domain: str
    query: str
    discovery_iteration: int
    score: float | None
    fetch_path: Literal["exa", "jina"]
```

`discovery_iteration` records which deepening pass surfaced the source, and
`fetch_path` records whether the content came straight from Exa or via the Jina
fallback. Both fields survive into the exported corpus.

## Stages 3 and 4: deliberate reuse of the scraper

The chunk and enrich stages do not reimplement anything. The pipeline imports
directly from the scraper:

```python
from king_context.scraper.chunk import Chunk, chunk_page
from king_context.scraper.enrich import EnrichedChunk, enrich_chunks, estimate_cost
```

**Chunk.** For each `SourceDoc`, the pipeline writes a `<slug>.md` page file
and a JSON sidecar (url, title, author, published_date, domain,
discovery_iteration, query, fetch_path) into the work directory's `pages/`
folder, then calls `chunk_page(source.content, source.url, config.scraper)` and
writes the resulting chunks to `chunks/<slug>.json`. Chunking respects the
scraper's structure-aware splitting (h2/h3 boundaries, subdivide, merge) and
the same content-hash provenance, because it is literally the same code path.

**Enrich.** The pipeline first calls `estimate_cost(chunks, config.scraper)`
and prints a preview through `_print_enrichment_cost`. For an OpenRouter
provider it prints a dollar estimate; for a local provider (Ollama) it prints a
chunk count with no dollar figure, plus a warning if OpenRouter fallback is
enabled. The dollar estimate is a fixed heuristic (the scraper's
`estimate_cost` hardcodes a per-token price), not a live quote from the
selected model. Unless `--yes` is passed, the pipeline prompts `Proceed?
[y/N]` and aborts the run if the answer is not `y`. It then calls
`enrich_chunks(chunks, config.scraper, output_dir=work_dir)`, which applies the
scraper's per-chunk LLM annotation, content-addressed enrichment cache, and
per-item failure isolation.

Because the research and scraper stages share these functions, the LLM
provider configuration is also shared: the `research` stage for query
generation and the `enrich`/`filter` stages all resolve through the same
`llm_providers` layer described in [providers](providers.md). The default model
across stages is `google/gemini-3-flash-preview`.

## Stage 5: export and auto-index

`export_research_to_json()` in `src/king_context/research/export.py` builds the
corpus on top of the scraper's `export_to_json`, then layers research-specific
fields on each section:

- `source_type` is always set to `"research"`.
- When a matching `SourceDoc` exists for the section URL: `authors` (parsed
  from a comma-separated author string), `published_date`, `domain`, and
  `discovery_iteration` are attached.

The corpus is written to
`.king-context/data/research/<slug>.json` (`RESEARCH_DATA_DIR`, resolved from
`PROJECT_ROOT`). If a file already exists at that path it is overwritten, and
the overwrite is logged and printed.

After export, unless `--no-auto-index` is set, the pipeline calls
`auto_index(output_path)`, which imports `context_cli`'s `index_doc` and
indexes the JSON into `RESEARCH_STORE_DIR` (`.king-context/research/`). This is
the seam where the research pipeline hands off to the canonical
[CLI retrieval](cli-retrieval.md) store. `auto_index` is defensive by design:
it logs and swallows any exception and never raises, so an indexing problem
cannot lose the exported JSON. After auto-index the corpus is searchable with
`kctx search --source research` and readable with `kctx read ... --source
research`.

The `source_type: "research"` marker also lets `kctx index` route a manually
re-indexed export to the research store automatically. See the
[corpus schema](../reference/corpus-schema.md) for the full section shape.

## Current limitations (P1)

The CLI advertises four workflow flags that are not yet fully wired. These are
honest gaps in the current implementation, not bugs to work around:

- **`--step` does not rehydrate state.** It is parsed and accepted, but
  `run_pipeline` only skips the earlier steps in `RESEARCH_STEPS`. It does not
  reload sources, chunks, or enriched data from the work directory. Resuming at
  `chunk` with no in-memory `sources` therefore hits the empty-input guard and
  raises a `RuntimeError`. The CLI help text and a runtime warning both flag
  this. `--stop-after` works as expected: it runs up to and including the named
  step and then returns.
- **`--no-filter` is a no-op.** There is no relevance filter stage in the
  research pipeline. `ResearchConfig.relevance_threshold` exists as a field
  (default `0.5`) but nothing consumes it. The flag is accepted and logged for
  forward compatibility.
- **`--force` is a no-op.** It is documented as a P3 placeholder for skipping
  URL dedup. The deepening loop always dedups by URL today.

For everything else (effort levels, EXA/Jina configuration, provider and model
selection) see the [CLI guide](../CLI_GUIDE.md), [env vars](../reference/env-vars.md),
and [providers](providers.md).

## Related docs

- [Architecture overview](overview.md)
- [Scraper pipeline](scraper-pipeline.md)
- [CLI retrieval](cli-retrieval.md)
- [Providers](providers.md)
- [Corpus schema](../reference/corpus-schema.md)
- [Environment variables](../reference/env-vars.md)
- [Storage layout](../reference/storage-layout.md)
