# King Context

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![npm](https://img.shields.io/npm/v/@king-context/cli?label=installer&color=blue)](https://www.npmjs.com/package/@king-context/cli)
[![Status](https://img.shields.io/badge/status-active-brightgreen.svg)](https://github.com/deandevz/king-context)

A retrieval layer for AI agents. Local first, token efficient, open source.

Portuguese version: [README-pt-br.md](README-pt-br.md).

---

Agents work better when they see the right context, not all of it. King Context indexes any corpus you give it (vendor docs, open web research, internal notes, architectural decisions) and hands the agent back exactly the slice it needs. Every section is annotated with structured metadata, so the agent searches before it reads, previews before it pulls full content, and never burns its budget on a file dump.

## Quick start

```bash
npx @king-context/cli init
```

This sets up `.king-context/` in any project: Python venv, CLI tools, agent skills, config templates. Zero manual wiring.

Add your keys:

```bash
cp .king-context/.env.example .env
# FIRECRAWL_API_KEY=...     scraping
# EXA_API_KEY=...           research
# OPENROUTER_API_KEY=...    optional, automated enrichment
```

Build a corpus from a docs site or a topic:

```bash
king-scrape https://docs.stripe.com --name stripe --yes
king-research "prompt engineering techniques" --high --yes
```

Then search and read:

```bash
kctx list
kctx search "authentication" --doc stripe
kctx read stripe authentication --preview     # ~400 tokens
kctx read stripe authentication                # full section
kctx grep "Bearer" --doc stripe --context 3
```

Or drive it through your agent of choice. The CLI is shell native, so any agent that runs commands can use it. Skills ship for Claude Code today, with Codex support and a portable skill format on the roadmap.

Full command reference in [`docs/CLI_GUIDE.md`](docs/CLI_GUIDE.md).

## What you get

**Scrape any docs site.** `king-scrape` discovers pages, fetches them, chunks the content, and enriches each chunk with keywords, use cases, tags, and priority.

**Research any topic.** `king-research` pulls sources from the open web via Exa, chunks them, and indexes the result the same way. Effort levels go from `--basic` (~30 sources) to `--extrahigh`.

**Search without dumping.** Metadata search hits in single-digit milliseconds. The agent previews ~400 tokens before pulling the full section. A query cache learns common paths and collapses repeats to sub-millisecond reads.

**Self-evolving retrieval.** Agents write `.king-context/_learned/<corpus>.md` shortcuts as they work, mapping common questions to exact section paths. The next session skips the search phase. The cache warms itself.

**Architectural decision memory.** `kctx adr` records project decisions as ADRs and indexes them alongside docs and research. Agents check the decision log before changing architecture, so context survives across sessions and contributors.

**One retrieval surface, many corpora.** Vendor docs, research sweeps, internal runbooks, and ADRs are all reachable through the same CLI primitives.

## How it works

Every section of every scraped page or researched source ends up annotated:

```json
{
  "keywords": ["api-key", "bearer-token", "authentication"],
  "use_cases": ["Configure API authentication", "Rotate API keys"],
  "tags": ["security", "setup"],
  "priority": 10
}
```

The agent matches its query against keywords, use cases, and tags first. No full-text scan, no vector similarity on roughly 90% of lookups. It only reads content when metadata says it should, and previews before reading the full thing.

That structured metadata is the core of the idea. It makes progressive disclosure work without losing recall, and it lets the same machinery serve a vendor doc site, a cross-web research sweep, and the project's own decision log.

## Benchmarks

Two rounds against Context7, the most widely used documentation tool for code agents.

### Round 1: MCP vs MCP

| Metric | King Context | Context7 | Improvement |
|---|---|---|---|
| Average tokens per query | 968 | 3,125 | 3.2x less |
| Latency (metadata hit) | 1.15ms | 200 to 500ms | 170x faster |
| Latency (full text search) | 97.83ms | 200 to 500ms | 2 to 5x faster |
| Duplicate results | 0 | 11 | zero waste |
| Relevance | 3.2 / 5 | 2.8 / 5 | +14% |
| Implementability | 4.4 / 5 | 4.0 / 5 | +10% |

### Round 2: skill vs skill

Both tools driven by the same agent (Opus 4.7) through CLI plus skill, on Gemini API docs.

| Metric | Context7 | King Context |
|---|---|---|
| Average tokens per query | ~1,896 | ~1,064 |
| Median tokens per query | 1,750 | 901 |
| Correct facts | 32 / 38 (84%) | 38 / 38 (100%) |
| Hallucinations per query | 0.33 | 0.0 |
| Composite quality (0 to 5) | 3.46 | 4.79 |

The takeaway: progressive disclosure plus structured metadata gives the agent checkpoints to backtrack, refuse to hallucinate, and surface multiple versions of the same parameter. Semantic similarity alone cannot.

Methodology and raw data in [BENCHMARK.md](BENCHMARK.md).

## Where this is going

**Community registry.** Anyone who scrapes a lib or researches a topic can publish the enriched corpus. Others install with one command:

```bash
kctx install stripe@v1
kctx install prompt-engineering-2026
```

Versioned, pre-enriched, current. Vendor docs are a starting point, not a ceiling.

**Specialist skills from corpora.** Feed an indexed corpus to an agent and it can produce a portable skill that knows the lib's idioms, gotchas, and patterns. From a research sweep, a skill that encodes the consensus and the disagreements across 30+ sources. Corpus in, skill out, agent agnostic.

**Living inside the dev loop.** Pin doc versions to the project so the agent never drifts. Surface relevant sections as you work. Notify when upstream docs change in a way that affects code you already shipped.

The aim is not "agent asks, corpus answers". The aim is that your agent always has the right context on hand, quietly, without you having to ask.

## Roadmap

- Community registry with versioned doc and research packages
- `pip install king-context` distribution
- Agent-generated skills built from indexed corpora
- Incremental doc updates without full re-scrape
- Windows installer support
- Benchmark suite covering docs, ADRs, and research corpora
- Workflow hooks that surface relevant sections during active coding
- Indexing for user content (md, txt, pdf, docx, video transcripts)

See [open issues](https://github.com/deandevz/king-context/issues) for active work.

## Interfaces

The CLI is the canonical interface. Any agent that can run shell commands can use King Context: today that means Claude Code via dedicated skills, with Codex support and a unified skill format on the roadmap. The MCP server still ships and runs on the same corpus, useful for non-coding agents and IDE integrations that expect an MCP endpoint. Same corpus, same retrieval shape, pick what fits your environment.

## Contributing

Three areas where help moves the project the most.

- **Corpus packages.** Scrape or research something you use a lot, open a PR. The community library is the biggest lever.
- **Pipeline reliability.** Edge cases in URL discovery, chunking strategies, JavaScript-rendered pages, source filtering.
- **Skills.** Skill workflows are still improving. Better sub-agent reliability, error handling, parallel enrichment, and a unified format that works across agent platforms.

This project is open source because retrieval infrastructure for LLMs should be transparent, community driven, and independent of any single provider.

## License

MIT. Use it, fork it, improve it.
