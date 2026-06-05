# Local UI server architecture

King Context is a CLI-first, local-first retrieval layer for AI agents. The
local UI is the human-facing complement: a small read-only web server that lets
a person browse ADRs, docs corpora, and research corpora that already live in
`.king-context/`. Agents use `kctx`; humans who want to read, review, and follow
links use the UI.

This document explains how the UI server is built. For the end-user guide (how
to launch it, what each screen shows, troubleshooting) see
[../ui-local.md](../ui-local.md). For the overall stack split see
[overview.md](overview.md), and for why retrieval runs on the flat-file store
rather than the SQLite layer see [cli-retrieval.md](cli-retrieval.md) and
[mcp-legacy.md](mcp-legacy.md).

## Where it sits in the stack

The UI never touches the legacy MCP stack (`server.py` plus `db.py` over SQLite,
FTS5, and embeddings). It reads the same flat-file surface that `kctx` reads,
through the same `context_cli` functions. The two stacks do not share data, and
the UI is firmly on the CLI side of that line (ADR-0005).

```
       +------------------------------------------+
       |              Browser (human)             |
       |   server-rendered HTML + plain JS        |
       |   hand-rolled SVG timeline (ADR graph)   |
       +-----------------+------------------------+
                         | HTTP (127.0.0.1:7373)
       +-----------------v------------------------+
       |        king_context.web.server           |
       |   stdlib http.server + thin adapter      |
       +-----------------v------------------------+
       |        king_context.web.router           |
       |   (method, path, query) -> handler       |
       +-----------------v------------------------+
       |        king_context.web.handlers         |
       |   (path, query, **params) -> (status,    |
       |   dict | bytes)                          |
       +-----------------v------------------------+
       |              context_cli                 |
       |   store.list_docs(), searcher.search(),  |
       |   adr.parse_adr(), adr.search_decisions()|
       +-----------------v------------------------+
       |   .king-context/ (flat-file store)       |
       |   adr/*.md                               |
       |   decisions/project/{graph,sections,...} |
       |   docs/{name}/, research/{topic}/        |
       +------------------------------------------+
```

## Module map

All UI code lives under `src/king_context/web/`.

| Module | Responsibility |
|--------|----------------|
| `server.py` | Entry point `main()`. Parses flags, picks a free port, binds the stdlib `HTTPServer`, opens the browser, and runs `serve_forever()`. The `WebRequestHandler` is the only HTTP-aware class. |
| `router.py` | Maps `(method, path)` to a handler via the `_ROUTES` list, matches path patterns, and serializes handler output to `(status, headers, body_bytes)`. |
| `handlers.py` | Pure domain handlers. Each is `(path, query, **path_params) -> (status, dict | bytes)`. Imports `context_cli`, never `king_context.db`. |
| `render.py` | Markdown to HTML, `string.Template` substitution, the layout wrapper, neighborhood resolution, and the canonical empty-state envelope. |
| `static/` | `app.js`, `graph.js`, `style.css`. Bundled in the wheel. |
| `templates/` | `_layout.html`, `home.html`, `adrs.html`, `corpus.html`, `corpus_root.html`, `search.html`. Bundled in the wheel. |

## Design-for-swap: stdlib server plus thin adapter (ADR-0007)

The server is Python's standard library `http.server`. No web framework, no new
runtime dependency for the transport. This fits a localhost, single-user tool
and keeps the install light.

The cost of `http.server` is that its request model is class-based and
stateful. The UI isolates that by keeping `WebRequestHandler` deliberately thin.
In `src/king_context/web/server.py`, every HTTP verb method funnels into one
`_handle(method)` that does exactly three things: parse the URL and query
string, call `router.dispatch(method, path, query)`, and write the returned
`(status, headers, body)` back. If `dispatch` raises, the adapter returns a
500 with a JSON body; it does not leak a stack trace to the client.

Routing and handlers know nothing about `BaseHTTPRequestHandler`. A handler is
a plain function that returns a tuple. This is the "design for swap" boundary:
if the UI ever outgrows `http.server`, only the adapter in `server.py` changes.
The router and the handler functions move to a new transport (for example
Starlette or FastAPI) untouched, because they were never coupled to the stdlib
request object in the first place.

