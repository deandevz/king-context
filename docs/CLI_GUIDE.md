# King Context CLI guide

King Context is a CLI-first retrieval layer for AI agents. Use it to keep
documentation, research, code-adjacent knowledge, and architectural decisions
searchable without loading large files into the model context.

The CLI is the primary interface for agent workflows. MCP support can still be
useful as an integration layer, but new capabilities expose reliable CLI
primitives first.

## Command overview

King Context installs three command-line tools:

- `kctx`: search, read, index, and validate local retrieval stores.
- `king-scrape`: scrape a documentation site and export indexed sections.
- `king-research`: build and index a research corpus for a topic.

The `kctx` command searches two content stores by default:

- `docs`: product or API documentation under `.king-context/docs/`.
- `research`: open-web research corpora under `.king-context/research/`.

Architectural decisions use a separate ADR workflow:

- Human-readable ADR files live under `.king-context/adr/`.
- Derived decision indexes live under `.king-context/decisions/project/`.

## Recommended retrieval workflow

Use progressive disclosure. Start with cheap metadata, then read only the
smallest section that answers the question.

1. List available stores:

   ```bash
   kctx list
   ```

2. Search metadata:

   ```bash
   kctx search "authentication api key" --top 5
   ```

3. Preview the most likely section:

   ```bash
   kctx read exa authentication --preview
   ```

4. Read the full section only when the preview is relevant:

   ```bash
   kctx read exa authentication
   ```

For most agent tasks, stop after one preview or one full read. Use `kctx grep`
for exact strings, and use `kctx adr` for architectural decisions.

## Search indexed documentation and research

### List stores

Use `kctx list` to see indexed documentation and research corpora.

```bash
kctx list
kctx list docs
kctx list research
kctx list --json
```

Arguments and flags:

- `source`: optional. Use `all`, `docs`, or `research`. The default is `all`.
- `--json`: return machine-readable output.

When you list all stores with `--json`, the command returns an object with
`docs` and `research` arrays. When you filter to one source, it returns a flat
array.

### Search metadata

Use `kctx search` to search titles, keywords, use cases, tags, and priorities.
The command returns metadata only, not full content.

```bash
kctx search "websocket streaming audio"
kctx search "authentication" --doc exa --top 3
kctx search "chain of thought" --source research
kctx search "rate limits" --source docs --json
```

Flags:

- `--doc <name>`: restrict results to one indexed corpus.
- `--top N`: limit results. The default is `5`.
- `--source all|docs|research`: choose which store to search. The default is
  `all`.
- `--json`: return machine-readable output.

Use technical terms, API names, and short concepts. The searcher tokenizes the
query and scores exact keyword matches, use-case substring matches, tag
matches, and section priority.

### Read a section

Use `kctx read` after search returns a section path.

```bash
kctx read exa authentication --preview
kctx read exa authentication
kctx read prompt-engineering-techniques ai-prompt-engineering-patterns --source research
kctx read exa authentication --json
```

Arguments and flags:

- `doc`: indexed corpus name.
- `section`: section path without `.json`.
- `--preview`: return the first approximately 150 words and the full token
  estimate.
- `--source all|docs|research`: disambiguate a corpus that exists in both
  stores. The default is `all`.
- `--json`: return machine-readable output.

If the section path doesn't exist, `kctx read` suggests up to five similar
paths.

### Browse topics

Use `kctx topics` to inspect tags inside one corpus.

```bash
kctx topics exa
kctx topics exa --tag authentication
kctx topics prompt-engineering-techniques --source research --json
```

Flags:

- `--tag <tag>`: show one tag group.
- `--source all|docs|research`: choose the store. The default is `all`.
- `--json`: return machine-readable output.

### Search exact content

Use `kctx grep` when you know the exact method, parameter, error code, or text
pattern.

```bash
kctx grep "Authorization" --doc exa
kctx grep "WebSocket" --source docs --context 3
kctx grep "Error 429" --json
```

Flags:

- `--doc <name>`: restrict results to one corpus.
- `--context N`: include surrounding lines.
- `--source all|docs|research`: choose the store. The default is `all`.
- `--json`: return machine-readable output.

## Index JSON exports

Use `kctx index` to build the file-based retrieval store from exported JSON.

```bash
kctx index .king-context/data/stripe.json
kctx index .king-context/data/research/prompt-engineering-techniques.json
kctx index .king-context/data/research/prompt-engineering-techniques.json --source research
kctx index --all
```

