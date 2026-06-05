# Roadmap

_Last updated: 2026-06-05._

King Context is a CLI-first, local-first retrieval layer for AI agents. This
page is the detailed, prioritized view of where the project is going. For the
headline list, see [Where this is going](../README.md#where-this-is-going) and
[Roadmap](../README.md#roadmap) in the README. The two README sections are the
single source of truth for the public-facing direction; this file expands on
them with priority reasoning and links into the architecture and reference
docs.

For active work, see the
[open issues](https://github.com/deandevz/king-context/issues).

## Recently shipped

These items appeared on earlier versions of this roadmap and are now delivered.
They are listed here so the roadmap reflects current state rather than past
intent. See [CHANGELOG.md](../CHANGELOG.md) for the full record.

| Item | Where it landed |
| --- | --- |
| GitHub Actions CI for tests | `.github/workflows/test.yml`, released in 0.4.0 |
| Pluggable scraper backends, including JavaScript-rendered pages via the Crawl4AI provider | ADR-0009 / ADR-0010 / ADR-0011, released in 0.4.0 |
| Incremental corpus updates without a full re-scrape | `king-scrape update`, ADR-0014 |
| Corpus drift audit (broken, moved, drifted URLs) | `king-scrape audit`, ADR-0013 |
| Local read-only web UI for ADRs, docs, and research | `kctx ui`, released in 0.3.2 |
| Beta Ollama and local model support | `src/llm_providers/`, ADR-0003, released in 0.3.0 |

## Short term

- Community registry with versioned doc and research packages. The
  `kctx install <name>@<version>` shape sketched in the README is the target;
  it does not exist in `src/context_cli/cli.py` yet.
- Standalone PyPI distribution (`pip install king-context`). Today the package
  installs from git through the npm installer (`npx @king-context/cli init`).
- Agent-generated skills built from indexed corpora. See [skills](skills.md)
  for the skills that ship today.
- Better sub-agent reliability during enrichment. The enrich step already
  isolates per-chunk provider failures so one bad chunk does not abort the
  batch; the remaining work is on the agent-driven scraper workflow.
- Richer research pipeline: domain filters and source deduplication across
  topics. Today `--no-filter` is accepted as a no-op in the research CLI, so
  this is net-new work. See [research pipeline](architecture/research-pipeline.md).
- Benchmark suite covering docs, ADRs, and research corpora. Current numbers
  are in [benchmarks](benchmarks.md).

## Further out

- Per-project version pinning, with notifications when upstream docs change.
  The drift audit (`king-scrape audit`) already detects change; pinning and
  notification are the next layer on top of it.
- Workflow hooks that surface relevant sections during active coding.
- Cross-corpus search (query multiple indices in one call). Today `kctx search`
  spans the `docs` and `research` stores; arbitrary multi-corpus queries are
  the goal. See [CLI retrieval](architecture/cli-retrieval.md).
- Indexing for user content (md, txt, pdf, docx, video transcripts) so the
  store is not limited to scraped sites and researched topics.
- More validation cases covering varied API styles and agent tasks.
- Windows installer general availability (currently beta, shipped in 0.3.1).
- A unified, agent-agnostic skill format. Skills ship for Claude Code today,
  with Codex support and a portable format planned.

## Out of scope (for now)

- Hosted or multi-tenant service. King Context is local-first by design; the
  flat-file store under `.king-context/` is the canonical stack
  (see [storage layout](reference/storage-layout.md)).
- CLI/MCP feature parity. New capabilities expose CLI primitives first. The
  MCP server (`server.py` plus the `db.py` SQLite/FTS5/embeddings cascade) is
  the legacy/secondary stack per ADR-0001, and the two stacks do not share
  data. See [MCP legacy](architecture/mcp-legacy.md).

## How priorities are set

Priorities follow contributor leverage:

1. **Corpus packages.** A community library of pre-enriched corpora is the
   project's single biggest lever. Anything that lowers the cost of producing
   or sharing a corpus jumps the queue.
2. **Pipeline reliability.** Edge cases in scraping and research that produce
   empty or low-quality corpora block everything else. See
   [scraper providers](architecture/providers.md).
3. **Agent ergonomics.** Skills, CLI ergonomics, and the legacy MCP surface
   are what agents touch. Improvements here compound across every corpus.
4. **Distribution.** Easy install and update paths grow the user base, which
   feeds back into corpus and reliability work.

If you have an idea that fits the leverage model but is not on this list, open
an issue or a discussion, or follow the [ADR workflow](contributing/adr-workflow.md)
if it is an architectural decision. The roadmap is not a ceiling.
