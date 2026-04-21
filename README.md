# King Context

Portuguese Version: [README-pt-br.md](README-pt-br.md).

> *What started as an open-source alternative to Context7 just became the start of something much bigger than we imagined.*

A knowledge retrieval layer for AI agents.

Feed it any corpus — vendor documentation, open-web research, internal notes — and it hands the agent back exactly the slice it needs, when it needs it. Structured metadata, progressive disclosure, no cloud round-trips.

Local first. Token efficient. Open source.

**Status:** actively developed. **License:** MIT.

---

## Why this exists

Agents write better code, better analysis, better anything when they have the right context. The hard part is figuring out what "right" means without dumping the kitchen sink.

A single API page costs 15k tokens of raw markdown, and most of it is noise. Cloud retrieval tools like Context7 send chunks based on semantic similarity — a remote server decides what your agent sees, and the agent pays the token bill whether it needed all of that or not. You can't see what's indexed, you don't control updates, and it doesn't work offline.

Forcing an agent to read ten 400-line `.md` files is the same problem dressed differently: most of those tokens never mattered for the current step.

King Context takes a different route. Every section of every scraped page or researched source gets structured metadata (keywords, use cases, tags, priority). The agent searches metadata first, previews before reading, and only pulls full content when it actually needs to. The query cache learns the common paths into your corpus, so repeat lookups hit in under a millisecond. Progressive disclosure, not dump.

