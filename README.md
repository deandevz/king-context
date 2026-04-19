# King Context

Portuguese Version: [README.md](README-pt-br.md).

Documentation infrastructure for AI code agents.

Scrapes any documentation site, enriches each section with structured metadata, and hands your agent exactly the docs it needs to write correct code. Nothing more.

Local first. Token efficient. Open source.

**Status:** actively developed. **License:** MIT.

---

## Why this exists

LLMs write better code when they have the right documentation in context. The hard part is figuring out what "right" means.

Dumping raw docs into context burns 15k tokens on a single API page, and most of it is noise. Cloud tools like Context7 ship chunks based on semantic similarity, which means a remote server decides what your agent sees, and the agent pays the token bill whether it needed all that or not. You can't see what's indexed, you don't control updates, and it doesn't work offline.

King Context takes a different route. Every section of every scraped doc gets structured metadata (keywords, use cases, tags, priority). The agent searches metadata first, previews before reading, and only pulls full content when it actually needs to. Progressive disclosure, not dump.

In practice, an agent with no prior knowledge of an API can use King Context to read the docs and produce working code on the first try, usually around 2,800 tokens total. The same workflow browsing a webpage runs 15k+ tokens and still leaves the agent to figure out what matters.

---

## Quick start

One command to install into any project:

```bash
npx @king-context/cli init
```

This creates `.king-context/` with a Python virtual env, the CLI tools, Claude Code skills, and config templates. Zero manual setup.

Add your keys:

```bash
cp .king-context/.env.example .env
# FIRECRAWL_API_KEY=...     required for scraping
# OPENROUTER_API_KEY=...    optional, for automated enrichment
```

Scrape a docs site:

```bash
.king-context/bin/king-scrape https://docs.stripe.com --name stripe --yes
.king-context/bin/kctx index .king-context/data/stripe.json
```

Or just ask Claude Code in plain English: *"scrape the Stripe docs and index them."* The installed skill handles the whole pipeline.

Then search, preview, and read:

```bash
kctx list                                        # show available docs
kctx search "authentication" --doc stripe       # metadata search
kctx read stripe authentication --preview       # about 400 tokens
kctx read stripe authentication                 # full section
kctx grep "Bearer" --doc stripe --context 3     # regex fallback
```

Every command accepts `--json` for machine-readable output.

---

## How it works

Three pieces.

**king-scrape** discovers pages on a docs site, downloads them, chunks the content, and enriches each chunk through an LLM. Each section ends up annotated like this:

```json
{
  "keywords": ["api-key", "bearer-token", "authentication"],
  "use_cases": ["Configure API authentication", "Rotate API keys"],
  "tags": ["security", "setup"],
  "priority": 10
}
```

**kctx index** turns the enriched JSON into a flat file structure with reverse indexes. No database. No embeddings for most queries.

**kctx** is the search interface. It scores sections by matching query terms against the keyword and use case indexes. No full text scan, no vector similarity on roughly 90% of lookups.

The enrichment step is the core of the idea. Agents find the right section through structured metadata instead of scanning raw content. That's what makes progressive disclosure work without losing recall.

---

## Benchmarks

We ran two rounds against Context7, the most widely used documentation tool for code agents today.

### Round 1: MCP server vs MCP server

Original architecture. Both tools exposed as MCP servers, same corpus, same agent.

| Metric | King Context | Context7 | Improvement |
|---|---|---|---|
| Average tokens per query | 968 | 3,125 | 3.2x less |
| Latency (metadata hit) | 1.15ms | 200 to 500ms | 170x faster |
| Latency (full text search) | 97.83ms | 200 to 500ms | 2 to 5x faster |
| Duplicate results | 0 | 11 | zero waste |
| Relevance score | 3.2 / 5 | 2.8 / 5 | +14% |
| Implementability | 4.4 / 5 | 4.0 / 5 | +10% |

Full data in [BENCHMARK.md](BENCHMARK.md).

### Round 2: skill vs skill

Both tools now running as CLI + Claude Code skill, driven by the same agent. The comparison ran on the Google Gemini API docs using Claude Opus 4.7.

| Metric | Context7 (skill) | King Context (skill) | Winner |
|---|---|---|---|
| Average tokens per query | ~1,896 | ~1,064 | King Context |
| Median tokens per query | 1,750 | 901 | King Context |
| Correct facts | 32 / 38 (84%) | 38 / 38 (100%) | King Context |
| Hallucinations per query | 0.33 | 0.0 | King Context |
| Composite quality (0 to 5) | 3.46 | 4.79 | King Context |
| First-shot code (Q4) | compiles | compiles | tie |

### What round 2 actually showed

The token gap shrank compared to round 1, but the story shifted from quantity to quality. With both sides now agent-driven, the difference is in how each tool shapes what the agent can ask for.

Three things King Context did that Context7 didn't:

