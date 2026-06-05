# CLI retrieval stack

King Context is a CLI-first, local-first retrieval layer for AI agents. The
`kctx` command is the primary interface. It is a pure-Python search tool over
flat JSON files under `.king-context/`: no SQLite, no FTS5, no embeddings, no
network calls for search or read. Everything an agent needs to find and read a
section is computed from files on disk.

This is the canonical stack. The MCP server (`src/king_context/server.py` plus
`db.py` with SQLite/FTS5/embeddings) is the legacy/secondary stack per ADR-0001,
and the two stacks do not share data. For the legacy path see
[mcp-legacy.md](mcp-legacy.md). For how corpora are produced see
[scraper-pipeline.md](scraper-pipeline.md) and
[research-pipeline.md](research-pipeline.md).

The package lives at `src/context_cli/`. The console script is registered in
`pyproject.toml` as `kctx = context_cli.cli:main`.

## Path resolution

All store roots are CWD-relative constants in `src/context_cli/__init__.py`:

```python
PROJECT_ROOT = Path.cwd()
STORE_DIR = PROJECT_ROOT / ".king-context" / "docs"
RESEARCH_STORE_DIR = PROJECT_ROOT / ".king-context" / "research"
DECISIONS_STORE_DIR = PROJECT_ROOT / ".king-context" / "decisions"
```

`PROJECT_ROOT = Path.cwd()` means paths resolve from the directory `kctx` is run
in, not from where the package is installed. Run `kctx` from a project root that
contains a `.king-context/` directory. The implication: the same installed
`kctx` operates on a different store depending on the current working directory,
so each project gets its own isolated retrieval store with no extra
configuration.

Store directories are passed explicitly into the searcher, reader, and grep
functions rather than read from module globals. `store.py` keeps a
`get_store_dir()` helper that returns `STORE_DIR`, but it covers only the docs
store. `cli.py` imports `STORE_DIR` and `RESEARCH_STORE_DIR` directly and builds
its own multi-store lists, so `store.get_store_dir()` is effectively legacy for
the multi-store CLI. See [storage-layout.md](../reference/storage-layout.md) for
the full on-disk map.

## Store layout produced by `kctx index`

`kctx index` converts a monolithic corpus JSON (one file produced by the scraper
or research pipeline) into an exploded per-doc directory.
`src/context_cli/indexer.py` does the work in `index_doc(json_path, store_dir)`.

For a corpus named `exa`, indexing writes:

```
.king-context/docs/exa/
  index.json            doc metadata only
  sections/
    authentication.json one file per section, plus token_estimate
    websockets.json
    ...
  keywords.json         reverse index: keyword -> [section paths]
  use_cases.json        reverse index: use_case -> [section paths]
  tags.json             reverse index: tag -> [section paths]
```

Details from `indexer.py`:

- The doc directory is named after the corpus `name` field. Any prior index
  directory is wiped with `shutil.rmtree` before writing, so indexing is a clean
  rebuild, not a merge.
- `index.json` holds `name`, `display_name`, `version`, `base_url`,
  `section_count`, and an `indexed_at` UTC timestamp.
- Each `sections/<path>.json` carries `title`, `path`, `url`, `keywords`,
  `use_cases`, `tags`, `priority`, `content`, and a computed `token_estimate`.
- `token_estimate` uses the heuristic `int(len(text.split()) * 1.33)`, the same
  formula used everywhere in the package.
- The three reverse indexes map each metadata term to the list of section paths
  that carry it. These power the metadata search layer without scanning content.

`index_all(data_dir, store_dir)` indexes every `*.json` in a directory in sorted
order. See [corpus-schema.md](../reference/corpus-schema.md) for the input JSON
shape the indexer expects.

### Routing to docs vs research

`kctx index` accepts `[path]`, `--all`, and `--source {all,docs,research}`
(default `all`). The store is chosen per file by `_resolve_index_store` in
`cli.py`:

- `--source docs` or `--source research` forces the target store.
- `--source all` (the default) auto-detects: `_detect_source` reads the JSON and
  routes to the research store if any section has `"source_type": "research"`,
  otherwise to the docs store.
- `--all` indexes every `.king-context/data/*.json` plus
  `.king-context/data/research/*.json`, resolving each file's store
  individually.

Note that for `index`, the `all` choice means auto-detect, which is different
from how `list`, `search`, and `grep` use `all` to mean "both stores". The
`--source` help text describes the default as "auto-detect from source_type".

## Searcher scoring

`src/context_cli/searcher.py` implements metadata scoring over the reverse
indexes. There is no SQLite and no embeddings. `_normalize_query` lowercases,
strips, and splits the query into terms. `_score_sections_in_doc` then walks the
three reverse indexes and accumulates a per-section score:

