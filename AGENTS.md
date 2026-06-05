# AGENTS.md

Instructions for AI agents working in the king-context repository. This file is the canonical, tool-neutral rule set. `CLAUDE.md` imports it and adds Claude-Code-specific guidance on top. Do not duplicate content between the two.

## What this project is

King Context is a CLI-first, local-first retrieval layer for AI agents. It indexes any corpus (vendor docs, web research, architecture decisions) into a flat-file store under `.king-context/` and serves it through three console scripts: `kctx` (search and read), `king-scrape` (documentation scraping pipeline), and `king-research` (web research pipeline). It ships as the npm installer `@king-context/cli` plus a Python package with four sub-packages: `king_context`, `context_cli`, `llm_providers`, `scraper_providers`.

The MCP server (`king-context-server`) still ships but is the legacy, secondary surface per ADR-0001. Do not frame the project, its docs, or new features around MCP.

## Non-negotiable rules

- All code, comments, identifiers, documentation, commits, and PR descriptions are written in English.
- Never use em-dashes or en-dashes anywhere: code, comments, docs, READMEs, commits, PR bodies, issues. Use periods, commas, colons, or parentheses instead.
- Never mix languages in the same file. Internal architecture drafts in `.docs/` may be Portuguese; everything else is English. `README-pt-br.md` is the one intentionally Portuguese published file.
- ADRs are created and updated only through the `kctx adr` CLI: draft the markdown elsewhere, import with `kctx adr new --from-file`, then run `kctx adr index` and `kctx adr validate`. Never hand-write or hand-edit files inside `.king-context/adr/`.

## The two retrieval stacks (critical orientation)

The repo contains two parallel retrieval stacks that do not share data:

1. **Canonical: the CLI flat-file stack.** `src/context_cli/` reads and writes JSON under `.king-context/docs/`, `.king-context/research/`, and `.king-context/decisions/`. Search is reverse-index metadata scoring. No SQLite, no embeddings.
2. **Legacy: the MCP SQLite stack.** `src/king_context/server.py` (FastMCP) plus `db.py` (SQLite, FTS5, embedding rerank) with `docs.db` and `data/` at the repo root. Kept as an integration layer per ADR-0001.

Consequences:

- Never couple new code (CLI, web UI, pipelines) to `king_context.db` or `docs.db` (ADR-0005).
- Never use `seed_data` or `python -m king_context.seed_data` to index a corpus; that feeds the legacy MCP database. Index with `kctx index` instead.
- The 4-layer cascade (cache, metadata, FTS5, embeddings) described in older docs applies only to the legacy stack. See `docs/architecture/overview.md`.

## Commands

```bash
# Install for development
pip install -e ".[all,dev]"

# Tests
pytest -q
pytest -k <test_name>

# Search and read indexed corpora (canonical CLI)
kctx list
kctx search "query" --source all|docs|research
kctx read <doc> <section-path>
kctx grep <pattern>
kctx topics <doc>
kctx index <file.json>
kctx adr <list|search|read|timeline|new|supersede|link|index|status|validate>
kctx llm-doctor
kctx ui

# Scrape and index documentation
king-scrape <url>                      # discover, filter, fetch, chunk, enrich, export
king-scrape <url> --provider crawl4ai  # pick scraper provider (default: firecrawl)
king-scrape <url> --step <stage> --stop-after <stage>
king-scrape audit <name>               # read-only corpus drift check
king-scrape update <name>              # incremental refresh reusing unchanged content

# Web research into an indexed corpus
king-research "<topic>" --basic|--medium|--high|--extrahigh
```

Full command reference: `docs/CLI_GUIDE.md`.

## Architecture map

- `src/context_cli/` is the `kctx` CLI, the canonical product surface.
- `src/king_context/scraper/` and `src/king_context/research/` are the two pipelines; `src/king_context/web/` is the local UI behind `kctx ui`.
- `src/scraper_providers/` and `src/llm_providers/` are pluggable provider abstractions (entry-point registries).
- `src/king_context/server.py`, `db.py`, `seed_data.py` are the legacy MCP stack.
- `installer/` is the zero-dependency npm package that bootstraps `.king-context/` into host projects.
- All paths resolve from `PROJECT_ROOT = Path.cwd()`; run commands from the project root.

Deep dives: `docs/architecture/`. Storage details: `docs/reference/storage-layout.md`. Corpus JSON format: `docs/reference/corpus-schema.md`. Environment variables: `docs/reference/env-vars.md`.

## Code conventions

- New code uses PEP 604 unions (`X | None`) and `from __future__ import annotations`; legacy core modules keep `typing.Optional` for local consistency.
- `pathlib` over `os.path`; dataclasses for config and value objects; stdlib `json`.
- CLI modules follow the `_build_parser()` plus `_cmd_<name>(args)` pattern with `set_defaults(func=...)`.
- Errors print `error: <message>` to stderr. The scraper CLI uses exit codes 1 (general), 2 (ValueError), 3 (provider unavailable); `kctx` exits 1 on failure.
- No linter or formatter is configured: match the existing hand-formatted style (4-space indent, trailing commas in multi-line calls).

Details with file references: `docs/contributing/code-style.md`.

## Testing

- Tests live in `tests/` mirroring the `src/` layout; shared fixtures in `tests/conftest.py`.
- Isolate with `tmp_path` and `monkeypatch` (store dirs, `DB_PATH`, dotenv). Patch targets use full module paths.
- Fake all HTTP and LLM calls (`httpx.MockTransport`, fake clients); tests never hit the network.
- CI runs Python 3.11 with pytest plus a blocking crawl4ai smoke job. There is no lint step.

Details: `docs/contributing/testing.md`.

## Commits and PRs

- Conventional Commits in English: `<type>(<scope>): <subject>`, imperative, no trailing period. Types: feat, fix, docs, refactor, test, chore. Scopes are component names (scraper, installer, ui, cli, llm, providers, adr, research).
- PR bodies stay minimal (Summary and Scope), especially for docs and chore PRs.
- Keep PR scope fixed: findings outside the PR's purpose become separate issues, not extra commits.

Details: `docs/contributing/commits-and-prs.md` and `CONTRIBUTING.md`.

## Decision records

Architecture decisions live as ADRs in `.king-context/adr/` (14 and counting). Before proposing or making an architectural change, check existing decisions (`kctx adr search`, `kctx adr timeline`). If a change contradicts an accepted ADR, raise it instead of silently diverging. Workflow: `docs/contributing/adr-workflow.md`.

## Working agreement with the maintainer

- Break multi-step work into stages. Present the plan, then wait for explicit approval before executing each stage.
- Never take a GitHub-facing or irreversible action (comment, issue, PR, close, merge, publish, push) without first showing the exact draft and getting approval for that specific action.
- The maintainer communicates in Portuguese: deliver summaries, verdicts, and explanations in Portuguese. Everything published (code, commits, PRs, issues, comments, docs) is English, previewed before posting.
- Keep responses concise and scannable. Lead with the concrete value or the one-line answer; add technical depth only when asked.
- When something breaks, first explain the root cause in one line (expected vs actual), confirm the fix approach, then apply and test it on a branch.
- Verify by running for real: execute the relevant command end to end in the project venv (real API calls when applicable) and report the observed output. Never claim success from reading code alone.
- In PR review: blocking points go to the contributor on the PR; non-blocking findings become separate follow-up issues. For multiple overlapping PRs from one contributor, consolidate all findings into a single issue and ask for one unified PR.
