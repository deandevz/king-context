# Benchmark Methodology

King Context is a CLI-first, local-first retrieval layer for AI agents. We have
run two rounds against Context7, the most widely used documentation tool for code
agents today. This document is the full methodology behind both rounds: how we
generated queries, how we scored answers, and how to reproduce the comparison on
a different corpus.

For the headline numbers and per-round discussion, see
[`docs/benchmarks.md`](docs/benchmarks.md). This file explains the procedure that
produced those numbers.

## Two rounds, two questions

The two rounds answer different questions because the project changed underneath
them.

- **Round 1 (historical)** compared two MCP servers. King Context exposed its
  legacy MCP stack (`server.py` plus the SQLite/FTS5/embeddings cascade in
  `db.py`) and Context7 ran as its cloud MCP server. The question was whether a
  local cascade returns less noise than a cloud round trip.
- **Round 2 (current)** compares two agent skills. Both tools run as a CLI plus a
  Claude Code skill, driven by the same agent. King Context uses the `kctx`
  retrieval surface over the flat-file store under `.king-context/`. The question
  is no longer "who drives retrieval" (both sides drive it now) but what shape of
  retrieval the agent can reach for.

Per [ADR-0001](.king-context/adr/), the `kctx` flat-file store is the canonical
stack and the MCP server is the legacy stack. The two stacks do not share data.
Round 1 measured the legacy stack; Round 2 measures the canonical one. Read them
in that light.

---

## Round 2 (current): skill vs skill

Both tools run as a CLI plus a Claude Code skill, driven by the same agent. The
comparison ran on the Google Gemini API documentation using Claude Opus 4.7.

### Configuration

| System | Surface | Description |
|---|---|---|
| **King Context** | `kctx` CLI + skill | Flat-file retrieval store under `.king-context/`, queried through `kctx search`, `kctx grep`, `kctx read --preview`, `kctx read`. |
| **Context7** | CLI + skill | Cloud documentation service, queried through its own CLI and skill. |

Both surfaces were given to the same agent. The agent decided which calls to
make, in which order, and when to stop. Neither side was hand-fed the answer.

### Corpus

A single corpus: the Google Gemini API documentation. King Context indexed it
into the `docs` store via `king-scrape` followed by `kctx index`. Context7
queried its hosted copy of the same docs. Using one well-known, versioned API
keeps the question about retrieval shape, not corpus selection.

### Progressive disclosure under test

The King Context side exercised the recommended retrieval workflow described in
[`docs/architecture/cli-retrieval.md`](docs/architecture/cli-retrieval.md):
metadata search first, then `grep` for exact strings, then a preview, then a full
read only when the preview is relevant.

```bash
kctx search "media resolution" --top 5
kctx grep "media_resolution" --doc gemini
kctx read gemini media-resolution --preview
kctx read gemini media-resolution
```

These are the same primitives a real agent uses. The benchmark measured the
agent working through them, not a single fixed call.

### Metrics

Round 2 shifted the emphasis from raw token count to answer quality, because both
sides were now agent-driven and the token gap had narrowed.

| Metric | Description |
|---|---|
| **Average tokens per query** | Mean tokens pulled into context to answer one query. |
| **Median tokens per query** | Median of the same, less sensitive to one large call. |
| **Correct facts** | Count of factually correct claims out of the total checked. |
| **Hallucinations per query** | Mean number of unsupported claims introduced per query. |
| **Composite quality** | Combined 0 to 5 score across correctness, relevance, and completeness. |
| **First-shot code** | Whether code written from the answer compiled on the first attempt. |

### Results

Numbers are reproduced from [`docs/benchmarks.md`](docs/benchmarks.md). Do not
treat figures elsewhere as authoritative if they disagree with that file.

