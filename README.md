# King Context

Local-first, token-efficient documentation for LLM agents. Scrape any docs site, enrich with structured metadata, and give AI agents exactly the documentation they need — nothing more.

**Status:** Active Development | **License:** MIT

---

## The Problem

LLMs need documentation to write correct code, but current approaches waste tokens:

- **Raw docs in context** — 15,000+ tokens for a single API page, most of it irrelevant
- **Cloud tools (Context7, etc.)** — the server decides what's relevant, returns large blocks, and the LLM pays the token cost whether it needed all that content or not
- **No transparency** — you can't see what's indexed, can't control freshness, can't work offline

---

## The Approach: MCP Server → CLI Pivot

### Phase 1: MCP Server (proved the concept)

We started with an MCP server using SQLite + FTS5 + embeddings, implementing a 4-layer cascade search (cache → metadata → FTS5 → hybrid). Benchmarks against Context7 showed the enriched metadata approach worked:

| Metric | King Context (MCP) | Context7 | Improvement |
|--------|-------------------|----------|-------------|
| Avg tokens/query | 968 | 3,125 | **3.2x fewer** |
| Latency (metadata hit) | 1.15ms | 200-500ms | **170x faster** |
| Latency (FTS) | 97.83ms | 200-500ms | **2-5x faster** |
| Duplicate results | 0 | 11 | **Zero waste** |
| Relevance score | 3.2/5 | 2.8/5 | +14% |
| Implementability | 4.4/5 | 4.0/5 | +10% |

**59-69% token reduction** across all tested queries (ElevenLabs, Gladia, OpenRouter). Full data in [BENCHMARK.md](BENCHMARK.md).

### Phase 2: CLI (where we are now)

The MCP server worked, but we realized something: **the server was making decisions that the agent should make**. It returned full content immediately — the agent had no way to preview, filter, or control the token budget.

We pivoted to a CLI (`kctx`) that gives agents **progressive disclosure**:

```
search (metadata only, ~50 tokens) → preview (~400 tokens) → full read (~1,000 tokens)
```

Each step costs tokens only if the agent decides to go deeper. The agent controls the budget, not the server.

| | CLI (`kctx`) | MCP Server |
|---|---|---|
| **Agent control** | Agent decides what to read | Server decides what to return |
| **Token cost** | Metadata-only search results | Full content in responses |
| **Preview** | `--preview` before full read | No preview mode |
| **Storage** | Plain files (`.king-context/`) | SQLite + FTS5 + embeddings |
| **Dependencies** | Zero for reads | SQLite, numpy, sentence-transformers |

The MCP server is still available for backward compatibility, but the CLI is the recommended interface.

### Phase 3: Real-World Validation

An LLM with zero prior knowledge of the MiniMax TTS API used King Context CLI to:

1. `kctx search "text to speech"` → found the right section in 1 query
2. `kctx read --preview` → confirmed it was relevant (~400 tokens)
3. `kctx read` → read the full API reference (~1,100 tokens)
4. Wrote a **working Python script on the first execution** — zero corrections

**Total: ~2,800 tokens consumed. First-shot accuracy. Zero adjustments.**

For comparison, reading the same API page in a browser would cost 15,000+ tokens — and the LLM would still need to find the relevant parts.

Full details in [`validation/minimax-tts-first-shot/`](validation/minimax-tts-first-shot/).

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

1. **Scrape** — `king-scrape` discovers pages on a docs site, fetches them, chunks the content, and enriches each chunk with structured metadata (keywords, use_cases, tags, priority) via LLM
2. **Index** — `kctx index` builds a file-based data store with reverse indexes for fast lookups
3. **Search** — `kctx search` scores sections by matching query terms against keyword and use_case indexes. No full-text scanning, no embeddings needed for 90% of queries

The metadata enrichment is the core innovation. Each section is annotated with:

```json
{
  "keywords": ["api-key", "bearer-token", "authentication"],
  "use_cases": ["Configure API authentication", "Rotate API keys"],
  "tags": ["security", "setup"],
  "priority": 10
}
```

Agents find the right section through structured metadata instead of scanning raw content. This is what enables the 70% token reduction.

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

# Resume interrupted scrapes (re-run the same command)
king-scrape https://docs.stripe.com --name stripe --yes

