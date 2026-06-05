# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

The imported `AGENTS.md` above is the canonical rule set: project identity (CLI-first, MCP legacy), the two retrieval stacks, commands, code conventions, testing, commits, ADRs, and the working agreement with the maintainer. Everything below is Claude-Code-specific.

## Skills

This repo ships and uses Claude Code skills. Use them instead of improvising the equivalent workflow:

| Task | Skill |
|---|---|
| Create a PR | `pr-create` (authoritative; minimal Summary and Scope body) |
| Review a contributor PR | `pr-review-flow` (Portuguese verdict first, English preview after approval, confirm before every GitHub action) |
| Create a commit | `commit-create` |
| Capture a deferred idea as a GitHub issue | `idea-issue` (plain English, no invented solutions, preview first, `idea` label) |
| Record an architecture decision | `king-record-decision` (drives `kctx adr`, never hand-written ADR markdown) |
| Query past decisions | `king-decisions` |
| Search indexed documentation | `king-context` |
| Scrape and index docs | `scraper-workflow` |
| Research a topic into a corpus | `king-research` |

The five king-context skills (`king-context`, `scraper-workflow`, `king-research`, `king-decisions`, `king-record-decision`) are also distributed to user projects by the installer; their templates live in `installer/templates/skills/`. When editing a skill, keep the repo copy and the template in sync. See `docs/skills.md`.

## Claude-specific notes

- The repo's own `.claude/skills/king-context/skill.md` intentionally calls bare `kctx`, while the installer template uses `.king-context/bin/kctx` wrapper paths. Do not "fix" one to match the other.
- Tests for MCP server tools mock `search_cascade()` and other `db` functions with full module paths (`king_context.db.x`, `king_context.server.x`).
- When verifying CLI behavior end to end, use the repo venv: `.venv/bin/kctx`, `.venv/bin/king-scrape`, `.venv/bin/king-research`.