**Self-correct.** The initial Q1 search missed the model spec page. The agent ran `grep`, found the line, read the section in preview mode, and stopped there. Total cost still lower than Context7's single bloated call. Progressive disclosure (`search, grep, preview, read`) gives the agent checkpoints to backtrack and try another angle without burning budget.

**Refuse to hallucinate.** Q5 asked about `Retry-After` headers. King Context explicitly answered "not present in the indexed docs". Context7 returned about 600 tokens of unrelated curl upload examples, purely because "rate limit" matched by proximity. When retrieval hands back large chunks picked by semantic similarity, false positives slip into context quietly. When retrieval is staged and filtered by metadata, the agent can tell when something is missing.

**Handle ambiguity.** Q3 touched `media_resolution`. The Gemini API has two generations of that parameter. King Context returned both. Context7 returned only the legacy version, which is outdated for Gemini 3. Structured metadata (keywords + use cases + tags) catches both generations; semantic similarity locks onto whichever has more mass in the corpus.

The round 2 win isn't "the agent drives retrieval". Both sides drive retrieval now. The win is the shape of what the agent can reach: small units indexed by metadata, previewable, versus bigger chunks ranked by semantics.

### Limitations we own

* One run per query in round 2, not two. Variance unknown.
* Context7 token counts are per-character estimates, not tiktoken. About 20% margin of error.

---

## Where this is going

King Context started as a search tool. The direction from here is bigger.

The goal is to become the documentation layer that code agents use every day. Three pieces are already taking shape.

### Community documentation registry

Anyone who scrapes the docs for a lib can publish the enriched corpus. Others install with a single command:

```bash
kctx install stripe@v1
kctx install fastapi@latest
```

Community maintained, versioned, always current. Pre-enriched, so you skip the scraping step. Official vendor docs are a starting point, not a ceiling. Communities around specific libs can publish better versions: more examples, deeper use cases, faster update cycles than the official pages.

### Agents that write specialized skills from docs

The docs themselves already contain everything needed to teach an agent to use a lib well. An agent reading your corpus can generate a Claude Code skill that knows the lib's conventions, its gotchas, and its idiomatic patterns. Docs in, skills out.

This is where King Context stops being just a retrieval tool and becomes a skill factory. Every public doc package becomes a candidate for an automatically generated specialized agent.

### Integration into the dev workflow

Retrieval is the baseline. The next layer is making King Context live inside the development loop: pin doc versions to the project so your agent never drifts, monitor upstream doc changes that might affect code you already wrote, surface the relevant sections when the agent notices you working on something.

The idea isn't "agent asks, doc answers". The idea is that your agent always has the right documentation context, quietly, without you having to ask.

---

## CLI and MCP

King Context ships two interfaces. They serve different environments.

The **CLI and the Claude Code skill** are the focus. That's where code agents work best, and that's where the quality numbers from the benchmark come from. If you use King Context inside Claude Code, Cursor, or any agentic coding workflow, that's the path.

The **MCP server** is still supported. Some tools and workflows need native MCP: non-coding agents, IDE integrations, anything that expects an MCP endpoint. It runs on the same corpus and keeps getting improvements, just at a less aggressive pace than the CLI.

Pick based on your environment. The corpus is the same either way.

---

## Project layout

```
king-context/
├── src/context_cli/        # CLI package (kctx)
│   ├── searcher.py         # metadata search
│   ├── reader.py           # section reader with preview
│   ├── indexer.py          # JSON-to-file indexer
│   └── grep.py             # regex fallback
├── src/king_context/       # MCP server and scraper
│   ├── server.py           # MCP server
│   ├── db.py               # SQLite cascade search
│   └── scraper/            # king-scrape pipeline
├── .king-context/          # data store (generated)
├── validation/             # real-world test cases
└── .claude/skills/         # Claude Code skills
```

---

## Roadmap

Short term:

* Community registry with versioned doc packages
* Distribution via `pip install king-context`
* Agent-generated skills built from scraped docs
* Better sub-agent reliability during enrichment

Further out:

* Per-project version pinning, with notifications when upstream docs change
* Workflow hooks that surface relevant docs during active coding
* Smarter scraping: URL discovery, chunk limits, JavaScript-rendered content
* More validation cases covering varied API styles and agent tasks

---

## Contributing

Three areas where the project needs the most help.

**Documentation packages.** If there's an API or framework you use a lot, scrape it and open a PR. A community library of pre-enriched docs is this project's biggest lever.

**Scraper reliability.** Edge cases in URL discovery, chunking strategies for unusual doc formats, better handling of JavaScript-rendered pages.

**Skill improvements.** The Claude Code workflows are in beta. Making sub-agents more reliable, handling errors properly, running enrichment steps in parallel.

This project is open source because documentation infrastructure for LLMs should be transparent, community driven, and independent of any single provider.

---

## License

MIT. Use it, fork it, improve it.
