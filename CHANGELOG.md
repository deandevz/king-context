# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
