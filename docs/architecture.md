# Architecture

King Context is a local-first retrieval layer for LLM agents. It indexes scraped documentation and researched topics into a structured store that supports progressive disclosure: metadata first, preview on demand, full read only when the agent needs it.

## The four pieces

### `king-scrape` — URL → corpus

Point it at a docs site. The pipeline runs:

1. **Discover** — find pages from sitemaps, navigation, and link graph.
2. **Filter** — drop irrelevant pages (heuristic + optional LLM filter).
3. **Fetch** — download HTML/markdown via Firecrawl.
4. **Chunk** — split content into sections that respect the source structure.
5. **Enrich** — annotate each chunk with `keywords`, `use_cases`, `tags`, `priority` via an LLM.
6. **Export** — write enriched JSON to `.king-context/data/<name>.json`.

### `king-research` — topic → corpus

Same enrichment shape, different intake. Give it a topic. It generates search queries, pulls sources from the open web via Exa, fetches and chunks them, and runs the same enrichment step. Effort flags (`--basic`, `--high`, `--extrahigh`) control how many queries and deepening iterations run.

Output goes to `.king-context/research/<slug>/`. The retrieval surface is identical to scraped docs.

### `kctx index` — JSON → flat store

Turns the enriched JSON into a flat file structure with reverse indexes:

- Docs go to `.king-context/docs/`
- Research goes to `.king-context/research/`
- Each section becomes a file plus entries in keyword and use-case indexes

### `kctx` — search and read

The retrieval interface. Scores sections by matching query terms against the keyword and use-case indexes. No full-text scan, no vector similarity on roughly 90% of lookups. A local query cache collapses repeat lookups to sub-millisecond reads.

Agents can write `.king-context/_learned/<corpus>.md` shortcuts as they work — mapping common questions to exact section paths. The retrieval layer gets faster per corpus over time, with no manual wiring.

## Cascade search (MCP server)

The MCP server (`king-context`) uses a four-layer cascade in `db.py`. It stops at the first hit:

1. **Cache** (`<1ms`) — exact query previously executed.
2. **Metadata** (`<5ms`) — match on keywords, use_cases, tags.
3. **FTS5** (`<10ms`) — full-text search via SQLite FTS5 with BM25 ranking.
4. **Hybrid rerank** (`<15ms`) — cosine similarity over `all-MiniLM-L6-v2` embeddings, threshold `0.3`.

Every search response includes a `transparency` object with `method`, `latency_ms`, `search_path`, and `from_cache` fields, so agents can see exactly which layer answered.

## Section schema

Every enriched section has the same shape, regardless of source:

```json
{
  "title": "Section title",
  "path": "section-path",
  "url": "https://docs.example.com/section",
  "keywords": ["keyword1", "keyword2"],
  "use_cases": ["how to do X", "when to use Y"],
  "tags": ["category1", "category2"],
  "priority": 10,
  "content": "Markdown content..."
}
```

Metadata is what makes progressive disclosure work without losing recall. The agent finds the right section through structured fields instead of scanning raw content.

## Storage layout

```
.king-context/
├── docs/                # Scraped documentation (indexed)
├── research/            # Researched topics (indexed)
├── data/                # Raw enriched JSON exports
├── _temp/               # Scraper work directories
├── _learned/            # Agent-authored shortcut cache
├── core/venv/           # Python virtual environment
└── bin/                 # CLI wrappers (kctx, king-scrape, king-research)
```

The MCP server keeps a SQLite database (`docs.db`) at the project root with tables `documentations`, `sections`, `sections_fts`, `query_cache`. See [`CLAUDE.md`](../CLAUDE.md) for the schema and module map.

## Why progressive disclosure

A single API page costs 15k tokens of raw markdown, and most of it is noise. Forcing an agent to read ten 400-line `.md` files is the same problem dressed differently. King Context keeps the corpus arbitrarily large because the agent never loads it whole. Metadata search filters to the right section, preview returns ~400 tokens, full read returns the rest only if needed. The bigger the corpus, the more the retrieval discipline pays off.
