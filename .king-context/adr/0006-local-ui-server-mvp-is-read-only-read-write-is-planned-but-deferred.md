---
id: ADR-0006
title: Local UI server MVP is read-only; read-write is planned but deferred
status: accepted
date: 2026-05-06
areas:
  - ui
  - product-strategy
  - architecture
supersedes: []
superseded_by: []
related:
  - ADR-0001
keywords:
  - read-only
  - mvp
  - read-write
  - deferred
  - ui-server
  - incremental
  - scope
tags:
  - architecture
  - product
  - ui
---



## Context

The local UI server was designed to help humans review and refine corpus content (ADRs, docs, research). "Refine" could naturally imply editing: updating ADR content, fixing section metadata, removing low-quality sections. The architecture document explicitly lists read-write as a v2 goal.

Building write support from the start would require: file locking for concurrent edits, integration with `kctx adr validate` before persisting ADR changes, conflict resolution when content is modified outside the UI simultaneously, and a more complex API surface with mutation endpoints.

## Decision

The v1 UI is strictly read-only. No write endpoints, no edit forms, no save operations. All handler functions return data; none mutate `.king-context/` files. The architecture uses pure handler functions `(path, query, body) -> (status, headers, dict)` which makes adding write handlers in v2 additive rather than a refactor. "Refinement" in v1 means the human identifies issues visually and corrects them via CLI or editor outside the UI.

## Alternatives Considered

Building read-write from day one would deliver the full vision immediately. Rejected because it significantly increases scope before the UI has proven usage patterns, risks building the wrong editing UX, delays shipping a useful navigation tool, and introduces correctness requirements (validation, locking) that are out of scope for a quality-of-life MVP. Incremental delivery is more aligned with the project's approach (ADR-0001: CLI-first, prove value before expanding surface).

## Consequences

v1 ships faster and with a smaller attack surface. The human workflow for refinement in v1 is: browse in UI, spot issue, fix via `kctx adr` CLI or editor, refresh UI. v2 adds write endpoints without breaking the existing read layer. Contributors adding write endpoints before a v2 ADR is accepted should treat this decision as a blocker requiring a supersession process.

## Links

.docs/LOCAL-UI-SERVER-ARCHITECTURE.md, ADR-0001
