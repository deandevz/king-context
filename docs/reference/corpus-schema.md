# Corpus JSON schema

King Context is a CLI-first, local-first retrieval layer for AI agents. A
corpus is a single JSON file that holds one documentation source (a scraped
docs site) or one research topic. Both `king-scrape` and `king-research` write
this shape, and `kctx index` turns it into the flat-file store that the
retrieval layer searches.

This page is the canonical schema reference for contributors submitting corpus
packages by hand. Every field below is grounded in the code that produces or
consumes it.

## Where corpus files live

Raw corpus JSON files are written under `.king-context/data/`:

- `.king-context/data/<name>.json` for scraped documentation
  (`src/king_context/scraper/export.py`).
- `.king-context/data/research/<slug>.json` for research corpora
  (`src/king_context/research/export.py`, `RESEARCH_DATA_DIR`).

These raw files are the intake format. They are not what the retrieval layer
reads directly. You index them into the flat store with:

```bash
kctx index .king-context/data/<name>.json   # index one file
kctx index --all                            # index every data/*.json and data/research/*.json
```

`kctx index` routes the corpus to a store based on `source_type` (see
[Research corpus differences](#research-corpus-differences)) or an explicit
`--source docs|research` flag, then calls `index_doc`
(`src/context_cli/indexer.py`) to expand the JSON into
`.king-context/docs/<name>/` or `.king-context/research/<slug>/`.

> The MCP server stack (`server.py` + `db.py`, SQLite/FTS5/embeddings) consumes
> the same JSON shape through `seed_data.seed_one`, but it is the legacy
> secondary stack per ADR-0001. The two stacks do not share data. This page
> describes the schema as the canonical `kctx` flat-file stack reads it.

## Top-level fields

```json
{
  "name": "httpx",
  "display_name": "HTTPX",
  "version": "v1",
  "base_url": "https://www.python-httpx.org",
  "sections": [ /* ... */ ]
}
```

| Field          | Type           | Required | Notes |
|----------------|----------------|----------|-------|
| `name`         | string         | yes      | Corpus identifier. Used as the directory name in the store and as the doc name in search results. `index_doc` reads `data["name"]` with no default, so a missing `name` is a hard error. For docs this is the doc slug, for research it is the topic slug. |
| `display_name` | string         | no       | Human-readable label. Defaults to `name` when absent (`indexer.py`). |
| `version`      | string         | no       | Free-form version label. Defaults to `"v1"` from both exporters. Stored in `index.json`, not used for scoring. |
| `base_url`     | string         | no       | Base URL of the source site. Empty string for research corpora that have no single origin. Stored in `index.json`. |
| `sections`     | array<section> | yes      | The content. An empty array indexes a corpus with zero sections. |

`kctx index` only persists `name`, `display_name`, `version`, `base_url`, and a
derived `section_count` and `indexed_at` into the per-corpus `index.json`. Any
other top-level key (including `_meta`, below) is read by the scraper's own
audit and update tooling but is not copied into the flat store.

## Per-section fields

Every section, regardless of source, has the same core shape
(`src/king_context/scraper/export.py`, mirrored by `EnrichedChunk` in
`src/king_context/scraper/enrich.py`):

```json
{
  "title": "Authentication",
  "path": "advanced-authentication",
  "url": "https://www.python-httpx.org/advanced/authentication",
  "keywords": ["auth", "basic auth", "bearer token", "DigestAuth"],
  "use_cases": ["Use when sending credentials with a request", "Configure when an API requires a bearer token"],
  "tags": ["authentication", "security"],
  "priority": 8,
  "content": "Markdown content..."
}
```

| Field       | Type          | Required | Notes |
|-------------|---------------|----------|-------|
| `title`     | string        | no       | Section heading. Defaults to `""` in the store if absent. |
| `path`      | string        | yes      | Section slug, unique within the corpus. Becomes the section filename `<path>.json` and the key in every reverse index. Slashes are replaced with `-` at export time (`_sanitize_path`) to keep sections as flat files. This is the value you pass to `kctx read <name> <path>`. |
| `url`       | string        | no       | Canonical source URL for the section. Defaults to `""`. Carried through to results so an agent can cite the upstream page. |
| `keywords`  | array<string> | no       | Specific, searchable terms. The strongest retrieval signal (see weights below). Defaults to `[]`. |
| `use_cases` | array<string> | no       | Practical "Use when / Configure when" scenarios. Matched as substrings, so they cast a wider net than keywords. Defaults to `[]`. |
| `tags`      | array<string> | no       | Broad category labels. The weakest exact-match signal. Defaults to `[]`. |
| `priority`  | integer       | no       | Importance, 1 to 10 (10 = core feature, 1 = edge case). Defaults to `0`. Acts as a tie-breaker boost on score. |
| `content`   | string        | no       | The Markdown body returned by `kctx read`. Defaults to `""`. The indexer also computes a `token_estimate` from it (`len(content.split()) * 1.33`). |

### How each metadata field affects retrieval

`kctx search` scores sections by matching query terms against three reverse
indexes (`keywords.json`, `use_cases.json`, `tags.json`) built by the indexer.
The scoring lives in `src/context_cli/searcher.py`:

| Field       | Match rule                         | Weight per hit |
|-------------|------------------------------------|----------------|
| `keywords`  | query term equals keyword (exact, case-insensitive) | `+3.0` |
| `use_cases` | query term is a substring of a use case (case-insensitive) | `+2.0` |
| `tags`      | query term equals tag (exact, case-insensitive)    | `+1.0` |

After the term matches accumulate, `priority` adds a final boost:

```text
final_score = base_score + priority * 0.5
```

So a section keyworded for the query and marked `priority: 10` carries an extra
`+5.0` over the same match at `priority: 0`. Results are sorted by
`final_score` descending and truncated to `--top`. This is why high-quality
`keywords` and accurate `priority` values matter most when you author a corpus
by hand: a section with empty metadata is effectively invisible to search even
if its `content` is perfect, because there is no full-text scan in the `kctx`
stack.

## The optional `_meta` provenance block

ADR-0012 added a provenance block so the corpus can support drift detection
(`king-scrape audit`) and incremental refresh (`king-scrape update`). All
`_meta` fields are optional. Consumers that do not recognize them ignore them,
so corpora authored before ADR-0012 and hand-written corpora without `_meta`
keep working with no migration.

`_meta` appears in two places, both written by
`export_to_json` in `src/king_context/scraper/export.py`.

### Top-level `_meta`

```json
"_meta": {
  "schema_version": 1,
  "scraper_version": "0.1.0",
  "scraped_at": "2026-05-07T20:05:17.197727+00:00",
  "source_url": "https://hono.dev/docs",
  "section_count": 695
}
```

| Field            | Type    | Notes |
|------------------|---------|-------|
| `schema_version` | integer | Corpus schema version. `CORPUS_SCHEMA_VERSION = 1` in `export.py`. |
| `scraper_version`| string  | Installed `king-context` package version, or `"unknown"` if the distribution metadata is not found. |
| `scraped_at`     | string  | UTC ISO 8601 timestamp of the export (`datetime.now(timezone.utc).isoformat()`). |
| `source_url`     | string  | Origin used for re-fetching. `king-scrape update` resolves the corpus source from `_meta.source_url`, falling back to `base_url` (`src/king_context/scraper/update.py`, `_resolve_source_url`). |
| `section_count`  | integer | Number of sections at export time. |

### Per-section `_meta`

```json
"_meta": {
  "content_hash": "51c11eb244bd6d0be66af27c20c7e45972a5aec9c1df6200655341ecfba51920"
}
```

| Field          | Type   | Notes |
|----------------|--------|-------|
| `content_hash` | string | `sha256` of the section `content`, computed in `Chunk.__post_init__` (`src/king_context/scraper/chunk.py`) and carried through `EnrichedChunk`. |

The hash is the data dependency that drift detection and incremental refresh
build on. `king-scrape update` reads `section["_meta"]["content_hash"]` to
decide which sections can be reused for free and which need a fresh enrichment
LLM call (`update.py`). `king-scrape update` hard-refuses a corpus that has no
top-level `_meta` block, so if you author a corpus by hand and want it to be
refreshable, include `_meta` with at least `source_url`.

> Note: `kctx index` does not copy `_meta` into the flat store. The section
> files under `.king-context/docs/<name>/sections/` carry `title`, `path`,
> `url`, `keywords`, `use_cases`, `tags`, `priority`, `content`, and a derived
> `token_estimate` only. `_meta` lives in the raw `.king-context/data/` JSON,
> which is where the scraper's audit and update tooling reads it.

## Research corpus differences

`king-research` reuses `export_to_json` and then adds research-specific fields
per section before writing to `.king-context/data/research/<slug>.json`
(`src/king_context/research/export.py`, `_apply_research_fields`).

The defining marker is `source_type`. `kctx index` uses it to auto-route the
corpus into the research store rather than the docs store.

| Field                 | Type          | Notes |
|-----------------------|---------------|-------|
| `source_type`         | string        | Always set to `"research"` on every research section. This is the routing signal for `kctx index`. |
| `authors`             | array<string> | Optional. Parsed from the source author string, splitting on commas. Omitted when the source has no author. |
| `published_date`      | string        | Optional. Source publish date, copied verbatim from the upstream source (for example `"2026-03-21T00:00:00.000Z"`). Omitted when absent. |
| `domain`              | string        | Hostname of the source URL (for example `"pr-peri.github.io"`). |
| `discovery_iteration` | integer       | Which research deepening pass surfaced this source (`0` for the first pass). |

These fields are added only when a matching source is found by URL; a section
whose URL has no source entry still gets `source_type: "research"` but none of
the optional provenance fields. Research corpora typically have an empty
`base_url` and no top-level `_meta` block, because the research exporter writes
the JSON itself rather than going through the scraper's `save_and_index` path.
The core section shape (`title`, `path`, `url`, `keywords`, `use_cases`,
`tags`, `priority`, `content`) and the search scoring are identical to docs.

## Complete annotated example

A documentation corpus with full provenance. Comments are annotations only;
JSON does not allow comments, so strip them before saving.

```jsonc
{
  "name": "httpx",                       // corpus id, becomes the store directory
  "display_name": "HTTPX",               // human label
  "version": "v1",                       // free-form version tag
  "base_url": "https://www.python-httpx.org",

  "sections": [
    {
      "title": "Authentication",
      "path": "advanced-authentication", // unique slug, no slashes; used by `kctx read`
      "url": "https://www.python-httpx.org/advanced/authentication",

      "keywords": ["auth", "basic auth", "bearer token", "DigestAuth"], // +3.0 each, exact match
      "use_cases": [                     // +2.0 each, substring match
        "Use when sending credentials with a request",
        "Configure when an API requires a bearer token"
      ],
      "tags": ["authentication", "security"], // +1.0 each, exact match
      "priority": 8,                     // adds +4.0 (8 * 0.5) to score

      "content": "# Authentication\n\nHTTPX supports ...",

      "_meta": {                         // optional, ADR-0012
        "content_hash": "51c11eb244bd6d0be66af27c20c7e45972a5aec9c1df6200655341ecfba51920"
      }
    }
  ],

  "_meta": {                             // optional top-level provenance, ADR-0012
    "schema_version": 1,
    "scraper_version": "0.1.0",
    "scraped_at": "2026-05-07T20:05:17.197727+00:00",
    "source_url": "https://www.python-httpx.org",
    "section_count": 1
  }
}
```

Minimal hand-authored corpus (no provenance, indexes and searches fine):

```json
{
  "name": "my-notes",
  "display_name": "My Notes",
  "version": "v1",
  "base_url": "",
  "sections": [
    {
      "title": "Deploy checklist",
      "path": "deploy-checklist",
      "url": "",
      "keywords": ["deploy", "release", "checklist"],
      "use_cases": ["Use when shipping a release"],
      "tags": ["ops"],
      "priority": 5,
      "content": "1. Run tests\n2. Tag the release\n3. ..."
    }
  ]
}
```

Save either file under `.king-context/data/`, then run `kctx index <path>` to
make it searchable.

## See also

- [Storage layout](storage-layout.md): what the flat store looks like after `kctx index`.
- [Environment variables](env-vars.md): provider keys used by enrichment and research.
- [CLI retrieval](../architecture/cli-retrieval.md): how `kctx search` and `kctx read` use this schema.
- [Scraper pipeline](../architecture/scraper-pipeline.md): how `king-scrape` produces docs corpora.
- [Research pipeline](../architecture/research-pipeline.md): how `king-research` produces research corpora.
- [MCP legacy stack](../architecture/mcp-legacy.md): how the secondary SQLite/FTS5 stack consumes the same JSON.
