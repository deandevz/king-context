# King Context

Portuguese version: [README-pt-br.md](README-pt-br.md).

> *What started as an open-source alternative to Context7 just became the start of something much bigger than we imagined.*

A knowledge retrieval layer for AI agents.

Feed it any corpus — vendor documentation, open-web research, internal notes — and it hands the agent back exactly the slice it needs, when it needs it. Structured metadata, progressive disclosure, no cloud round-trips.

Local first. Token efficient. Open source.

**Status:** actively developed. **License:** MIT.

---

## Why this exists

Agents write better code, better analysis, better anything when they have the right context. The hard part is figuring out what "right" means without dumping the kitchen sink.

A single API page costs 15k tokens of raw markdown, and most of it is noise. Cloud retrieval tools like Context7 send chunks based on semantic similarity — a remote server decides what your agent sees, and the agent pays the token bill whether it needed all of that or not. You can't see what's indexed, you don't control updates, and it doesn't work offline.

King Context takes a different route. Every section of every scraped page or researched source gets structured metadata (keywords, use cases, tags, priority). The agent searches metadata first, previews before reading, and only pulls full content when it actually needs to. The query cache learns the common paths into your corpus, so repeat lookups hit in under a millisecond. Progressive disclosure, not dump.

In practice: an agent with no prior knowledge of an API can read the docs and produce working code on the first try, usually around 2,800 tokens total. A `--high` research sweep on prompt engineering indexed 172 sources and the agent could still hold a full design conversation on top of that corpus using ~4% of its context window.

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

Every command accepts `--json` for machine-readable output. Full reference: [`docs/CLI_GUIDE.md`](docs/CLI_GUIDE.md).

---

## Documentation

In repo wiki under [`docs/`](docs/index.md):

- [Architecture](docs/architecture.md) — how the cascade search, scraper, and researcher fit together
- [Vision](docs/vision.md) — where the project is going, and the design ideas behind it
- [Benchmarks](docs/benchmarks.md) — performance numbers vs Context7
- [Case studies](docs/case-studies.md) — real agent sessions with full traces
- [Roadmap](docs/roadmap.md) — short-term and long-term plans
- [CLI guide](docs/CLI_GUIDE.md) — `kctx` commands and flags

---

## At a glance

- **Token efficient.** ~1,000 tokens per query vs ~3,000 for Context7 in the original benchmark, and 100% factual accuracy vs 84% in the skill-vs-skill round. Numbers and methodology in [Benchmarks](docs/benchmarks.md).
- **Local first.** Your corpus, your machine. No cloud round-trips on retrieval. Works offline.
- **Two intake paths, one retrieval surface.** `king-scrape` for vendor docs, `king-research` for open-web topics. Same enriched JSON, same `kctx` interface.
- **Progressive disclosure.** Metadata search → preview → full read. Agents only pull what they need.
- **Self-warming cache.** Agents write `.king-context/_learned/<corpus>.md` shortcuts as they work. Retrieval gets faster per corpus over time, with no manual wiring.

---

## Contributing

This project is open source because retrieval infrastructure for LLMs should be transparent, community-driven, and independent of any single provider.

Three areas where the project benefits the most from outside help:

- **Corpus packages.** Scrape an API or research a topic you use a lot, and open a PR. A community library of pre-enriched corpora is the biggest lever this project has.
- **Pipeline reliability.** Edge cases in URL discovery, chunking, JavaScript-rendered pages, source filtering.
- **Skill improvements.** Sub-agent reliability, error handling, parallel enrichment.

Read the [contributing guide](CONTRIBUTING.md) for setup, branching, commit style, and the PR workflow. By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

---

## License

MIT. Use it, fork it, improve it.
