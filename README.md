# King Context

A local-first, token-efficient documentation server for LLM context injection via the Model Context Protocol.

**Status:** Open Source | **License:** MIT

---

## Why This Exists

Cloud-based documentation tools like Context7 work well, but they come with inherent limitations:

- **Opacity** — No visibility into what documentation is actually indexed
- **Dependency** — Relying on third parties to update documentation
- **Cost** — Token-heavy responses that inflate API usage
- **Latency** — Network round-trips for every query

This project provides a transparent, community-maintainable alternative where you control the documentation, the indexing, and the token budget.

---

## Core Innovation: Cascade Search

The system implements a **4-layer prioritized search strategy** that stops at the first hit:

```
1. CACHE        (<1ms)   → Previously successful queries
2. METADATA     (<5ms)   → Structured fields: keywords, use_cases, tags
3. FTS5         (<10ms)  → Full-text search with BM25 ranking
4. HYBRID       (<15ms)  → Semantic reranking via embeddings (optional)
```

This architecture ensures that **90% of queries resolve at the metadata layer**, returning focused chunks instead of flooding context with redundant information.

---

## Benchmark Results

Comparative analysis against Context7 across multiple APIs (ElevenLabs, Gladia, OpenRouter):

| Metric | King Context | Context7 | Improvement |
|--------|--------------|----------|-------------|
| Avg tokens/query | 968 | 3,125 | **3.2x fewer** |
| Latency (metadata) | 1.15ms | 200-500ms | **170x faster** |
| Latency (FTS) | 97.83ms | 200-500ms | **2-5x faster** |
| Duplicate results | 0 | 11 | **Zero waste** |
| Relevance score | 3.2/5 | 2.8/5 | +14% |
| Implementability | 4.4/5 | 4.0/5 | +10% |

**Token reduction: 59-69% across all tested queries.**

Full benchmark methodology and raw data available in [BENCHMARK.md](BENCHMARK.md).

---

## Trade-offs

This tool is not universally better. It excels in specific conditions:

| Strength | Limitation |
|----------|------------|
| Millisecond latency (local) | Requires indexed documentation |
| Predictable token costs | Keyword-based queries work best |
| Zero duplications | Natural language queries less effective |
| Full transparency | Documentation quality determines results |
| Offline capability | No broad web search |

**Quality depends on documentation quality.** If your indexed docs comprehensively cover the API, this system will outperform cloud alternatives in accuracy, token efficiency, and latency. If documentation is sparse or poorly structured, results will reflect that.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     MCP Server (FastMCP)                    │
├─────────────────────────────────────────────────────────────┤
│  Tools:                                                     │
│  ├── search_docs(query, doc_name?, max_results?)           │
│  ├── list_docs()                                           │
│  ├── show_context(query, doc_name?)                        │
│  └── add_doc(doc_json)                                     │
├─────────────────────────────────────────────────────────────┤
│                    Cascade Search Engine                    │
│  ┌─────────┐  ┌──────────┐  ┌──────┐  ┌────────┐          │
│  │  Cache  │→ │ Metadata │→ │ FTS5 │→ │ Hybrid │          │
│  └─────────┘  └──────────┘  └──────┘  └────────┘          │
├─────────────────────────────────────────────────────────────┤
│  SQLite + FTS5         │  Embeddings (all-MiniLM-L6-v2)    │
└─────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/your-org/king-context.git
cd king-context

# Create virtual environment and install
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### CLI Usage (Recommended)

The `kctx` CLI is the recommended way for AI agents to access documentation. It operates on a file-based `.king-context/` data store — no SQLite required for reads.

```bash
# Index documentation from scraped data
kctx index data/elevenlabs-api.json    # index one doc
kctx index --all                        # index all data/*.json

# List available docs
kctx list

# Search by keywords/use cases (metadata only, no content — token efficient)
kctx search "streaming audio"
kctx search "auth" --doc elevenlabs-api --top 3

# Read a section (preview first, then full)
kctx read elevenlabs-api websocket-streaming --preview
kctx read elevenlabs-api websocket-streaming

# Browse by topic
kctx topics elevenlabs-api
kctx topics elevenlabs-api --tag api-reference

# Grep content for exact patterns
kctx grep "Client(" --doc httpx --context 3
```

