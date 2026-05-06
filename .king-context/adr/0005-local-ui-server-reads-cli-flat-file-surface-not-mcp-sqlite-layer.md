---
id: ADR-0005
title: Local UI server reads CLI flat-file surface, not MCP/SQLite layer
status: accepted
date: 2026-05-06
areas:
  - ui
  - retrieval
  - cli
  - architecture
supersedes: []
superseded_by: []
related:
  - ADR-0001
keywords:
  - ui-server
  - flat-file
  - cli-surface
  - retrieval-layer
  - mcp-separation
  - search-cascade
  - context-cli
tags:
  - architecture
  - ui
  - retrieval
  - cli
---



## Context

The project has two coexisting retrieval surfaces. The legacy surface lives in `king_context/db.py` and uses SQLite with FTS5 full-text search plus SentenceTransformer embeddings (~500MB model). It is used by the MCP server. The current surface lives in `context_cli/` and uses flat JSON files in `.king-context/` with reverse-index scoring (`searcher.py`). It is used by all CLI commands and was established as the canonical interface by ADR-0001.

When building the local UI server, it would be technically possible to use `search_cascade()` from `db.py` because it offers FTS5 and embedding-based reranking. Both surfaces exist in the same installed package.

## Decision

The local UI server (`king_context/web/`) reads exclusively from the CLI flat-file surface: `context_cli/searcher.search()` for docs and research, `context_cli/store.list_docs()` for corpus listing, and `context_cli/adr.*` functions for ADR retrieval. It does not import or call `king_context.db`, does not open `docs.db`, and does not load any embedding model.

## Alternatives Considered

Using `search_cascade()` from `db.py` would provide FTS5 full-text search and embedding reranking on top of keyword scoring. Rejected because: it contradicts ADR-0001 (CLI-first as canonical interface), it loads ~500MB of SentenceTransformer at startup making `kctx ui` slow to start, it creates a dependency on `docs.db` being populated separately from `.king-context/`, and it fragments the retrieval contract (two surfaces that can return different results for the same query).

## Consequences

UI startup is instant because no model is loaded. The UI has zero new Python deps for retrieval. UI search behavior evolves with the CLI surface naturally. Future contributors must not add `king_context.db` imports to `king_context/web/` — the UI is a visual layer over the CLI, not an independent retrieval client. If the CLI surface gains new capabilities (FTS, semantic search), the UI inherits them without separate wiring.

## Links

src/context_cli/searcher.py, src/context_cli/store.py, src/context_cli/adr.py, src/king_context/db.py, ADR-0001
