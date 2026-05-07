---
id: ADR-0013
title: Read-only drift audit for indexed corpora via `king-scrape audit`
status: accepted
date: 2026-05-07
areas:
  - scraper
  - corpus
  - cli
supersedes: []
superseded_by: []
related:
  - ADR-0009
  - ADR-0010
  - ADR-0012
keywords:
  - audit
  - drift-detection
  - http-head
  - url-health
  - discover-diff
  - markdown-report
  - read-only
tags:
  - architecture
  - scraper
  - cli
---


# ADR-0013: Read-only drift audit for indexed corpora via `king-scrape audit`

## Context

A corpus committed under `data/<name>.json` is a snapshot. The upstream docs site keeps moving pages get renamed, deprecated, removed; new sections appear. The MCP server happily serves whatever was indexed, so a contributor has no easy way to ask *"is this corpus still aligned with the live docs, or do I need to re-scrape?"* without paying full pipeline cost (Firecrawl fetch + OpenRouter enrichment) just to find out.

ADR-0012 established content hash provenance through the pipeline so that, eventually, an `--update` flow can answer that question precisely. But:

- Today, many indexed corpora pre-date ADR-0012 and have no `_meta.content_hash`.
- A precise content-diff requires re-fetching every page, which is the expensive part the contributor is trying to avoid before deciding to refresh.
- The most actionable signal *which URLs are flat out broken* is cheap to obtain and useful on its own.

There is a real gap between "do nothing" and "run the full incremental refresh that ADR-0014 will introduce." That gap is what this ADR fills.

## Decision

Introduce a `king-scrape audit <name>` subcommand whose only job is to read an indexed corpus and report drift signals as a Markdown file. The audit is **read-only**: it never mutates `data/<name>.json`, never writes to the database, never spends LLM credits. It is safe to run on a schedule.

The audit runs two passes:

1. **URL health (always).** Walks every unique section URL in the corpus and issues an HTTP `HEAD` (falling back to `GET` when the server returns 405/501). Results are mapped to one of: `fresh` (2xx), `moved` (3xx, with `Location` captured), `broken` (404/410), or `unreachable` (timeout / network error / other 5xx). No provider key is required for this pass, it uses `httpx` directly with bounded concurrency (10).
2. **Discovery diff (optional, default-on).** Calls the configured `DiscoveryProvider` (Firecrawl, Crawl4AI) to re-map the upstream site, then diffs the URL set against the corpus. Reports `new_urls` (in fresh discover, not in corpus) and `orphan_urls` (in corpus, not in fresh discover). `--no-discover` skips this pass for environments without provider keys.

A new module `src/king_context/scraper/audit.py` owns the dataclasses (`SectionAudit`, `CorpusAudit`), the async URL probe, the discovery diff, and a Markdown renderer (`render_report`) plus writer (`write_report`). The CLI dispatcher in `cli.py` delegates to `audit_main(argv)` when invoked as `king-scrape audit ...`. The existing `king-scrape <url>` flow is unchanged `audit` is a sibling subcommand, not a refactor of the existing parser.

Reports land at `.king-context/audit/<name>-<UTC-timestamp>.md`. The exit code is `0` for clean / advisory only audits, `2` when at least one section is broken, so a CI job can gate on it.

## Alternatives Considered

**Inline `--audit` flag on the existing `king-scrape <URL>` invocation.** Rejected because the existing positional argument is a URL, not a name, and conflating the two surfaces would be confusing. Subcommand dispatch keeps the two flows clearly separate at the CLI level.

**Standalone console script (`king-audit`).** Possible, but multiplies the bin surface for a feature that conceptually lives next to the scrape pipeline. The single dispatcher in `king-scrape` matches the way Git, Cargo, and `kctx` already organise their subcommands.

**Full content-hash diff in this PR.** Considered and deferred. ADR-0012 introduced the per-section `_meta.content_hash`; using it here would force this PR to depend on ADR-0012 landing first, and would still be incomplete for pre-ADR-0012 corpora. Splitting URL health into its own change keeps each PR focused and lets contributors get the broken URL signal even on legacy corpora. ADR-0014 (incremental refresh) is the natural home for the content-hash diff because it has to compute fresh page hashes anyway as part of deciding what to re-enrich.

**Mutate `data/<name>.json` with status fields.** Rejected. Keeping the corpus pristine and writing audits to a separate location preserves the simple "read only fact" model of the indexed JSON. A contributor inspecting `data/*.json` should see only what `seed_data` reads, never audit metadata.

## Consequences

Contributors gain a one line, read only command to check whether a corpus is still aligned with upstream. The output is plain Markdown so it diffs nicely, can be committed if desired, or pasted into an issue.

Because the audit never spends LLM credits and never mutates state, it is safe to attach to a CI cron, a pre merge check on corpus PRs, or a manual sanity run before considering a re-scrape.

The dispatcher pattern (`if argv[1] == "audit": ...`) creates a precedent that ADR-0014's `update` subcommand will follow without further refactor. If the project ever grows enough subcommands to warrant `argparse` subparsers, the migration is a local change inside `cli.main` with no impact on the audit module.

A small ongoing maintenance cost: `httpx` was already a dependency through the existing pipeline, so no new transitive dependencies. The audit's HEAD pass is bounded at 10 concurrent requests by default, appropriate for typical corpora (50-500 URLs) without hammering the upstream.

## Links

src/king_context/scraper/audit.py
src/king_context/scraper/cli.py
.king-context/adr/0012-content-hash-provenance-and-enrichment-cache.md