| Metric | Context7 (skill) | King Context (skill) | Winner |
|---|---|---|---|
| Average tokens per query | ~1,896 | ~1,064 | King Context |
| Median tokens per query | 1,750 | 901 | King Context |
| Correct facts | 32 / 38 (84%) | 38 / 38 (100%) | King Context |
| Hallucinations per query | 0.33 | 0.0 | King Context |
| Composite quality (0 to 5) | 3.46 | 4.79 | King Context |
| First-shot code (Q4) | compiles | compiles | tie |

### What the numbers mean

The token gap shrank compared to Round 1, but the story moved from quantity to
quality. With both sides agent-driven, the difference is in what the agent can
ask for. Three behaviors separated the tools (full narrative in
[`docs/benchmarks.md`](docs/benchmarks.md)):

- **Self-correct.** When the first search missed a page, the agent ran `grep`,
  found the line, previewed the section, and stopped. Staged primitives give it
  checkpoints to backtrack without burning budget.
- **Refuse to hallucinate.** When a fact was not in the indexed docs, King
  Context answered that it was missing. Retrieval staged and filtered by metadata
  lets the agent tell when something is absent, rather than smuggling a
  proximity-matched chunk into context.
- **Handle ambiguity.** When a parameter had two generations in the docs,
  structured metadata surfaced both, while semantic similarity locked onto
  whichever had more mass in the corpus.

### Limitations we own

- One run per query in Round 2, not two. Variance is unknown.
- Context7 token counts are per-character estimates, not tiktoken counts. Roughly
  20% margin of error.

---

## Round 1 (historical): MCP server vs MCP server

This round predates the CLI-first architecture. It compared two MCP servers on
the same corpus with the same agent. King Context exposed its legacy MCP stack,
calling `search_docs()` directly; Context7 ran as its cloud MCP server. Keep this
section for context, not as a description of how King Context works today.

### Configuration

| System | Type | Description |
|---|---|---|
| **King Context (legacy MCP)** | Local | MCP server with the four-layer cascade in `db.py`: Cache, Metadata, FTS5, Hybrid rerank. |
| **Context7** | Cloud | External documentation service with a remote API. |

For the cascade layers, see
[`docs/architecture/mcp-legacy.md`](docs/architecture/mcp-legacy.md).

### Metrics

| Metric | Description | Range |
|---|---|---|
| **Relevance** | Does the doc answer the question? | 1-5 |
| **Implementability** | Can you implement from it? | 1-5 |
| **Noise** | Repeated or irrelevant info | 1-5 (1 is clean) |
| **Completeness** | Is anything critical missing? | 1-5 |
| **Tokens** | char_count / 4 | int |

#### Implementability rubric

| Score | Criteria |
|---|---|
| 5 | Code example plus parameters plus edge cases |
| 4 | Code example plus main parameters |
| 3 | Conceptual information, no code |
| 2 | Missing critical information |
| 1 | Cannot implement |

#### Relevance rubric

| Score | Criteria |
|---|---|
| 5 | Answers exactly the query, no noise |
| 4 | Answers the query with useful extra context |
| 3 | Partially answers, includes unrequested info |
| 2 | Tangentially related, too much noise |
| 1 | Irrelevant or mostly duplicated |

### Developer profiles

Queries simulated two profiles:

- **Junior developer.** Basic, direct questions. Focus on "how to start" and
  "simple example".
- **Senior developer.** Specific, advanced questions. Focus on edge cases,
  performance, and integration.

### Question categories

| Category | Junior query | Senior query |
|---|---|---|
| **Auth** | How to authenticate | Token refresh, security |
| **Core feature** | Basic usage | Streaming with timestamps |
| **Error handling** | What errors exist | Retry strategy, rate limits |
| **Integration** | How to use with Python | WebSocket, multiplexing |
| **Edge cases** | Supported formats | Timeout handling, partial responses |

Total: 5 categories x 2 profiles = 10 queries per benchmark.

### Procedure

1. **Question generation.** For each of the 10 combinations, prompt the model as
   the given profile to generate one realistic question about the category.