## Reads only the CLI flat-file surface (ADR-0005)

`src/king_context/web/handlers.py` imports from three `context_cli` modules and
nothing from `king_context.db`:

- `context_cli.store.list_docs(store_dir)` for corpus listings.
- `context_cli.searcher.search(...)` and its `SearchResult` for unified search.
- `context_cli.adr` for `parse_adr`, `search_decisions`, `_load_indexed_decisions`,
  and ID resolution.

Corpus and section reads go directly against the flat-file layout:
`.king-context/docs/{name}/index.json`, `sections/{path}.json`, and the reverse
`tags.json` index. ADR detail reads the Markdown source under
`.king-context/adr/` via `parse_adr`, falling back to the indexed JSON under
`.king-context/decisions/project/` when no source file is found. The ADR graph
endpoint is a pass-through of `.king-context/decisions/project/graph.json`.

There is no SQLite connection anywhere in the `web` package, no embedding model
load, and no FTS5. That is by design: the UI is a view over the same canonical
store the CLI uses, so what a human sees matches what an agent retrieves.

## Read-only MVP (ADR-0006)

The MVP serves `GET` only. Every domain handler returns either rendered content
or an empty-state hint; none of them write to `.king-context/`. The adapter in
`server.py` does register `do_POST`, `do_PUT`, `do_DELETE`, `do_PATCH`, and
`do_OPTIONS`, but they all route through the same `_ROUTES` table, which
contains only `GET` entries. A non-`GET` request to a known path returns 405
(method not allowed); an unknown path returns 404. See `dispatch` in
`src/king_context/web/router.py`.

Refinement (editing an ADR, adjusting section metadata) happens through the CLI
or a text editor, then a manual browser refresh. Read-write is planned but
deferred.

## Assets bundled in the wheel (ADR-0008)

The CSS, JS, and HTML templates ship inside the Python package, not in
`installer/templates/`. `installer/templates/` is for artifacts a user is meant
to edit (skills, env); UI assets belong to the project.

`pyproject.toml` declares `src/king_context` as a wheel package under
`[tool.hatch.build.targets.wheel]`, so the `static/` and `templates/`
directories travel inside it. The code loads them wheel-relative, never from a
hardcoded source-tree path:

- `render.py` reads templates with `importlib.resources.files("king_context.web.templates")`.
- `router.py` serves static files from `Path(__file__).parent / "static"`.

The only new runtime dependency the UI adds is `markdown>=3.5`, declared in
`pyproject.toml` `dependencies`. The Node installer stays dependency-free, and a
UI update rides along with `pip install --upgrade` of the Python package.

## Entry point crosses packages

`kctx ui` lives in the `context_cli` package but the server lives in
`king_context.web`. `context_cli._cmd_ui` (in `src/context_cli/cli.py`) imports
`king_context.web.server.main` lazily and forwards the parsed flags as an argv
list:

```python
def _cmd_ui(args):
    from king_context.web.server import main as web_main
    argv = []
    if args.port is not None:
        argv += ["--port", str(args.port)]
    if args.host:
        argv += ["--host", args.host]
    if args.no_open:
        argv += ["--no-open"]
    sys.exit(web_main(argv))
```

`web.server.main()` returns a process exit code, which `_cmd_ui` passes to
`sys.exit`. The web server uses `return 2` for startup failures (bad
`KCTX_UI_PORT`, no free port, refused bind, or a `0.0.0.0` bind attempt) and
`return 0` on a clean shutdown. This `2` is internal to the web server's own
exit-code convention. It is not the CLI-wide pattern: `kctx` itself uses
`sys.exit(1)` for its error paths, and exit codes 2 and 3 elsewhere belong only
to the scraper CLI (`src/king_context/scraper/cli.py`).

## Startup: port selection and lifecycle

`main()` in `src/king_context/web/server.py`:

1. Resolves the host. Default is `127.0.0.1` (`DEFAULT_HOST`). A `--host 0.0.0.0`
   request is rejected with a message and `return 2`; public bind is not a
   supported MVP case and there is no authentication.
