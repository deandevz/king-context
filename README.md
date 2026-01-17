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

# Install dependencies
pip install -e .
```

### Configure Claude Code

Using the CLI:

```bash
claude mcp add king-context -- python server.py
```

Or manually add to your MCP configuration:

```json
{
  "mcpServers": {
    "king-context": {
      "command": "python",
      "args": ["server.py"],
      "cwd": "/path/to/king-context"
    }
  }
}
```

### Seed Documentation

```bash
# Place documentation JSON in data/
python seed_data.py
```

### Usage

```python
# Search documentation
search_docs("authentication", doc_name="openrouter")

# List available docs
list_docs()

# Preview context injection (with token estimate)
show_context("websocket streaming", doc_name="elevenlabs")
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

### In Progress

- **Scraping Skills** — Claude Code skills for semi-automated documentation extraction. Currently functional but not production-ready. Contributions welcome.

### Planned

- **Automated Scraping Pipeline** — A system to crawl, extract, and index documentation with minimal manual intervention
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
├── server.py           # MCP server implementation
├── db.py               # Cascade search engine + SQLite
├── seed_data.py        # Database seeding
├── data/               # Documentation JSONs + embeddings
│   ├── *.json          # Indexed documentations
│   ├── embeddings.npy  # Section embeddings
│   └── _internal/      # Mapping files
├── docs.db             # SQLite database
└── tests/              # Test suite
```

---

## License

MIT License. Use it, fork it, improve it.

---

## Acknowledgments

Built as an alternative to proprietary documentation tools. Inspired by the need for transparent, efficient, and community-driven LLM tooling.