2. **Query execution.** Run each question against both systems. The King Context
   side called `search_docs(query=..., doc_name=..., max_results=5)` on the legacy
   MCP server; the Context7 side called its `query-docs` tool.
3. **Evaluation (LLM judge).** For each result pair, score relevance,
   implementability, noise, completeness, and token count, then pick a winner with
   reasoning.
4. **Consolidation.** Aggregate into an executive summary with averages, a
   breakdown by developer profile, and a breakdown by question category.

### Results

| Metric | King Context (legacy MCP) | Context7 | Improvement |
|---|---|---|---|
| Average tokens per query | 968 | 3,125 | 3.2x less |
| Latency (metadata hit) | 1.15ms | 200 to 500ms | 170x faster |
| Latency (full text search) | 97.83ms | 200 to 500ms | 2 to 5x faster |
| Duplicate results | 0 | 11 | zero waste |
| Relevance | 3.2 / 5 | 2.8 / 5 | +14% |
| Implementability | 4.4 / 5 | 4.0 / 5 | +10% |

### Latency reference (legacy cascade)

The legacy MCP cascade stops at the first hit. Approximate per-layer latency:

```
1. Cache hit     -> <1ms    (exact query previously executed)
2. Metadata hit  -> <5ms    (match on keywords / use_cases / tags)
3. FTS5 hit      -> <10ms   (full-text search with BM25)
4. Hybrid rerank -> <15ms   (semantic similarity reordering)
```

By contrast, a Context7 cloud round trip is typically 200 to 500ms.

---

## Token efficiency formula

Both rounds report a token ratio:

```
efficiency_ratio = context7_tokens / king_context_tokens
```

- `ratio > 1.5`: King Context significantly more efficient.
- `ratio 1.0 to 1.5`: King Context slightly more efficient.
- `ratio < 1.0`: Context7 more efficient.

---

## Reproducing the comparison

Round 2 is the current methodology. To re-run it on a different corpus:

1. **Index the corpus into King Context.** Scrape and export, then build the
   flat-file store.

   ```bash
   king-scrape https://docs.example.com --name example --yes
   kctx index .king-context/data/example.json
   ```

   The export and section schema are documented in
   [`docs/reference/corpus-schema.md`](docs/reference/corpus-schema.md).

2. **Make the same corpus available in Context7.** Use the matching Context7
   library ID.

3. **Give both surfaces to the same agent.** Run the King Context skill and the
   Context7 skill under one agent with the same prompt and the same model.

4. **Run identical queries.** Generate the question set per the developer profiles
   and categories above, or supply a fixed set. The agent works through its own
   retrieval calls on each side.

5. **Score with the same rubric.** Use the metrics and rubrics in this document.
   Count tokens consistently across both sides, and note the per-character
   estimate caveat for Context7.

### A note on raw-results files

There is no committed raw-results file in this repository at present. The earlier
methodology referenced `BENCHMARK_RESULTS_*.md` files; none exist in the tree
today. The reproducible numbers live in [`docs/benchmarks.md`](docs/benchmarks.md),
and the headline tables also appear in the [README](README.md). If raw per-query
results are committed later, link them from here.

---

## Related documentation

- [`docs/benchmarks.md`](docs/benchmarks.md): headline numbers and per-round
  analysis.
- [`docs/architecture/overview.md`](docs/architecture/overview.md): how the
  pieces fit together.
- [`docs/architecture/cli-retrieval.md`](docs/architecture/cli-retrieval.md): the
  `kctx` retrieval surface used in Round 2.
- [`docs/architecture/mcp-legacy.md`](docs/architecture/mcp-legacy.md): the legacy
  cascade used in Round 1.
- [`docs/architecture/scraper-pipeline.md`](docs/architecture/scraper-pipeline.md)
  and
  [`docs/architecture/research-pipeline.md`](docs/architecture/research-pipeline.md):
  how corpora are built.
- [`docs/reference/corpus-schema.md`](docs/reference/corpus-schema.md): the
  section schema that powers metadata search.
