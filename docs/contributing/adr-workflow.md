# ADR workflow

King Context is a CLI-first, local-first retrieval layer for AI agents.
Architectural decisions are part of that retrieval surface: they are the
project's decision memory, stored as Architecture Decision Records (ADRs) under
`.king-context/adr/` and retrievable through the same `kctx` command agents use
for docs and research.

ADRs are managed only through the `kctx adr` CLI. The CLI enforces the file
shape, maintains the reciprocal link graph, and rebuilds the derived index. You
provide judgment about which decisions relate to or replace which; the CLI keeps
the structure honest.

## The two layers

| Layer | Location | Edited by | Role |
| --- | --- | --- | --- |
| ADR markdown | `.king-context/adr/NNNN-slug.md` | `kctx adr` commands | Human-readable source of truth |
| Decision index | `.king-context/decisions/project/` | `kctx adr index` (derived) | Search and graph cache |

The markdown files are the source of truth. The JSON under
`.king-context/decisions/project/` is a derived cache: never edit it by hand.
The retrieval commands (`list`, `search`, `read`, `timeline`) read the index,
not the markdown.

This ADR store lives in the `kctx` flat-file stack under `.king-context/`. It is
independent of the legacy MCP server (`server.py` plus the `docs.db`
SQLite/FTS5/embeddings layer): the two stacks do not share data. See
[ADR-0001](../../.king-context/adr/0001-adopt-cli-first-architecture-for-agent-retrieval.md)
and the [MCP legacy architecture](../architecture/mcp-legacy.md) for the split.

## Do not hand-edit the ADR directory

Do not create or edit markdown directly in `.king-context/adr/`. The supported
ways to get content into the store are:

- The `kctx adr new` flags, which build the file for you.
- Drafting a complete ADR markdown file *somewhere else* (for example a scratch
  file or `.docs/`) and importing it with `kctx adr new --from-file <path>`.

Both paths run the same parser (`_parse_adr_content` in
`src/context_cli/adr.py`), so a malformed draft is rejected before it ever lands
in the ADR directory. Hand-writing files under `.king-context/adr/` bypasses ID
assignment, filename derivation, reciprocal link updates, and the index
rebuild, which is exactly the state `kctx adr validate` and `kctx adr status`
exist to catch.

The two skills that drive this workflow, `king-record-decision` and
`king-decisions`, both state the same rule: discovery and creation happen
through `kctx adr` retrieval commands, not by scanning
`.king-context/adr/*.md`. See [Skills](../skills.md).

## The ten subcommands

All subcommands are defined in `src/context_cli/adr.py`. They split into
retrieval and maintenance.

Retrieval (reads the derived index):

| Command | Purpose |
| --- | --- |
| `kctx adr list` | List ADRs, active by default. |
| `kctx adr search <query>` | Score ADR metadata for a topic. |
| `kctx adr read <id-or-path>` | Print one decision, full or preview. |
| `kctx adr timeline <query>` | Group matched decisions by lifecycle state. |

Maintenance (writes markdown and rebuilds the index):

| Command | Purpose |
| --- | --- |
| `kctx adr new` | Create an ADR from flags or `--from-file`. |
| `kctx adr supersede <old> <new> --reason ...` | Mark one ADR superseded by another. |
| `kctx adr link <from> <to>` | Add a reciprocal `related` link. |
| `kctx adr index` | Rebuild the decision index from markdown. |
| `kctx adr status` | Check whether markdown and index are in sync. |
| `kctx adr validate` | Check fields, body sections, and graph state. |

