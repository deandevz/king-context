# King Context

Local-first, token-efficient documentation for LLM agents. Scrape any docs site, enrich with structured metadata, and serve to AI agents via a fast CLI — reducing token usage by 70% while enabling first-shot accurate implementations.

**Status:** Active Development | **License:** MIT

---

## Real-World Validation

An LLM with no prior knowledge of the MiniMax TTS API used King Context to:

1. Search indexed docs → found the right API section in 1 query
2. Read ~2,800 tokens of documentation (vs 15,000+ tokens reading the raw page)
3. Produced a **working Python script on the first execution** — zero corrections needed

```
search → preview → read → implement → working
```

**70% fewer tokens. First-shot accuracy.** Full details in [`validation/minimax-tts-first-shot/`](validation/minimax-tts-first-shot/).

---

## How It Works

```
┌─────────────┐     ┌─────────────┐     ┌──────────────┐     ┌───────────┐
│  king-scrape │ ──→ │  data/*.json │ ──→ │  kctx index  │ ──→ │ .king-    │
│  (scraper)   │     │  (enriched)  │     │              │     │  context/ │
└─────────────┘     └─────────────┘     └──────────────┘     └─────┬─────┘
                                                                    │
                                                              ┌─────▼─────┐
                                                              │ kctx CLI  │
                                                              │ search/   │
                                                              │ read/grep │
                                                              └───────────┘
```

1. **Scrape** — `king-scrape` discovers pages, fetches, chunks, and enriches them with structured metadata (keywords, use_cases, tags, priority) via LLM
2. **Index** — `kctx index` builds a file-based data store optimized for fast lookups
3. **Search** — `kctx search` finds the right section through metadata scoring — no full-text scanning, no embeddings needed for 90% of queries

The metadata enrichment is what makes it efficient: instead of dumping entire pages into context, agents search by keywords/use_cases and read only the sections they need.

---

## Quick Start

```bash
git clone https://github.com/deandevz/king-context.git
cd king-context
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

### Scrape documentation

```bash
# Scrape and index an entire docs site
king-scrape https://docs.stripe.com --name stripe --yes
kctx index data/stripe.json

# Scrape with resume support (re-run to continue if interrupted)
king-scrape https://docs.stripe.com --name stripe --yes

# Run individual steps
king-scrape https://docs.stripe.com --name stripe --stop-after fetch
king-scrape https://docs.stripe.com --name stripe --step chunk
king-scrape https://docs.stripe.com --name stripe --step export
```

Requires `FIRECRAWL_API_KEY` and `OPENROUTER_API_KEY` in `.env`. The scraper has **intra-step resume**: fetch skips already-downloaded pages, enrich skips already-processed batches.

### Search documentation (CLI)

```bash
# List available docs
kctx list

# Search by keywords/use cases (metadata only — token efficient)
kctx search "streaming audio"
kctx search "auth" --doc elevenlabs-api --top 3

# Read a section (preview first, then full)
kctx read elevenlabs-api websocket-streaming --preview
kctx read elevenlabs-api websocket-streaming

# Browse by topic
kctx topics elevenlabs-api

# Grep content for exact patterns
kctx grep "Client(" --doc httpx --context 3
```

All commands support `--json` for machine-parseable output.

---

## Why a CLI Instead of MCP

The MCP server approach works, but the CLI is significantly more efficient for AI agents:

| | CLI (`kctx`) | MCP Server |
|---|---|---|
| **Storage** | Plain files (`.king-context/`) | SQLite database |
| **Dependencies** | Zero (reads files) | SQLite + FTS5 + embeddings |
| **Token cost** | Metadata-only search results | Full content in responses |
| **Agent control** | Agent decides what to read | Server decides what to return |
| **Preview** | `--preview` before full read | No preview mode |

The CLI gives agents a **progressive disclosure** pattern: search → preview → read. Each step costs tokens only if the agent decides to go deeper. With MCP, the server returns full content immediately.

---

## Claude Code Skills (Beta)

Skills teach Claude Code how to use King Context effectively. Currently available:

### `king-context` skill
Search strategy with self-learning. Finds the right documentation section in ≤3 CLI calls, saves shortcuts for future sessions.

### `scraper-workflow` skill
Orchestrates the full scraping pipeline with two modes:
- **Workflow A (OpenRouter)** — fully automated via `king-scrape`
- **Workflow B (Claude Code sub-agents)** — uses Haiku for enrichment, Sonnet for filtering, no external API key needed

Supports smart URL resolution (deep page → docs root), topic filtering (scrape only TTS docs from a site with 141 pages), and resume detection.

> **Note:** Skills are in active development and may change.

---

## Benchmark Results

Tested against Context7 across multiple APIs (ElevenLabs, Gladia, OpenRouter):

| Metric | King Context | Context7 | Improvement |
|--------|--------------|----------|-------------|
| Avg tokens/query | 968 | 3,125 | **3.2x fewer** |
| Latency (metadata) | 1.15ms | 200-500ms | **170x faster** |
| Duplicate results | 0 | 11 | **Zero waste** |

**Token reduction: 59-69% across all tested queries.** Full methodology in [BENCHMARK.md](BENCHMARK.md).

---

## Architecture

### CLI (`kctx`) — Recommended

File-based search on `.king-context/` directory. No database required for reads.

```
.king-context/
├── elevenlabs-api/
│   ├── _meta.json              # doc metadata + reverse indexes
│   ├── websocket-streaming.md  # section content
│   ├── authentication.md
│   └── ...
└── stripe/
    └── ...
