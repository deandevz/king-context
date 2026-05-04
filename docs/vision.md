# Vision

King Context started as a search tool against scraped docs. The direction from here is bigger: a retrieval layer that any agent, on any topic, can lean on without burning its context window.

## The `.md` problem, solved sideways

The dominant pattern for giving agents knowledge today is a folder of markdown files. It falls over the moment the folder gets real. Ten 400-line docs is a five-digit token tax on every turn, and agents still miss the one paragraph that matters.

King Context replaces that pattern. The corpus can be arbitrarily large because the agent never loads it whole. Metadata search filters to the right section, preview returns ~400 tokens, full read returns the rest only if needed. The query cache learns your common paths. The bigger the corpus, the more the retrieval discipline pays off.

## Skills and agents that run on multiple corpora

A skill or sub-agent shouldn't need to carry its reference material in-context. It should query the corpus the same way a developer greps a codebase — narrowly, progressively, only when needed.

With King Context, a single agent can hold an index for Stripe's API, the research sweep on "webhook security", the team's internal runbook, and a domain-specific research corpus, and reach into any of them mid-task. The retrieval shape is the same across all of them. Build once, plug in many knowledge bases.

## Community knowledge registry

Anyone who scrapes a lib or researches a topic can publish the enriched corpus. Others install with a single command:

```bash
kctx install stripe@v1
kctx install prompt-engineering-2026
```

Community maintained, versioned, always current. Pre-enriched, so you skip the scraping or research step. Vendor docs are a starting point, not a ceiling — the registry can hold research corpora, curated internal collections, and community-maintained alternates with better examples and faster update cycles.

## Agents that write specialized skills from a corpus

An agent reading your corpus can generate a Claude Code skill that knows the lib's conventions, its gotchas, and its idiomatic patterns. Or, from a research corpus, a skill that encodes the consensus and the disagreements across 30+ sources. Corpus in, skill out.

This is where King Context stops being just a retrieval tool and becomes a skill factory.

## Integration into the dev workflow

Retrieval is the baseline. The next layer is living inside the development loop: pin doc versions to the project so your agent never drifts, monitor upstream doc changes that might affect code you already wrote, surface the relevant sections when the agent notices you working on something.

The idea isn't "agent asks, corpus answers". The idea is that your agent always has the right context on hand, quietly, without you having to ask.

---

## CLI and MCP

King Context ships two interfaces. They serve different environments.

The **CLI and the Claude Code skill** are the focus. That's where code agents work best, and that's where the quality numbers from the [benchmarks](benchmarks.md) come from. If you use King Context inside Claude Code, Cursor, or any agentic coding workflow, that's the path.

The **MCP server** is still supported. Some tools and workflows need native MCP: non-coding agents, IDE integrations, anything that expects an MCP endpoint. It runs on the same corpus and keeps getting improvements, just at a less aggressive pace than the CLI.

Pick based on your environment. The corpus is the same either way.
