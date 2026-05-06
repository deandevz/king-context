---
id: ADR-0007
title: Python stdlib http.server with design-for-swap adapter pattern for local UI server
status: accepted
date: 2026-05-06
areas:
  - ui
  - server
  - architecture
supersedes: []
superseded_by: []
related:
  - ADR-0001
  - ADR-0004
keywords:
  - http-server
  - stdlib
  - design-for-swap
  - adapter-pattern
  - fastapi-migration-path
  - zero-deps
  - http-transport
tags:
  - architecture
  - ui
  - server
---




## Context

The local UI server needs an HTTP transport layer. Options available without adding new dependencies include Python's built-in `http.server` module and Node.js built-in `http` module. Options with new dependencies include FastAPI, Starlette (transitively present via `fastmcp`), and Flask.

The project has an established pattern of preferring zero external deps when sufficient (installer is pure Node.js built-ins; CLI uses only stdlib `json`, `pathlib`, `argparse`). The UI server is a localhost single-user tool; high-concurrency and async are not requirements for v1.

## Decision

Use Python `http.server` from the standard library as the HTTP transport for the MVP. Implement a design-for-swap adapter pattern: all request handlers are pure functions with signature `(path: str, query: dict, body: bytes) -> (status: int, headers: dict, body: dict)`. The `BaseHTTPRequestHandler` subclass is a thin adapter that parses the HTTP request, calls the appropriate handler function, and serializes the response. Swapping to Starlette or FastAPI later means replacing only the adapter class, not any handler logic.

## Alternatives Considered

FastAPI or Starlette: already transitively available via `fastmcp`, would provide async, automatic OpenAPI docs, and cleaner routing. Rejected for MVP because adding framework deps before proving UI value is premature; the single-user localhost use case does not require async. The design-for-swap pattern ensures this is not a permanent constraint.

Node.js built-in `http` module: zero npm deps, consistent with installer tooling. Rejected because it would require IPC or subprocess calls to reach the Python data layer (`context_cli/`), adding latency and cross-process error handling complexity for no benefit.

Flask: simpler than FastAPI but still an external dep with its own conventions. Same reasoning as FastAPI applies.

## Consequences

Zero new Python deps for the HTTP transport layer. Handler functions are independently testable without an HTTP framework or test client. Single-threaded stdlib server is sufficient for localhost single-user usage. When the UI grows in complexity (async, middleware, request validation, auth for read-write v2), migration to Starlette or FastAPI is a one-file adapter swap that does not touch handler logic. The design-for-swap pattern must be preserved: contributors must not call `self.send_response()` or other `BaseHTTPRequestHandler` methods directly from handler functions.

## Links

src/king_context/web/server.py, src/king_context/web/handlers.py, ADR-0001, ADR-0004
