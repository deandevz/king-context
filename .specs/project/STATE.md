# Project State

## Active Work

- Scraper skill workflow complete — all 7 tasks implemented and tested

## Decisions

| Date | Decision | Context |
|------|----------|---------|
| 2026-04-16 | Migrate from MCP to CLI+Skill | Industry trend (Playwright, Context7), better token efficiency, more agent control |
| 2026-04-16 | Dual-mode scraper workflow (OpenRouter + Claude Code sub-agents) | Flexibility: OpenRouter for automation, Claude Code sub-agents for users without API key |
| 2026-04-16 | Haiku for enrichment, Sonnet for filter sub-agents | Haiku is sufficient for metadata generation; Sonnet classifies ambiguous URLs better |
| 2026-04-16 | Cumulative batch checkpoints for enrichment | Last batch file contains all enriched chunks — compatible with export.py |
| 2026-04-16 | Intra-step resume for fetch (skip existing .md) and enrich (skip existing batches) | Prevents wasting Firecrawl credits and LLM calls on interrupted pipelines |

## Blockers

None currently.

## Deferred Ideas

- (none yet)

## Lessons Learned

- FilterResult dataclass has required fields `filter_method` and `llm_fallback_used` — test fixtures must include these