2. Resolves the start port. Precedence is `--port`, then the `KCTX_UI_PORT`
   environment variable, then `DEFAULT_PORT = 7373`. A non-integer
   `KCTX_UI_PORT` prints a warning and aborts with `return 2`.
3. Finds a free port. `find_free_port(host, start, span=20)` tries to bind each
   candidate in `[start, start + 20)` and returns the first that binds. If none
   are free it raises `OSError` with a hint to pass `--port`, and `main()`
   returns 2. This is the auto-increment behavior: a second `kctx ui` on a busy
   7373 lands on 7374, with no cross-process coordination.
4. Binds the `HTTPServer`, prints `King Context UI on http://HOST:PORT (Ctrl+C
   to stop)`, and opens the browser unless `--no-open` was passed.
   `webbrowser.open()` is wrapped in a bare `try/except`, so a headless server
   without a display fails silently and keeps serving; the URL is already in the
   terminal.
5. Calls `serve_forever()`. `KeyboardInterrupt` (Ctrl+C) breaks the loop and the
   `finally` block calls `httpd.server_close()`. There is no `stop` command, no
   PID file, and no single-instance check. The module also exposes test hooks
   (`_server_ready`, `_active_server`) so tests can start the server in a thread
   and shut it down.

### Flags and environment

| Input | Effect |
|-------|--------|
| `--port N` | Start port override. Auto-increment still applies from there. |
| `--host H` | Bind host override. Default `127.0.0.1`. `0.0.0.0` is rejected. |
| `--no-open` | Do not open the browser. |
| `KCTX_UI_PORT` | Default start port when `--port` is absent. |

## Routing

`src/king_context/web/router.py` holds `_ROUTES`, an ordered list of
`(method, pattern, handler, content_type_override)` tuples. `_try_match`
supports three pattern forms:

- Exact paths (`/api/health`).
- A single-segment named parameter (`/api/adrs/{id}`), URL-decoded before it
  reaches the handler.
- A trailing wildcard (`/static/{*rest}`) that captures the remainder of the
  path.

Order matters. `/api/adrs/graph` is registered before `/api/adrs/{id}` so the
literal `graph` is not captured as an ADR ID. `dispatch` walks the list, and if
a path matches but the method does not it returns 405 rather than 404.

Handlers return either a `dict` (serialized to JSON with
`Content-Type: application/json`) or `bytes` (served with the route's
content-type override, or a MIME type derived from the path extension). The
router computes `Content-Length` for every response.

### Routes

HTML pages (human-facing):

| Route | Renders |
|-------|---------|
| `GET /` | Home dashboard: per-source counts for ADRs, docs, research, plus the global search form. |
| `GET /adrs` | ADR list page with the SVG timeline; side panel empty. |
| `GET /adrs/{id}` | Same page with the side panel populated for one ADR. |
| `GET /docs` and `GET /research` | Grid of corpus cards. |
| `GET /docs/{name}` and `GET /research/{name}` | Sidebar of sections (grouped by tag) with an empty viewer hint. |
| `GET /docs/{name}/{section_path}` and `GET /research/{name}/{section_path}` | Same page with the selected section rendered. |
| `GET /search?q=...&source=...` | Search form plus grouped results. |

JSON endpoints (consumed by the page scripts):

| Route | Returns |
|-------|---------|
| `GET /api/health` | `{status, version}`. The version comes from `importlib.metadata.version("king-context")`. |
| `GET /api/adrs` | Light ADR list (no content), sorted by date then ID. |
| `GET /api/adrs/graph` | Pass-through of `graph.json` (`{nodes, edges}`). |
| `GET /api/adrs/{id}` | `{adr, neighborhood}` with full content and resolved related / supersedes / superseded_by links. |
| `GET /api/docs` and `GET /api/research` | Corpus list (`name`, `display_name`, `version`, `section_count`, `base_url`). |
| `GET /api/{docs|research}/{name}/sections` | Light section list (`path`, `title`, `tags`, `priority`), no content. |
| `GET /api/{docs|research}/{name}/sections/{section_path}` | One section with `content_md` and rendered `content_html`. Research sections also carry `source_type`, `published_date`, `domain` when present. |
| `GET /api/search?q=...&source=...` | `{results, scoring}`. |
| `GET /static/{*rest}` | Bundled CSS / JS, with path-traversal guards. |