# Run individual pipeline steps
king-scrape <url> --name <name> --stop-after fetch   # stop after fetching
king-scrape <url> --name <name> --step chunk          # resume from chunking
king-scrape <url> --name <name> --step export         # resume from export
```

Requires `FIRECRAWL_API_KEY` and `OPENROUTER_API_KEY` in `.env`. The scraper has **intra-step resume**: fetch skips already-downloaded pages, enrich skips already-processed batches.

### Search documentation

```bash
kctx list                                        # list available docs
kctx search "streaming audio"                    # search across all docs
kctx search "auth" --doc stripe --top 3          # search within a specific doc
kctx read stripe authentication --preview        # preview before reading
kctx read stripe authentication                  # full read
kctx topics stripe                               # browse by topic
kctx grep "Bearer" --doc stripe --context 3      # grep for exact patterns
```

All commands support `--json` for machine-parseable output. Full CLI guide with usage examples in [`docs/CLI_GUIDE.md`](docs/CLI_GUIDE.md).

### Real example: MiniMax TTS (first-shot)

This is a real session — Claude had zero knowledge of the MiniMax API:

```bash
$ kctx list
  minimax-tts  66 sections

$ kctx search "text to speech HTTP" --doc minimax-tts
  1. T2A HTTP API Reference (speech-t2a-http-content) score=14.50

$ kctx read minimax-tts speech-t2a-http-content --preview    # ~400 tokens
  # Confirmed: endpoint URL, auth, request/response format

$ kctx read minimax-tts speech-t2a-http-content              # ~1,100 tokens
  # Full spec: models, voice_setting, audio_setting, curl example

$ kctx grep "English_" --doc minimax-tts                     # confirm voice ID
  voice_id: "English_expressive_narrator"
```

**5 commands. ~2,800 tokens. Working Python script on first execution.** See [`validation/minimax-tts-first-shot/`](validation/minimax-tts-first-shot/) for the full code and detailed token breakdown.

---

## Claude Code Skills (Beta)

Skills teach Claude Code how to use King Context effectively.

### `king-context` skill — Documentation Search

Teaches the agent the optimal lookup strategy: check learned shortcuts → list → search → preview → read. Finds the right section in ≤3 CLI calls and saves shortcuts for future sessions.

### `scraper-workflow` skill — Documentation Scraping

Orchestrates the full scraping pipeline with two modes:
- **Workflow A (OpenRouter)** — fully automated via `king-scrape --yes`
- **Workflow B (Claude Code sub-agents)** — uses Haiku for enrichment, Sonnet for filtering, no external LLM API key needed

Supports smart URL resolution (deep page → docs root), topic filtering ("scrape only the TTS docs from this site"), and resume detection.

> Skills are in active development and may change. See the skill files in `.claude/skills/` for details.

---

## Architecture

### CLI — `kctx` (Recommended)

File-based search on `.king-context/` directory. No database, no dependencies for reads.

```
.king-context/
├── stripe/
│   ├── _meta.json              # doc metadata + reverse indexes
│   ├── authentication.md       # section content
│   ├── webhooks.md
│   └── ...
└── elevenlabs-api/
    └── ...
```

### MCP Server (Legacy)

Still available for tools that integrate via the Model Context Protocol:

```bash
claude mcp add king-context -- king-context
python -m king_context.seed_data   # seed SQLite database
```

Uses the 4-layer cascade search (cache → metadata → FTS5 → hybrid embeddings) on SQLite. See [BENCHMARK.md](BENCHMARK.md) for details.

### Scraper — `king-scrape`

Pipeline: discover → filter → fetch → chunk → enrich → export. Each step saves checkpoints to `.king-context/_temp/<domain>/`. Interrupted scrapes resume automatically.

---

## Roadmap

- **Community Documentation Registry** — shared, versioned documentation packages (`kctx install stripe@v1`). A community-maintained library of pre-enriched docs for popular APIs and frameworks
- **Package distribution** — publish as `pip install king-context`
- **Skill improvements** — the scraper workflow skill is in beta. Improving sub-agent reliability, parallel execution, and error handling
- **More validation cases** — testing across different documentation sites, API styles, and complexity levels
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
├── docs/                   # Documentation
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
- **Validation cases** — more real-world examples of LLMs using King Context to build working code

This project is open source because documentation tooling for LLMs should be transparent, community-driven, and independent of any single provider.

---

## License

MIT License. Use it, fork it, improve it.
