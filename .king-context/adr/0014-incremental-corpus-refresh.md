---
id: ADR-0014
title: Incremental corpus refresh via `king-scrape update`
status: accepted
date: 2026-05-08
areas:
  - scraper
  - corpus
  - cli
  - cost
supersedes: []
superseded_by: []
related:
  - ADR-0010
  - ADR-0012
  - ADR-0013
keywords:
  - incremental-refresh
  - content-hash
  - reuse
  - update-flow
  - cost-preview
  - chunk-identity
tags:
  - architecture
  - scraper
  - cli
---


# ADR-0014: Incremental corpus refresh via `king-scrape update`

## Context

A contributor who indexed a docs site months ago and wants to refresh has two options today: rerun `king-scrape <url> --name <name>`, which under the resume rules of fetch.py silently skips changed pages and produces a stale corpus; or wipe `.king-context/_temp/<host>/` and pay the full pipeline cost again, dominated by OpenRouter enrichment ($1 to $3 for a corpus of a few hundred chunks). Neither is acceptable.

ADR-0012 added `content_hash` provenance to every chunk, every section, and every fetched page so that a third path becomes possible: refetch all pages, rechunk, and reuse every section whose chunked content is byte identical to the previous scrape. ADR-0013 added the read only audit subcommand that surfaces drift signals without spending LLM credits. The missing piece is the action that closes the loop: take an audited corpus and actually update it cheaply.

## Decision

Add `king-scrape update <name>`. The command is dispatched the same way as `audit` (a small `if argv[1] == "update": ...` branch in `cli.main`, no argparse subparser refactor) so the existing `king-scrape <url>` flow is unchanged.

The flow:

1. Locate the corpus at `data/<name>.json` or `.king-context/data/<name>.json`. Resolve the source URL from `_meta.source_url` (preferred) or the legacy `base_url` field. A corpus that has neither cannot be updated; the command exits with a clear error pointing at a from scratch rescrape.
2. Build a reuse index from the existing corpus: `content_hash -> { keywords, use_cases, tags, priority }`. For corpora that predate ADR-0012 (no `_meta.content_hash`), recompute the hash from `content` so legacy corpora work without migration.
3. Run discover, filter, fetch with `force_refresh=True`. The new flag bypasses the slug skip behaviour in fetch.py so a changed upstream page is actually redownloaded. Without it, the existing resume logic would mask exactly the drift we are trying to detect.
4. Rechunk all fetched pages. Each fresh chunk carries its own `content_hash` from ADR-0012.
5. For each fresh chunk, look up its `content_hash` in the reuse index. Hit means carry forward the enrichment values; miss means the chunk is genuinely new or changed and needs the LLM.
6. Show a cost preview (reused / new / removed / added URL counts plus the OpenRouter dollar estimate from `enrich.estimate_cost`) and prompt for confirmation. `--yes` skips the prompt for scripted runs.
7. Enrich only the new chunks. The enrichment cache from ADR-0012 catches any further reuse the chunk identity index could not see (different model swap recovery, prompt invariance).
8. Compose the final section list in fresh chunk order. Reused sections keep their carried over enrichment values but adopt the fresh chunk's structural fields (`title`, `path`, `url`) so an upstream page reorganisation is reflected.
9. Write the updated corpus back to the same JSON path. `auto_seed` is left to the user via `kctx index` because update writes to the corpus committed in the repo, not to the local indexed store the MCP server reads.

The integrity unit is the chunk's `content_hash`, not the page or the section. Two changed paragraphs inside a 50 chunk page only re enrich those two chunks.

## Alternatives Considered

**Page level reuse.** Compare the per page sidecar's `content_hash` (ADR-0012) to a stored equivalent and skip the rechunk when the page is identical. Faster than rechunking everything, but rechunking is microseconds per page and the corpus does not currently store a per page hash; adding one for marginal speed up is premature optimisation. Chunk level reuse is correct without it. The page sidecar stays useful for the audit subcommand and for future PRs that want to short circuit the LLM cache lookup.

**Force a full rescrape under a flag.** Considered as a stopgap. Rejected because the LLM cost ($1 to $3 per corpus per refresh) is the entire problem statement; a stopgap that does not solve it is not worth shipping.

**Diff against the audit report from ADR-0013.** Considered as input. Rejected because audit is a snapshot of upstream URL health, not a fresh fetch. Update needs the actual fresh content to compute new hashes, so it duplicates a small amount of audit's URL traversal but with full GET. Audit and update remain orthogonal: audit answers "is this corpus aligned"; update acts on the answer.

**Mutate `data/<name>.json` in place atomically.** Discussed. Current implementation writes through `save_and_index(..., auto_seed=False)`, which uses the same path the original export wrote to. Atomic write via tempfile + replace is a future hardening; the current `save_and_index` is consistent with how export works for fresh scrapes, and update should not diverge there.

**Skip the cost preview by default.** Rejected. Even with cache hits, an unintended `--update` against a corpus with hundreds of changed chunks could silently spend $5+. Cost preview plus confirmation matches the existing fresh scrape ergonomics in `cli.run_pipeline`, where the same prompt fires before enrichment.

## Consequences

A contributor can now run `king-scrape audit my-corpus`, see broken URLs and orphans, then `king-scrape update my-corpus --yes` to actually refresh. The combined flow is one read only check followed by one cheap action.

Cost scales with churn, not with corpus size. A 700 chunk corpus where 5 chunks changed costs the LLM call price for 5 chunks plus negligible disk I/O, vs. the previous full rescrape cost of all 700.

The provider Protocols stay untouched (ADR-0010); `force_refresh` is an additive boolean on `fetch_pages`, not on the FetchProvider contract. Crawl4AI and Firecrawl handle update transparently.

Update writes back to `data/<name>.json` at the same path the original lived. A contributor can `git diff data/<name>.json` to inspect exactly which sections changed before committing the refresh, which is a meaningful QA improvement for community corpus contributions.

`auto_seed=False` on the export means the user's local MCP index is not automatically refreshed. They run `kctx index .king-context/data/<name>.json` (or `kctx index --all`) when they want the new corpus visible to retrieval. This matches the project's existing ethos: indexed retrieval state is reproducible from the JSON committed in the repo, never the source of truth.

The dispatcher pattern grows to two subcommands (`audit`, `update`); a third or fourth would justify a real argparse subparser refactor. For now the four line `if argv[1] == "X":` branch is the right shape.

## Links

src/king_context/scraper/update.py
src/king_context/scraper/fetch.py
src/king_context/scraper/cli.py
.king-context/adr/0012-content-hash-provenance-and-enrichment-cache.md
.king-context/adr/0013-corpus-drift-audit-subcommand.md