The `/docs` and `/research` root pages exist so the navigation in `_layout.html`
and the home dashboard cards resolve instead of 404. They reuse
`corpus_index(source_label, ...)` for the payload and render the corpus card
grid (or the canonical empty state) via `corpus_root_page`.

## Server-side rendering

Pages are server-rendered with no client-side framework and no build step.
`render.py` uses `string.Template` for `$var` / `${var}` substitution, with no
conditionals or loops in the templates. Handlers build the inner HTML fragments
in Python (escaping user data with `html_escape`) and pass them in under keys
ending in `_raw` so the template substitution does not double-escape
already-rendered HTML. `render_page` wraps the rendered template inside
`_layout.html` and returns UTF-8 bytes.

Markdown rendering happens on the server. `render_markdown` calls the `markdown`
library with the `fenced_code` and `tables` extensions and falls back to
`<pre>`-wrapped escaped text if the library is missing or raises, so malformed
content never breaks a handler.

## The two ADR-driven page scripts

The `static/` JS is plain (no framework, no bundler) and progressive: pages
render fully server-side, then the scripts add interactivity.

- `graph.js` draws the ADR timeline. It fetches `/api/adrs/graph`, places nodes
  on a horizontal date axis, draws `related` edges as solid Bezier curves and
  `supersedes` edges as dashed lines, and emits a click event carrying the ADR
  ID. If the graph payload is an empty state it shows the `hint` instead of an
  empty SVG.
- `app.js` handles the side panel and navigation. On a node or list click it
  fetches `/api/adrs/{id}`, populates `#adr-panel`, and uses `history.pushState`
  so `/adrs/{id}` URLs stay bookmarkable. It also wires the search form.

## Empty states: fail-soft per source

The UI never hard-fails on missing or partial data. `render.py` defines the
canonical envelope:

```json
{"items": [], "reason": "dir_missing" | "not_indexed" | "parse_error", "hint": "..."}
```

Every handler that can encounter absent data returns this shape with HTTP 200,
not an error status. An empty store is a normal state, not a server fault. The
`HINTS` table in `render.py` maps each `(source, reason)` pair to an actionable
message, for example "Run `king-scrape <url>` or `kctx index <file.json>`" for
docs that exist but are not indexed, or "Run `kctx adr index`" for a missing
graph. The home dashboard surfaces these hints inline per card, so a fresh
project guides the user toward the command that populates each source.

Two ADR-specific cases worth calling out:

- An ADR with invalid frontmatter returns `parse_error` for that ID with a hint
  to run `kctx adr validate`; valid ADRs stay accessible.
- A `related` / `supersedes` / `superseded_by` ID that is not in the index is
  marked `broken: true` by `resolve_neighborhood` and rendered as a visible
  "broken" link rather than a dead hyperlink.

## Security posture

The UI is a localhost, single-user tool with no authentication. Two layers keep
it from doing harm:

- Bind is `127.0.0.1` only. `0.0.0.0` is rejected at startup (ADR-0006 scope).
- Path traversal is blocked in two places. Static file serving in `router.py`
  rejects absolute paths, backslashes, and `..` segments, then resolves the
  target and verifies it stays inside `static/`. Corpus and section reads in
  `handlers.py` validate each path segment with `_safe_segment` and confirm the
  resolved file stays inside the store directory with `_resolve_within`.

There is no CORS header. The UI and its `/api/*` endpoints are same-origin on
the same port.

## Related decisions

- ADR-0005: the local UI reads the CLI flat-file surface, not the MCP SQLite layer.
- ADR-0006: the local UI MVP is read-only; read-write is deferred.
- ADR-0007: Python stdlib `http.server` with a design-for-swap adapter pattern.
- ADR-0008: UI static assets are bundled inside the Python wheel, not in `installer/templates/`.

Read them with `kctx adr read ADR-0005` (and 0006, 0007, 0008), or follow the
links from the running UI at `/adrs`.