Flags:

- `--all`: index `.king-context/data/*.json` and
  `.king-context/data/research/*.json`.
- `--source all|docs|research`: force the target store. The default is `all`,
  which auto-detects research JSON when a section has
  `"source_type": "research"`.

The indexer writes one directory per corpus and builds reverse indexes for
keywords, use cases, and tags.

## Manage architectural decisions

Use `kctx adr` to record and retrieve architectural decision records. ADRs are
human-readable Markdown files, and the JSON decision index is a derived cache.
Don't edit `.king-context/decisions/` directly.

Allowed ADR statuses are:

- `proposed`
- `accepted`
- `deprecated`
- `superseded`
- `rejected`

Accepted and proposed ADRs are active unless another ADR supersedes them.
ADR-specific search commands show active decisions by default.

### List decisions

```bash
kctx adr list
kctx adr list --all
kctx adr list --json
```

Flags:

- `--active`: show active decisions. This is the default behavior.
- `--all`: include superseded, deprecated, rejected, and proposed decisions.
- `--json`: return machine-readable output.

### Search decisions

```bash
kctx adr search "cli first retrieval" --top 5
kctx adr search "mcp context budget" --all
kctx adr search "agent retrieval" --json
```

Flags:

- `--active`: show active decisions. This is the default behavior.
- `--all`: include inactive historical decisions.
- `--top N`: limit results. The default is `5`.
- `--json`: return machine-readable output.

Search results include the ADR ID, status, active state, path, score, and
supersession metadata.

### Read a decision

```bash
kctx adr read ADR-0001 --preview
kctx adr read 0001-adopt-cli-first-architecture-for-agent-retrieval
kctx adr read ADR-0001 --json
```

Arguments and flags:

- `target`: ADR ID or indexed path.
- `--preview`: return the first approximately 150 words.
- `--json`: return machine-readable output.

### Show a decision timeline

Use `kctx adr timeline` when current guidance and history both matter.

```bash
kctx adr timeline "cli first agent retrieval"
kctx adr timeline "job coordination" --json
```

The timeline groups results into active, superseded, deprecated or rejected,
and related decisions. It also shows supersession reasons when they exist.

### Create a decision

Use `kctx adr new` after searching for related decisions. The CLI enforces the
ADR structure; the agent or author decides which decisions are related or
superseded.

```bash
kctx adr new \
  --title "Adopt CLI-first architecture for agent retrieval" \
  --status accepted \
  --date 2026-05-02 \
  --areas "cli,retrieval,agents,mcp,product-strategy" \
  --keywords "cli-first,agent-retrieval,context-budget,mcp" \
  --tags "architecture,product,retrieval,agents" \
  --context "The CLI gives agents fast, explicit retrieval primitives." \
  --decision "Design future King Context capabilities CLI-first." \
  --alternatives "MCP-first and strict CLI/MCP parity were considered." \
  --consequences "Expose CLI primitives first and add MCP support later when needed."
```

You can also create an ADR from a complete Markdown draft:

```bash
kctx adr new --from-file draft.md
```

When `--supersedes` is present, include `--supersession-reason`. The command
updates the superseded ADR and rebuilds the decision index.

### Supersede a decision

Use `kctx adr supersede` when both ADRs already exist.

```bash
kctx adr supersede ADR-0001 ADR-0002 \
  --reason "The old approach created unsafe deploy behavior."
```

The command updates the old ADR with `status: superseded` and
`superseded_by`, updates the new ADR with `supersedes` and
`supersession_reason`, and rebuilds the index.

### Link related decisions

Use `kctx adr link` for a non-supersession relationship.

```bash
kctx adr link ADR-0001 ADR-0004
kctx adr link ADR-0001 ADR-0004 --type related
```

The MVP supports only `related` links. Links are reciprocal.

### Rebuild, check, and validate decisions

Use these commands after manual edits, merges, or conflict resolution:

```bash
kctx adr index
kctx adr status
kctx adr validate
```

- `kctx adr index` rebuilds `.king-context/decisions/project` from
  `.king-context/adr`.
- `kctx adr status` checks whether Markdown sources and indexed JSON are in
  sync.
- `kctx adr validate` checks required fields, body sections, links,
  reciprocal supersession state, related links, and stale status metadata.

## Scrape documentation

Use `king-scrape` to turn a documentation site into a King Context JSON export.