`new`, `supersede`, and `link` call `rebuild_index()` themselves after writing
markdown, so you do not need a separate `kctx adr index` after them. You do need
`index` after manual merges or conflict resolution. Examples for every flag are
in the [CLI guide](../CLI_GUIDE.md#manage-architectural-decisions).

### list

```bash
kctx adr list           # active decisions only (default)
kctx adr list --all     # include superseded, deprecated, rejected, proposed
kctx adr list --json
```

`--active` is the default and is accepted explicitly. "Active" means status
`accepted` or `proposed` with no `superseded_by` entry (`_active` in
`src/context_cli/adr.py`).

### search

```bash
kctx adr search "cli first retrieval" --top 5
kctx adr search "scraper provider" --all
kctx adr search "agent retrieval" --json
```

Scoring is keyword-weighted, not full-text or vector. `_score_decision` ranks an
exact ID match highest, then path, then title and keywords, areas, use cases and
link targets, and tags, with a small priority bonus. Use technical nouns and area
names, not full sentences. The default top count is 5.

### read

```bash
kctx adr read ADR-0001 --preview
kctx adr read 0001-adopt-cli-first-architecture-for-agent-retrieval
kctx adr read ADR-0001 --json
```

`target` accepts either the ADR ID (`ADR-0001`, case-insensitive) or the indexed
path (the filename stem without `.md`). `--preview` returns the first ~150 words
and flags whether the body was truncated.

### timeline

```bash
kctx adr timeline "cli first agent retrieval"
kctx adr timeline "scraper provider" --json
```

Timeline pulls the topic's matches plus everything they supersede, are
superseded by, or relate to, then groups them: `Active`, `Superseded`,
`Deprecated/Rejected`, `Related`. It also surfaces the supersession reason when
one is recorded. Use it when both current guidance and history matter.

### new

Flag form (the CLI assembles the markdown):

```bash
kctx adr new \
  --title "Adopt CLI-first architecture for agent retrieval" \
  --status accepted \
  --date 2026-05-02 \
  --areas "cli,retrieval,agents,mcp,product-strategy" \
  --keywords "cli-first,agent-retrieval,context-budget,mcp" \
  --tags "architecture,product,retrieval,agents" \
  --context "..." \
  --decision "..." \
  --alternatives "..." \
  --consequences "..."
```

Required flags are `--title`, `--status`, `--areas`, `--keywords`, `--tags`,
`--context`, `--decision`, `--alternatives`, and `--consequences`
(`_create_adr_from_flags`). `--status` defaults to `accepted`. `--date` defaults
to today. `--supersedes` and `--related` take comma-separated ADR IDs;
`--supersedes` requires `--supersession-reason`. The ID is assigned
automatically as the next `ADR-NNNN`, and the filename is derived from the ID
number plus a slug of the title.

The `--from-file` flow is described in its own section below.

### supersede

```bash
kctx adr supersede ADR-0001 ADR-0002 \
  --reason "The old approach created unsafe deploy behavior."
```

Use this when both ADRs already exist. `--reason` is required. The command sets
the old ADR to `status: superseded` and adds the new ID to its `superseded_by`,
then adds the old ID to the new ADR's `supersedes` and writes
`supersession_reason` on the new ADR (`_supersede`). It rejects an ADR
superseding itself.

### link

```bash
kctx adr link ADR-0001 ADR-0004
kctx adr link ADR-0001 ADR-0004 --type related
```

Only `--type related` is supported. The link is reciprocal: both ADRs get the
other's ID in `related` (`_add_related`). An ADR cannot link to itself.

### index

```bash
kctx adr index
```

Rebuilds `.king-context/decisions/project/` from every `*.md` under
`.king-context/adr/`. See [Index artifacts](#index-artifacts) for what it
writes.

### status

```bash
kctx adr status
```

Compares markdown sources against the indexed JSON and reports drift: an ADR in
markdown but not the index, an ADR in the index but not markdown, a missing
index, or markdown that changed after it was indexed (detected by content hash
and mtime, `status_issues`). Exit is non-zero with a stale message that tells
you to run `kctx adr index`.

### validate

```bash
kctx adr validate
```

Runs the full structural and graph check (`validation_errors`), then appends the
`status` checks. It catches missing or malformed frontmatter, missing body
sections, filename/ID mismatch, duplicate IDs, links to nonexistent ADRs,
self-links, missing supersession reasons, and broken reciprocity (see
[The reciprocal link graph](#the-reciprocal-link-graph)). Exit is non-zero if
any error is found.

> Exit codes: `kctx` uses `sys.exit(1)` for every error path, including
> `adr status` and `adr validate` failures. The dedicated exit codes `2`
> (ValueError) and `3` (ProviderUnavailableError) exist only in the scraper CLI
> (`src/king_context/scraper/cli.py`), not in `kctx`.

## The `--from-file` flow

When a decision needs more nuance than flags comfortably carry, draft the full
ADR markdown in a scratch file, then import it. Run all three commands in order:

```bash
kctx adr new --from-file draft.md
kctx adr index
kctx adr validate
```

`new` already rebuilds the index, so the explicit `index` step is redundant
right after a single `new`. The reason to keep it in the workflow is that it is
the standard recovery step after any manual change, and running `index` then
`validate` together is the habit the skills enforce. The
`king-record-decision` skill prescribes exactly this sequence: write, then
`kctx adr index`, then `kctx adr validate`, then `kctx adr timeline "<topic>"`
to confirm the resulting state.

What `--from-file` does (`_create_adr_from_file`):

1. Reads the draft and parses its frontmatter.
2. If the draft has no `id`, assigns the next `ADR-NNNN` and rewrites the
   frontmatter with it. If it has an `id`, that ID is normalized and must not
   already exist.
3. Verifies every `supersedes` and `related` target already exists. Missing
   targets abort the import before anything is written.
4. Derives the filename from the ID number and the title slug, validates the
   full content through the same parser as flag-based creation, and only then
   writes the file.
5. Applies the supersession side effects: each superseded ADR gets
   `status: superseded` and the new ID in its `superseded_by`; each related ADR
   gets the reciprocal `related` link.

The `new` command then calls `rebuild_index()` (`cmd_new`), so the import and the
index rebuild happen in a single `kctx adr new --from-file` invocation.

Because the draft passes through the same `_parse_adr_content` parser, a draft
missing a required field or body section is rejected with a clear error rather
than landing half-formed in the ADR directory.

## Frontmatter and body

Every ADR is YAML frontmatter followed by a markdown body. Both are validated.

### Required frontmatter fields

These keys must all be present (`REQUIRED_FRONTMATTER`):

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | `ADR-NNNN`. Bare `NNNN` is normalized to `ADR-NNNN`. |
| `title` | string | Human-readable decision title. |
| `status` | string | One of `proposed`, `accepted`, `deprecated`, `superseded`, `rejected`. |
| `date` | string | `YYYY-MM-DD` (ISO date). |
| `areas` | list | Architecture areas, for example `cli`, `scraper`, `providers`. |
| `supersedes` | list | ADR IDs this decision replaces. May be `[]`. |
| `superseded_by` | list | ADR IDs that replaced this one. May be `[]`. |
| `related` | list | Non-supersession links. May be `[]`. |
| `keywords` | list | Search terms for `kctx adr search`. |
| `tags` | list | Categories. |

`supersession_reason` is optional in general but required whenever `supersedes`
is non-empty. Empty lists render as `[]`; populated lists render as YAML block
sequences (`_render_frontmatter`).

### Required body sections

The body must contain all of these headings, verbatim (`REQUIRED_SECTIONS`):

```markdown
## Context
## Decision
## Alternatives Considered
## Consequences
## Links
```

`render_adr_markdown` lays them out in this order under a top-level
`# ADR-NNNN: Title` heading. `## Links` may be empty.

### Example frontmatter

From `ADR-0009`:

```yaml
---
id: ADR-0009
title: Pluggable scraper provider abstraction for king-scrape
status: accepted
date: 2026-05-06
areas:
  - cli
  - scraper
  - providers
  - plugin-system
supersedes: []
superseded_by: []
related:
  - ADR-0001
  - ADR-0003
  - ADR-0010
  - ADR-0011
keywords:
  - scraper-provider
  - registry
  - stage-aware
  - soft-import
  - python-extras
  - entry-points
tags:
  - architecture
  - scraper
  - providers
---
```

ADR body content can be in Portuguese (the architecture-doc exception in the
project language rule); everything else in an ADR, including field names and
status values, stays English.

## The reciprocal link graph

The link graph is the part `kctx adr validate` is most strict about. Three list
fields define edges, and each edge must be reciprocal:

- `supersedes` (forward) pairs with `superseded_by` (back) on the other ADR.
- `superseded_by` (back) pairs with `supersedes` (forward) on the other ADR.
- `related` pairs with `related` on the other ADR.

`validate` enforces, among other checks (`validation_errors`):

- If `A.supersedes` lists `B`, then `B.superseded_by` must list `A`.
- If `A.superseded_by` lists `B`, then `B.supersedes` must list `A`.
- If `A.related` lists `B`, then `B.related` must list `A`.
- An ADR with `supersedes` set must carry a `supersession_reason`.
- An ADR with any `superseded_by` must have `status: superseded` and cannot be
  active.
- An ADR with `status: superseded` must have at least one `superseded_by`.
- No self-links and no direct supersession cycle (`A` supersedes `B` while `B`
  supersedes `A`).

The `supersede` and `link` commands write both sides of an edge for you, which
is why hand-editing markdown is the most common source of validation failures:
it is easy to write one side and forget the other.

## Index artifacts

`kctx adr index` (and the implicit rebuild after `new`, `supersede`, and `link`)
deletes and rebuilds `.king-context/decisions/project/` from the markdown
sources. `rebuild_index()` writes:

| Artifact | Contents |
| --- | --- |
| `index.json` | Corpus metadata: name, section count, `indexed_at` (UTC), source dir. |
| `sections/<path>.json` | One file per ADR: full parsed `Decision`, including content, source hash, and token estimate. |
| `keywords.json` | Reverse index from keyword, area, lowercased ID, and status to ADR paths. |
| `use_cases.json` | Reverse index from generated use-case strings to ADR paths. |
| `tags.json` | Reverse index from tag to ADR paths. |
| `graph.json` | `nodes` (id, title, status, active, path, date) and `edges` (`supersedes` and `related`). |
| `timeline.json` | Ordered decision items with full lifecycle metadata. |

Everything here is derived. If it drifts from the markdown, `kctx adr status`
reports it and the fix is always `kctx adr index`, never a manual edit. The
per-section JSON carries a `source_hash` (SHA-256 of the markdown) and
`source_mtime`, which is how `status` detects that an ADR changed after it was
last indexed.

## When to write an ADR

Write an ADR when a decision shapes the project's architecture or changes its
direction, and would otherwise be lost as tribal knowledge. Concretely:

- Adopting or replacing an architecture pattern (for example ADR-0001, adopting
  CLI-first architecture for agent retrieval).
- Introducing an abstraction or plugin boundary (for example ADR-0009, the
  pluggable scraper provider abstraction).
- Reversing or narrowing a prior decision (use `supersede`).
- Any choice a future contributor would reasonably ask "why is it done this
  way" about.

Routine bug fixes, refactors with no design tradeoff, and reversible
implementation details do not need an ADR.

## Check existing decisions first

Before proposing or recording a change, check whether the project has already
decided the question. The `king-record-decision` and `king-decisions` skills
make this a hard step, and the order is fixed:

```bash
kctx adr status                           # if stale, run: kctx adr index
kctx adr search "<topic>" --active --top 5
kctx adr read <ADR-ID> --preview          # or a full read
kctx adr timeline "<topic>"               # when history matters
```

Classify what you find:

- The new decision replaces an existing active ADR: use `--supersedes` with a
  concrete reason (or `kctx adr supersede` if both already exist).
- The existing ADR is relevant but still valid: link it with `--related`.
- The new decision appears to contradict an active ADR and the replacement is
  not explicit: stop and confirm with a human before writing.
- Nothing relevant exists: create an independent ADR.

Do this through the retrieval commands, not by reading
`.king-context/adr/*.md` directly. The index is what search and timeline see,
and it is what keeps the retrieval cheap.

## Working without the wrapper

In a development checkout the `.king-context/bin/kctx` wrapper may not exist. Run
the module directly:

```bash
python -m context_cli.cli adr status
python -m context_cli.cli adr validate
```

Installed projects use the wrapper at `.king-context/bin/kctx`.

## Related docs

- [CLI guide: manage architectural decisions](../CLI_GUIDE.md#manage-architectural-decisions)
- [Architecture overview](../architecture/overview.md)
- [CLI retrieval architecture](../architecture/cli-retrieval.md)
- [MCP legacy architecture](../architecture/mcp-legacy.md)
- [Storage layout](../reference/storage-layout.md)
- [Corpus schema](../reference/corpus-schema.md)
- [Skills](../skills.md)
- [Code style](./code-style.md)
- [Testing](./testing.md)
- [Commits and PRs](./commits-and-prs.md)