In practice: an agent with no prior knowledge of an API can read the docs and produce working code on the first try, usually around 2,800 tokens total. A `--high` research sweep on prompt engineering indexed 172 sources and the agent could still hold a full design conversation on top of that corpus using ~4% of its context window. Same workflows browsing raw webpages run 15k+ tokens per page and still leave the agent to figure out what matters.

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
# EXA_API_KEY=...           required for king-research
# OPENROUTER_API_KEY=...    optional, for automated enrichment
```

Scrape a docs site:

```bash
.king-context/bin/king-scrape https://docs.stripe.com --name stripe --yes
.king-context/bin/kctx index .king-context/data/stripe.json
```

Or research an open-web topic — same index, no starting URL needed:

```bash
.king-context/bin/king-research "prompt engineering techniques" --high --yes
.king-context/bin/king-research "retry backoff" --basic --yes
```

`king-research` discovers sources across the web, chunks and enriches them the same way `king-scrape` does, and drops the result into `.king-context/research/<slug>/`. Corpus size scales with effort: `--basic` typically lands ~30 sources in under a minute, `--high` reaches well over 150 in a few minutes, `--extrahigh` is the state-of-the-art sweep.

Or just ask Claude Code in plain English: *"scrape the Stripe docs"* or *"research prompt engineering, detailed"*. The installed skills route to the right pipeline.

Then search, preview, and read — same commands across docs and research:

```bash
kctx list                                           # docs
kctx list research                                  # research corpora
kctx search "authentication" --doc stripe          # metadata search
kctx read stripe authentication --preview          # about 400 tokens
kctx read stripe authentication                    # full section
kctx topics prompt-engineering-techniques          # browse a research tree
kctx grep "Bearer" --doc stripe --context 3       # regex fallback
```

Every command accepts `--json` for machine-readable output.

---

## How it works

Four pieces.

**king-scrape** — point it at a docs site. It discovers pages, downloads them, chunks the content, and enriches each chunk through an LLM.

**king-research** — give it a topic. It generates search queries, pulls sources from the open web via Exa, fetches and chunks their content, and hands the chunks to the same enrichment step as the scraper. `--basic` to `--extrahigh` controls how many queries and how many deepening iterations run.

Both produce the same shape of output. Each section ends up annotated like this:

```json
{
  "keywords": ["api-key", "bearer-token", "authentication"],
  "use_cases": ["Configure API authentication", "Rotate API keys"],
  "tags": ["security", "setup"],
  "priority": 10
}
```

**kctx index** turns the enriched JSON into a flat file structure with reverse indexes. Docs go to `.king-context/docs/`; research goes to `.king-context/research/`. Separate stores, same retrieval surface.

**kctx** is the search interface. It scores sections by matching query terms against the keyword and use case indexes. No full-text scan, no vector similarity on roughly 90% of lookups. A local query cache collapses repeat lookups to sub-millisecond reads. On top of that, agents can write `.king-context/_learned/<corpus>.md` shortcuts as they work — mapping common questions to exact section paths — so the next session skips the search phase entirely. The retrieval layer gets faster per corpus over time, without anyone wiring it up.

The enrichment step is the core of the idea. Agents find the right section through structured metadata instead of scanning raw content. That's what makes progressive disclosure work without losing recall — and it's what lets the same machinery serve both a vendor doc site and a cross-web research sweep.

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

## Case studies

Real sessions, not synthetic benchmarks. Each one captures the command sequence the agent ran, the corpus it worked against, and the artifact it produced.

- **[MiniMax TTS — first-shot code](validation/minimax-tts-first-shot/)** — Agent reads a vendor API reference through `kctx` and writes working code on the first run. 5 lookups, ~2,800 tokens of docs consumed, zero adjustments.
- **[Triage-1 — research-driven synthesis](validation/examples/prompt-engineering-triage1/)** — Agent queries a 172-source `king-research --high` corpus on prompt engineering and composes a production-grade customer-support prompt, cross-referencing 5–6 indexed sources. Full design conversation fits in ~4% of the context window. A `.king-context/_learned/` shortcut file is written mid-session — the retrieval cache warming itself as a side effect of the work.

More cases under [`validation/examples/`](validation/examples/). PRs welcome.

---

## Where this is going

King Context started as a search tool against scraped docs. The direction from here is bigger: a retrieval layer that any agent, on any topic, can lean on without burning its context window.

### The `.md` problem, solved sideways

The dominant pattern for giving agents knowledge today is a folder of markdown files. It falls over the moment the folder gets real. Ten 400-line docs is a five-digit token tax on every turn, and agents still miss the one paragraph that matters.

King Context replaces that pattern. The corpus can be arbitrarily large because the agent never loads it whole. Metadata search filters to the right section, preview returns ~400 tokens, full read returns the rest only if needed. The query cache learns your common paths. The bigger the corpus, the more the retrieval discipline pays off.

### Skills and agents that run on multiple corpora

A skill or sub-agent shouldn't need to carry its reference material in-context. It should query the corpus the same way a developer greps a codebase — narrowly, progressively, only when needed.

With King Context, a single agent can hold an index for Stripe's API, the research sweep on "webhook security", the team's internal runbook, and a domain-specific research corpus (e.g. LATAM cooking techniques, prompt engineering state of the art), and reach into any of them mid-task. The retrieval shape is the same across all of them. Build once, plug in many knowledge bases.

### Community knowledge registry

Anyone who scrapes a lib or researches a topic can publish the enriched corpus. Others install with a single command:

```bash
kctx install stripe@v1
kctx install prompt-engineering-2026
```

Community maintained, versioned, always current. Pre-enriched, so you skip the scraping or research step. Vendor docs are a starting point, not a ceiling — the registry can hold research corpora, curated internal collections, and community-maintained alternates with better examples and faster update cycles.

### Agents that write specialized skills from a corpus

An agent reading your corpus can generate a Claude Code skill that knows the lib's conventions, its gotchas, and its idiomatic patterns. Or, from a research corpus, a skill that encodes the consensus and the disagreements across 30+ sources. Corpus in, skill out.

This is where King Context stops being just a retrieval tool and becomes a skill factory.

### Integration into the dev workflow

Retrieval is the baseline. The next layer is living inside the development loop: pin doc versions to the project so your agent never drifts, monitor upstream doc changes that might affect code you already wrote, surface the relevant sections when the agent notices you working on something.

The idea isn't "agent asks, corpus answers". The idea is that your agent always has the right context on hand, quietly, without you having to ask.

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
├── src/king_context/       # MCP server, scraper, researcher
│   ├── server.py           # MCP server
│   ├── db.py               # SQLite cascade search
│   ├── scraper/            # king-scrape pipeline (URL → corpus)
│   └── research/           # king-research pipeline (topic → corpus)
├── .king-context/          # data store (generated)
│   ├── docs/               # scraped documentation
│   ├── research/           # researched topics
│   └── _learned/           # agent-authored shortcut cache (grows with use)
├── validation/
│   ├── minimax-tts-first-shot/   # doc-driven first-shot code case
│   └── examples/                 # synthesis / multi-source case studies
└── .claude/skills/         # Claude Code skills (king-context, scraper-workflow, king-research)
```

---

## Roadmap

Short term:

* Community registry with versioned doc and research packages
* Distribution via `pip install king-context`
* Agent-generated skills built from scraped docs and research corpora
* Better sub-agent reliability during enrichment
* Richer research pipeline: domain filters, source deduplication across topics

Further out:

* Per-project version pinning, with notifications when upstream docs change
* Workflow hooks that surface relevant sections during active coding
* Smarter scraping: URL discovery, chunk limits, JavaScript-rendered content
* Cross-corpus search (query multiple indices in one call)
* More validation cases covering varied API styles and agent tasks

---

## Contributing

Three areas where the project needs the most help.

**Corpus packages.** If there's an API, framework, or topic you use a lot, scrape it or research it and open a PR. A community library of pre-enriched knowledge bases is this project's biggest lever.

**Pipeline reliability.** Edge cases in URL discovery, chunking strategies for unusual doc formats, JavaScript-rendered pages, better source filtering in `king-research`.

**Skill improvements.** The Claude Code workflows are in beta. Making sub-agents more reliable, handling errors properly, running enrichment steps in parallel.

This project is open source because retrieval infrastructure for LLMs should be transparent, community driven, and independent of any single provider.

---

## License

MIT. Use it, fork it, improve it.
