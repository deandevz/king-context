# Project State

## Active Work

- npm installer (`@king-context/cli`) implemented — init, doctor, update commands working
- Python paths refactored to CWD-relative (`.king-context/docs/`, `.king-context/data/`, `.king-context/_temp/`)

## Decisions

| Date | Decision | Context |
|------|----------|---------|
| 2026-04-16 | Migrate from MCP to CLI+Skill | Industry trend (Playwright, Context7), better token efficiency, more agent control |
| 2026-04-16 | Dual-mode scraper workflow (OpenRouter + Claude Code sub-agents) | Flexibility: OpenRouter for automation, Claude Code sub-agents for users without API key |
| 2026-04-16 | Haiku for enrichment, Sonnet for filter sub-agents | Haiku is sufficient for metadata generation; Sonnet classifies ambiguous URLs better |
| 2026-04-16 | Cumulative batch checkpoints for enrichment | Last batch file contains all enriched chunks — compatible with export.py |
| 2026-04-16 | Intra-step resume for fetch (skip existing .md) and enrich (skip existing batches) | Prevents wasting Firecrawl credits and LLM calls on interrupted pipelines |
| 2026-04-16 | PROJECT_ROOT = Path.cwd() instead of __file__ | Enables king-context to work from any project via venv, not just from cloned repo |
| 2026-04-16 | Everything under .king-context/ (docs/, data/, _temp/, _learned/) | Single boundary between tool internals and user project — clean .gitignore |
| 2026-04-16 | npm installer creates venv automatically | User doesn't need to know Python is involved — `npx @king-context/cli init` handles everything |

## Blockers

None currently.

## Deferred Ideas

- (none yet)

## Lessons Learned

- FilterResult dataclass has required fields `filter_method` and `llm_fallback_used` — test fixtures must include these
