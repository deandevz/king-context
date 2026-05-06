---
id: ADR-0004
title: Treat multi-OS compatibility (macOS, Linux, Windows) as a baseline
status: accepted
date: 2026-05-06
areas:
  - installer
  - cli
  - testing
  - product
supersedes: []
superseded_by: []
related:
  - ADR-0001
  - ADR-0002
  - ADR-0007
  - ADR-0008
keywords:
  - multi-os
  - windows
  - cross-platform
  - installer
  - testing
tags:
  - architecture
  - installer
  - platform
---







# Treat multi-OS compatibility as a baseline

## Context

King Context started Unix-first and only added Windows support reactively when issue #19 was filed. Going forward the project's reach (community registry, agent-installable corpora) depends on running anywhere a developer's agent runs, and that includes Windows. Treating Windows as an afterthought leads to hardcoded `bin/`, hardcoded `python3`, and tests that pass only on the maintainer's box.

## Decision

All new code paths in `installer/`, `src/king_context/`, `src/context_cli/`, and tests must be developed with macOS, Linux, and Windows compatibility as a non-negotiable baseline. New features that touch filesystem layout, process spawning, shell invocation, or path handling must use platform-aware helpers (for example `path.win32` and `path.posix` in Node, `pathlib` in Python, the shared helpers in `installer/lib/python.js`) instead of platform-specific literals. Tests that exercise platform-specific behavior must use those same helpers so they pass on any host.

## Alternatives Considered

Continuing Unix-first with opportunistic Windows fixes preserves short-term velocity but produces drift like the bugs caught in PR #26 (test that only passes on Windows, orphan wrapper templates). Splitting into Unix-only and Windows-only code paths duplicates logic and makes review harder. Dropping Windows support outright shrinks the user base of the npm installer, which is the primary user-facing entry point.

## Consequences

Reviews and CI must check that new code does not assume `bin/python`, `python3`, forward-slash paths, or POSIX-only shell idioms. Tests that touch paths or process spawning must mock at the helper level, not at `path.join` directly. The installer scaffold contract (ADR-0002) extends to platform abstraction: there is one path resolver per concept, used by init, update, and doctor alike. Windows is currently beta and existing bugs are tolerated during the beta window, but new contributions are held to the baseline.

## Links

installer/lib/python.js, installer/lib/scaffold.js, installer/lib/doctor.js, tests/test_installer_scaffold.py, ADR-0001, ADR-0002
