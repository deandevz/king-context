---
id: ADR-0008
title: UI static assets bundled inside Python wheel, not in installer templates
status: accepted
date: 2026-05-06
areas:
  - ui
  - installer
  - architecture
supersedes: []
superseded_by: []
related:
  - ADR-0001
  - ADR-0002
  - ADR-0004
keywords:
  - python-wheel
  - package-data
  - static-assets
  - installer-templates
  - bundling
  - ui-assets
tags:
  - architecture
  - ui
  - installer
---





## Context

The installer has an established `templates/` directory pattern for artifacts that are copied into the user's project during `init`: skills (`.claude/skills/`), env example (`.king-context/.env.example`), and agent definitions. Following this pattern, UI assets (HTML, CSS, JS) could be placed in `installer/templates/ui/` and copied to `.king-context/ui/` during installation.

An alternative is to treat UI assets as part of the Python package itself, bundled inside the wheel via `package_data` and served directly from the installed package path.

## Decision

UI static assets (`src/king_context/web/static/`, `src/king_context/web/templates/`) are packaged inside the Python wheel via `package_data` in `pyproject.toml`. They are not copied to `installer/templates/` and are not placed in `.king-context/` in the user's project. The server resolves asset paths via `Path(__file__).parent / "static"`.

## Alternatives Considered

Placing assets in `installer/templates/ui/` and copying to `.king-context/ui/` during init would follow the existing skills/env pattern. Rejected because: UI assets are not user-editable (unlike skills, which users customize), so the `templates/` convention would be semantically wrong; `update.js` would need new overwrite logic to refresh assets on upgrade (unlike skills, which users may have modified); reading files outside the package breaks path portability across OS (conflicts with ADR-0004); and it would add a new directory to the `.king-context/` scaffold contract managed by ADR-0002.

## Consequences

UI assets update automatically with `pip install --upgrade` alongside the Python code, with no extra installer logic. The `installer/lib/scaffold.js` scaffold contract (ADR-0002) requires no changes for the UI feature. Path resolution is `Path(__file__).parent / "static"` — portable on all OS per ADR-0004. The `installer/templates/` convention remains reserved exclusively for user-owned, user-editable artifacts. If a user ever wants to customize the UI appearance, the pattern to follow is a `.king-context/ui-overrides/` directory loaded on top of package defaults (not modifying package files).

## Links

src/king_context/web/static/, src/king_context/web/templates/, installer/lib/scaffold.js, pyproject.toml, ADR-0002, ADR-0004