| Match type | Comparison | Weight |
| --- | --- | --- |
| Keyword | `term == key.lower()` (exact) | 3 |
| Use case | `term in use_case.lower()` (substring) | 2 |
| Tag | `term == key.lower()` (exact) | 1 |

After accumulating the metadata score, each candidate section is loaded and its
priority is folded in:

```python
final_score = base_score + priority * 0.5
```

So a section with a keyword hit (3) and `priority: 10` scores `3 + 10 * 0.5 =
8.0`. Results are sorted by score descending and truncated to `top` (default
`5`). The function returns `SearchResult` dataclasses carrying `doc_name`,
`section_path`, `title`, `score`, `keywords`, `use_cases`, `tags`, `priority`,
and `source`.

`search(query, store_dir, doc_name=None, top=5, source="docs")` searches one
store. When `doc_name` is given it restricts to that doc (returning empty if the
doc has no `index.json`). Otherwise it scans every doc directory in the store,
skipping directories whose name starts with `_` and directories missing an
`index.json`.

## Multi-store model

Every query-facing command understands `--source {all,docs,research}` with
default `all`. `_active_stores(source)` in `cli.py` returns the target stores:

| `--source` | Stores searched |
| --- | --- |
| `docs` | `[("docs", STORE_DIR)]` |
| `research` | `[("research", RESEARCH_STORE_DIR)]` |
| `all` | both, docs first then research |

There are two access patterns layered on top of this:

### Fan-out and merge (`list`, `search`, `grep`)

These commands call into each active store, tag every result with its store
label via the `source` field, then merge. `_cmd_search` runs `search()` once per
store, extends a single list, re-sorts globally by score descending, and
truncates to `--top`. `_cmd_grep` does the same fan-out for matches. `_cmd_list`
renders one block per store. Because merging happens after per-store search, a
single ranked result set can mix docs and research, and the formatter prefixes
each line with `[docs]` or `[research]`.

### Single-store resolution (`read`, `topics`)

`read` and `topics` operate on exactly one section or one doc, so they must
resolve a single store. `_find_doc_store(doc_name, source)` looks for the doc's
`index.json` in each active store. If the same doc slug exists in more than one
store and `--source` is `all`, it raises `AmbiguousDocError`:

```python
raise AmbiguousDocError(
    f"Doc '{doc_name}' exists in multiple stores ({labels}). "
    "Re-run with --source docs or --source research."
)
```

The command boundary catches it, prints the message to stderr, and exits with
status `1`. The fix is to disambiguate with `--source docs` or
`--source research`. If the doc is not found in any active store, the command
also exits `1` with a "not found" message.

## Read with preview and fuzzy suggestions

`src/context_cli/reader.py` reads one section file and returns a
`SectionContent` dataclass (`title`, `content`, `url`, `token_estimate`,
`is_preview`). `read_section(doc_name, section_path, store_dir, preview=False)`
loads `<store>/<doc>/sections/<section_path>.json`.

- `token_estimate` always reflects the full section, taken from the stored value
  (falling back to the `words * 1.33` heuristic if absent).
- `--preview` truncates the content to the first 150 words and sets
  `is_preview=True` only when the content exceeds 150 words. Shorter sections are
  returned whole and are not flagged as previews. The full token estimate is
  still reported, so an agent can see the cost of the complete read before
  fetching it.

When the section file does not exist, `read_section` raises `FileNotFoundError`
whose message includes up to five "Did you mean" suggestions from
`suggest_similar`. That helper scans the section filenames in the doc's
`sections/` directory and ranks them: prefix matches (the query is a prefix of
the candidate or vice versa) rank above plain substring matches. `_cmd_read`
catches the error, prints it to stderr, and exits `1`.

## Topics

`topics <doc>` groups a doc's sections by tag. `_cmd_topics` resolves the doc to
a single store (with the same `AmbiguousDocError` behavior as `read`), reads the
doc's `tags.json`, and for each tag loads the referenced section files to build
groups of `title`, `path`, and `priority`. Sections within a tag are sorted by
priority descending. `--tag <tag>` narrows output to a single tag group (an
unknown tag yields an empty result). A doc with no `tags.json` returns "No topics
found."

## Grep

`src/context_cli/grep.py` runs line-level regex search over section content.
`grep_docs(pattern, store_dir, doc_name=None, context_lines=0, source="docs")`
compiles the pattern with `re.IGNORECASE` (search is always case-insensitive),
then iterates the section files of each in-scope doc, splits content on
newlines, and records a `GrepMatch` for every line that matches.

- Matches are grouped by section: matches within the same section are adjacent
  in the returned list.
- `--context N` includes up to `N` lines before and after each match
  (`context_before` / `context_after`).
