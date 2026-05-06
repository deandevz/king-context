# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.1] - 2026-05-06

### Added

- Windows support for the installer (beta). `king-context init`, `update`,
  and `doctor` now work on Windows: `py -3` detection, `Scripts\python.exe`
  resolution, `python -m pip` invocation, and `.cmd` shims for `kctx`,
  `king-scrape`, and `king-research`. Existing macOS and Linux behavior is
  preserved. Co-authored with @Vadelo (issue #19).
- ADR-0004: treat multi-OS compatibility (macOS, Linux, Windows) as a
  baseline development constraint.

### Changed

- Path helpers in `installer/lib/python.js` now use `path.win32` /
  `path.posix` based on `process.platform`, so Windows path assertions
  pass on any host.
- Removed orphan `installer/templates/wrapper-*.sh` files. Wrapper bodies
  are inlined in `scaffold.js` and the templates are no longer read.

## [0.3.0] - 2026-05-05

### Added

- Beta Ollama and local model support via a new pluggable provider layer
  in `src/llm_providers/`. `king-scrape`, `king-research`, and the new
  `kctx llm-doctor` command can now talk to OpenRouter, Ollama local
  (OpenAI-compatible), Ollama native/cloud, and an optional Ollama to
  OpenRouter fallback. Default behavior for existing OpenRouter users is
  unchanged. ([#40](https://github.com/deandevz/king-context/pull/40))
- Stage-aware provider configuration via new env vars: `ENRICH_*`,
  `FILTER_*`, `RESEARCH_*`, `OLLAMA_*`, `CONCURRENCY_*`, and
  `ENABLE_FALLBACK`. Centralized `.king-context/.env` and `.env` loading
  through `src/king_context/env.py`.
- `kctx llm-doctor` diagnostics command and a Node-side `doctor` Ollama
  hook (warning only) so users can verify provider, model, and
  reachability before running a stage.
- ADR-0003 recording the pluggable LLM provider decision, plus
  `docs/ollama.md` setup guide and updated `docs/CLI_GUIDE.md` LLM
  section, EN/PT-BR READMEs, installer env template, and king-context
  skills.

### Changed

- Bumped the Python package version from `0.2.0` to `0.3.0` so it matches
  the npm installer release and the `v0.3.0` GitHub tag. Code already
  shipped in v0.3.0, this is metadata only.
  ([#41](https://github.com/deandevz/king-context/pull/41))

### Removed

- Untracked `.specs/features/local-models-enrichment/human.md` that
  slipped through the `.specs/` gitignore rule in the previous PR. Local
  copy preserved on disk and now ignored as intended.
  ([#41](https://github.com/deandevz/king-context/pull/41))

## [0.2.1] - 2026-05-02

### Fixed

- Installer now passes `--no-cache-dir` (and `--force-reinstall --no-deps`
  on upgrade) when installing the `king-context` Python package from git.
  Previously, pip cached the built wheel under the unchanged version
  `0.1.0`, so `init`/`update` silently reused the stale wheel and missed
  new commits on `main` (e.g. the ADR commands shipped in 0.2.0). Bumped
  the Python package version to `0.2.0` so cached wheels from earlier
  installs are no longer matched.

## [0.2.0] - 2026-05-02

### Added

- ADR (Architecture Decision Record) memory for the CLI. New `kctx adr`
  subcommands let agents record, list, and recall architectural decisions
  across sessions. Two new skills (`king-decisions` and `king-record-decision`)
  plug into Claude Code so agents use the decision log without manual
  prompting. Installer now scaffolds an `.king-context/adr/` directory and
  seeds it with two example ADRs that document the project's own
  architectural choices.

### Changed

- Renamed the Python MCP server console script from `king-context` to
  `king-context-server`. The `king-context` name is reserved for the npm
  installer (`@king-context/cli`), which is the user facing entry point.
  Users with a Claude Code or Claude Desktop MCP config that points at
  `king-context` should update it to `king-context-server`. The
  `python -m king_context.server` invocation is unchanged.