```bash
king-scrape https://docs.example.com --name example --yes
```

The scraper pipeline runs these steps:

1. Discover URLs.
2. Filter relevant URLs.
3. Fetch pages.
4. Chunk content.
5. Enrich chunks with metadata.
6. Export JSON.

Useful flags:

- `--name <name>`: set the corpus name.
- `--display-name <name>`: set the display name.
- `--step discover|filter|fetch|chunk|enrich|export`: resume from a step.
- `--stop-after discover|filter|fetch|chunk|enrich|export`: stop after a step.
- `--model <model>`: choose the enrichment model.
- `--chunk-max-tokens N`: set the maximum chunk size. The default is `800`.
- `--chunk-min-tokens N`: set the minimum chunk size before merging. The
  default is `50`.
- `--concurrency N`: set concurrent fetch requests. The default is `5`.
- `--no-llm-filter`: disable LLM fallback in URL filtering.
- `--no-auto-seed`: skip database seeding after export.
- `--include-maybe`: fetch URLs classified as `maybe`.
- `--yes`: skip interactive confirmation prompts.

`king-scrape` writes exported documentation JSON to `.king-context/data/`.
Use `kctx index` to build or rebuild the file-based CLI store from that JSON.

## Build research corpora

Use `king-research` to research a topic from the open web and index the result
into the `research` store.

```bash
king-research "retrieval augmented generation for coding agents" --medium --yes
king-research "prompt engineering techniques" --basic --name prompt-engineering
king-research "agent memory systems" --high --no-auto-index
```

Effort flags:

- `--basic`: fewer queries and no deepening iterations.
- `--medium`: default effort.
- `--high`: more queries and deepening iterations.
- `--extrahigh`: maximum query and deepening budget.

Workflow flags:

- `--name <slug>`: override the output slug.
- `--step <step>`: start the research pipeline from a step.
- `--stop-after <step>`: stop after a step.
- `--yes`: skip the enrichment cost prompt.
- `--no-auto-index`: export JSON without indexing it into
  `.king-context/research/`.
- `--no-filter`: accepted as a no-op in the current P1 implementation.
- `--force`: accepted as a no-op in the current P3 implementation.

Research exports include `"source_type": "research"` in their sections, so
`kctx index` can route them to the research store automatically.

## Agent usage patterns

### Use docs for implementation details

```bash
kctx search "authentication api key" --doc exa --top 3
kctx read exa authentication --preview
kctx read exa authentication
```

Use this pattern when you need current API behavior, setup steps, parameters,
or examples from indexed documentation.

### Use research for broader questions

```bash
kctx search "tree of thoughts" --source research --top 5
kctx read prompt-engineering-techniques tree-of-thoughts --source research --preview
```

Use this pattern when the answer depends on synthesized web research rather
than one product's documentation.

### Use ADRs for project direction

```bash
kctx adr status
kctx adr search "cli first retrieval" --active --top 5
kctx adr read ADR-0001 --preview
```

Use this pattern before changing architecture, adding new surfaces, or making a
decision that could conflict with existing project guidance.

### Use grep for exact symbols

```bash
kctx grep "class Client" --source docs
kctx grep "Error 429" --context 3
```

Use this pattern when metadata search is too broad and you know the exact text.

## JSON output

Use `--json` when another script or agent needs structured output.

```bash
kctx list --json
kctx search "authentication" --json
kctx read exa authentication --json
kctx adr search "cli first" --json
```

The exact JSON shape depends on the command:

- Search commands return ranked result objects.
- Read commands return the selected content and metadata.
- List commands return indexed corpus or ADR metadata.
- ADR timeline returns grouped decision history.

## Troubleshooting

### The wrapper command doesn't exist

If `.king-context/bin/kctx` isn't present in a development checkout, run the
Python module directly:

```bash
python -m context_cli.cli --help
python -m context_cli.cli adr status
```

Installed projects use the wrapper commands in `.king-context/bin/`.

### A doc exists in both stores

If a corpus name exists in both `docs` and `research`, add `--source docs` or
`--source research` to `kctx read` and `kctx topics`.

### Search returns no results

Try shorter, keyword-based queries. Use technical nouns, API names, tags, and
error codes instead of full natural-language questions.

### ADR status is stale

Run:

```bash
kctx adr index
kctx adr validate
```

If validation fails, fix the Markdown source under `.king-context/adr/`, then
rebuild the index. Don't edit `.king-context/decisions/` directly.