- `--doc <name>` restricts to one doc; otherwise every non-underscore doc
  directory in the store is scanned.
- `_cmd_grep` fans out across active stores and tags each match with its store
  label.

Use `grep` when metadata search is too broad and you know the exact method name,
parameter, error code, or string.

## The nine subcommands

`_build_parser` in `cli.py` registers exactly nine top-level subcommands. `main()`
parses args and dispatches via `args.func`; with no subcommand it prints help.

| Subcommand | Purpose | Multi-store | `--json` |
| --- | --- | --- | --- |
| `list [source]` | List indexed corpora per store | yes (fan-out) | yes |
| `search <query>` | Metadata reverse-index scoring | yes (fan-out + merge) | yes |
| `read <doc> <section>` | Read one section, optional preview | yes (single-store) | yes |
| `grep <pattern>` | Line-level case-insensitive regex over content | yes (fan-out) | yes |
| `topics <doc>` | Group sections by tag | yes (single-store) | yes |
| `index [path]` | Build the flat store from corpus JSON | yes (routing) | no |
| `llm-doctor` | Probe configured LLM providers (Ollama, beta) | n/a | yes |
| `adr ...` | Architectural decision records | separate store | yes (per subcommand) |
| `ui` | Launch the local read-only web UI | n/a | n/a |

`search`, `read`, `grep`, and `topics` accept `--source`. `list` takes `source`
as an optional positional argument with the same choices. `index` uses
`--source` for store routing as described above.

`adr` is a substantial sub-application wired in via `adr.add_subparser`; it is
covered in [adr-workflow.md](../contributing/adr-workflow.md), and its store is
the decision index under `.king-context/decisions/project/`, separate from docs
and research. `llm-doctor` is described in [providers.md](providers.md). `ui` is
the one command that reaches outside the `context_cli` package: `_cmd_ui`
imports `king_context.web.server.main` and forwards `--port`, `--host`, and
`--no-open`, so it depends on the `king_context` web subtree being importable.
See [local-ui.md](local-ui.md).

## Output formatting

`src/context_cli/formatter.py` renders results as compact plain text or, with
`--json`, as JSON via `dataclasses.asdict`. Plain-text output is intentionally
terse and token-efficient for agent consumption: `list` is a column table,
`search` is a numbered list with score and the first use case, `read` is a
titled section with a `URL | Tokens | [PREVIEW]` footer, `topics` groups by tag,
and `grep` groups matches under `## [source] doc/section-title` headings with
`line_number: line_content`.

## Error handling and exit codes

The CLI uses a single non-zero exit code. Every aborting condition in `kctx`
(doc not found, ambiguous slug, missing section, missing index data, ADR
validation or parse failures) prints to stderr and calls `sys.exit(1)`. There
are no other exit codes in the `kctx` CLI.

Exit codes `2` (`ValueError`) and `3` (`ProviderUnavailableError`) exist only in
the scraper CLI at `src/king_context/scraper/cli.py`, not in `kctx`. See
[scraper-pipeline.md](scraper-pipeline.md).

## Conventions in this package

- Each command is a thin `_cmd_*(args)` handler wired with
  `parser.set_defaults(func=...)`.
- Results are modeled as dataclasses (`DocInfo`, `SearchResult`, `GrepMatch`,
  `SectionContent`, `IndexResult`) and serialized with `dataclasses.asdict`.
- Directory names starting with `_` are skipped when enumerating docs, in
  `store.py`, `searcher.py`, and `grep.py`.
- Diagnostic and error output goes to stdout/stderr via `print`; the
  `context_cli` package does not use the `logging` module. (By contrast,
  `src/llm_providers/logging.py` exists and is used by the provider layer, so do
  not assume print-only conventions across the whole repo: verify per package.)
- New code in this package uses PEP 604 unions (`str | None`), consistent with
  the function signatures here. The criterion across the repo is that new code
  uses `X | None` while legacy core modules keep `typing.Optional` for local
  consistency. See [code-style.md](../contributing/code-style.md).

## Related docs

- [overview.md](overview.md): how the stacks fit together
- [scraper-pipeline.md](scraper-pipeline.md): `king-scrape`, produces corpus JSON
- [research-pipeline.md](research-pipeline.md): `king-research`, produces corpus JSON
- [providers.md](providers.md): LLM provider configuration and `llm-doctor`
- [local-ui.md](local-ui.md): the `kctx ui` web server
- [mcp-legacy.md](mcp-legacy.md): the legacy MCP/SQLite stack
- [corpus-schema.md](../reference/corpus-schema.md): input JSON shape
- [storage-layout.md](../reference/storage-layout.md): full `.king-context/` map
- [env-vars.md](../reference/env-vars.md): environment variables
- [skills.md](../skills.md): Claude Code skills that drive `kctx`