```

Search scores sections by matching query terms against keyword and use_case indexes stored in `_meta.json`. No FTS5, no embeddings — just fast file reads.

### MCP Server — Legacy

Still available for tools that integrate via the Model Context Protocol:

```bash
claude mcp add king-context -- king-context
python -m king_context.seed_data   # seed SQLite database
```

Uses a 4-layer cascade search (cache → metadata → FTS5 → hybrid embeddings) on SQLite. See [BENCHMARK.md](BENCHMARK.md) for details.

### Scraper (`king-scrape`)

Pipeline: discover → filter → fetch → chunk → enrich → export.

```bash
king-scrape <url>                    # full pipeline
king-scrape <url> --stop-after fetch # partial run
king-scrape <url> --step export      # resume from step
king-scrape <url> --no-llm-filter    # heuristic filter only
```

Each step saves checkpoints to `.temp-docs/<domain>/`. Interrupted scrapes resume automatically.

---

## Documentation Schema

Every indexed documentation follows this enriched structure:

```json
{
  "name": "api-name",
  "sections": [
    {
      "title": "Authentication",
      "keywords": ["auth", "api-key", "bearer-token"],
      "use_cases": ["Configure API authentication", "Rotate API keys"],
      "tags": ["security", "setup"],
      "priority": 10,
      "content": "# Authentication\n\n..."
    }
  ]
}
```

The `keywords`, `use_cases`, `tags`, and `priority` fields are what make search efficient — agents find the right section through structured metadata instead of scanning content.

---

## Roadmap

- **Community Documentation Registry** — shared, versioned documentation packages (`kctx install stripe@v1`). The goal is a community-maintained library of pre-enriched docs for popular APIs and frameworks
- **NPM/PyPI-style distribution** — publish King Context as a standalone package installable via `pip install king-context`
- **Skill improvements** — the scraper workflow skill is in beta. Improving sub-agent reliability, parallel execution, and checkpoint handling
- **Methodology documentation** — King Context is one component of a broader methodology for LLM-assisted development. Separate repository planned

---

## Project Structure

```
king-context/
├── src/context_cli/        # CLI package (kctx)
│   ├── cli.py              # Entry point with subcommands
│   ├── searcher.py         # Metadata-based search engine
│   ├── reader.py           # Section reader with preview
│   ├── indexer.py          # JSON → file structure indexer
│   ├── formatter.py        # Output formatting (plain/JSON)
│   └── grep.py             # Content-level regex search
├── src/king_context/       # MCP server + scraper
│   ├── server.py           # MCP server (FastMCP)
│   ├── db.py               # Cascade search engine + SQLite
│   └── scraper/            # Scraping pipeline (king-scrape)
├── .king-context/          # File-based data store (generated)
├── data/                   # Documentation JSONs (generated)
├── validation/             # Real-world test cases
├── tests/                  # Test suite
└── .claude/skills/         # Claude Code skills (beta)
```

---

## Contributing

Contributions needed:

- **Documentation packages** for popular APIs and frameworks
- **Scraper improvements** — better URL discovery, chunking strategies
- **Skill refinements** — making the Claude Code workflows more reliable
- **Testing** across different documentation sites and use cases

This project is open source because documentation tooling for LLMs should be transparent, community-driven, and independent of any single provider.

---

## License

MIT License. Use it, fork it, improve it.