All commands support `--json` for machine-parseable output.

A Claude Code skill (`.claude/skills/king-context/skill.md`) teaches agents the optimal search strategy: check learned shortcuts, list, search, preview, then read — finding the right section in ≤3 CLI calls.

### MCP Server (Legacy)

The MCP server is still available for tools that integrate via the Model Context Protocol.

Using the CLI:

```bash
claude mcp add king-context -- king-context
```

Or manually add to your MCP configuration:

```json
{
  "mcpServers": {
    "king-context": {
      "command": "king-context",
      "cwd": "/path/to/king-context"
    }
  }
}
```

```bash
# Seed the SQLite database (required for MCP)
python -m king_context.seed_data
```

---

## Documentation Schema

Each indexed documentation follows this structure:

```json
{
  "name": "api-name",
  "display_name": "API Display Name",
  "version": "v1",
  "base_url": "https://docs.example.com",
  "sections": [
    {
      "title": "Authentication",
      "path": "auth",
      "url": "https://docs.example.com/auth",
      "keywords": ["auth", "api-key", "bearer", "token"],
      "use_cases": ["how to authenticate", "setup api key"],
      "tags": ["security", "setup"],
      "priority": 10,
      "content": "# Authentication\n\n..."
    }
  ]
}
```

The `keywords`, `use_cases`, and `tags` fields enable the metadata search layer, which is the primary driver of token efficiency.

---

## Transparency

Every search response includes metadata about how results were found:

```json
{
  "transparency": {
    "method": "metadata",
    "latency_ms": 1.30,
    "search_path": ["cache_miss", "metadata_hit"],
    "from_cache": false
  }
}
```

No black boxes. You always know which layer returned your results and how long it took.

---

## Roadmap

### Scraper Pipeline

The `king-scrape` CLI automates documentation extraction end-to-end: discovers URLs on a site, filters for documentation pages, fetches and chunks the content, enriches each chunk with structured metadata via LLM, and exports a ready-to-use JSON file indexed into the database.

```bash
king-scrape https://docs.stripe.com
```

Requires `FIRECRAWL_API_KEY` and `OPENROUTER_API_KEY`. Full usage guide in [src/king_context/scraper/SCRAPER.md](src/king_context/scraper/SCRAPER.md).

### Planned
- **Community Documentation Registry** — Shared, versioned documentation packages maintained by the community
- **Methodology Documentation** — This project is one component of a broader methodology for LLM-assisted development (replacing SDD/BMAD approaches). Separate repository coming soon.

---

## Contributing

This project is intentionally open source because:

1. **Transparency** — You should know exactly what documentation is being injected into your LLM context
2. **Independence** — No dependency on third-party update cycles
3. **Community Quality** — Documentation improves faster when maintained collectively

Contributions needed:

- Documentation packages for popular APIs/frameworks
- Improvements to scraping and extraction skills
- Testing across different use cases
- Performance optimizations

---

## Project Structure

```
king-context/
├── src/king_context/       # MCP server package
│   ├── server.py           # MCP server (FastMCP)
│   ├── db.py               # Cascade search engine + SQLite
│   ├── seed_data.py        # Database seeding
│   └── scraper/            # Scraping pipeline (king-scrape CLI)
├── src/context_cli/        # CLI package (kctx)
│   ├── cli.py              # Entry point with subcommands
│   ├── store.py            # .king-context/ path resolution
│   ├── indexer.py           # JSON → file structure indexer
│   ├── searcher.py         # Metadata-based search engine
│   ├── reader.py           # Section reader with preview
│   ├── formatter.py        # Output formatting (plain/JSON)
│   └── grep.py             # Content-level regex search
├── .king-context/          # File-based data store (generated)
├── tests/                  # Test suite
├── data/                   # Documentation JSONs + embeddings
├── scripts/                # Utility scripts
├── pyproject.toml          # Project configuration
└── docs.db                 # SQLite database (generated)
```

---

## License

MIT License. Use it, fork it, improve it.

---

## Acknowledgments

Built as an alternative to proprietary documentation tools. Inspired by the need for transparent, efficient, and community-driven LLM tooling.
