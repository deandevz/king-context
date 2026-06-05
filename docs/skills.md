# Claude Code skills

King Context is a CLI-first, local-first retrieval layer for AI agents. It ships
five Claude Code skills that teach an agent how to drive the CLI: when to reach
for each command, how to scope retrieval, and which constraints to honor so the
agent never corrupts a store or hallucinates metadata.

The skills are not code. They are instruction files (`skill.md`) that Claude
Code loads when a trigger phrase matches. They orchestrate the three CLI
wrappers under `.king-context/bin/`:

- `.king-context/bin/kctx`: search, read, index, and manage decision records.
- `.king-context/bin/king-scrape`: scrape a docs site into an indexed corpus.
- `.king-context/bin/king-research`: build a research corpus from the open web.

All five skills target the canonical kctx flat-file stack under
`.king-context/`, not the legacy MCP server. See
[architecture/overview.md](architecture/overview.md) for how the two stacks
relate, and [architecture/mcp-legacy.md](architecture/mcp-legacy.md) for the
secondary stack the skills deliberately avoid.

## How skills get installed

Skills live in the installer as templates under
`installer/templates/skills/<skill>/skill.md`. The npm package
`@king-context/cli` copies them into a host project on `init` and `update`:

```bash
npx @king-context/cli init      # installs skills into .claude/skills/
npx @king-context/cli update    # overwrites skills with the latest templates
```

`installSkills()` in `installer/lib/skills.js` copies the entire
`templates/skills/` tree into the host project's `.claude/skills/`, recursively,
and it **always overwrites**. Both `installer/lib/init.js` and
`installer/lib/update.js` call it. Local edits to an installed skill do not
survive an `update`. To change skill behavior permanently, edit the template in
`installer/templates/skills/` and ship a new package version.

`init` also writes a permission allowlist into `.claude/settings.local.json`
(via `mergeSettings()` in the same file) so the agent can run the wrappers
without prompting:

```
Bash(.king-context/bin/kctx *)
Bash(.king-context/bin/king-scrape *)
Bash(.king-context/bin/king-research *)
```

The wrappers themselves are scaffolded by `installer/lib/scaffold.js`, which
writes `.king-context/bin/{kctx,king-scrape,king-research}` shell scripts that
exec the project venv at `.king-context/core/venv/` against the modules
`context_cli.cli`, `king_context.scraper.cli`, and `king_context.research.cli`.
See [reference/storage-layout.md](reference/storage-layout.md) for the full
`.king-context/` tree and [reference/env-vars.md](reference/env-vars.md) for the
API keys the scraping and research skills need.

## The repo's own skill copies

This repository also keeps copies of the skills under `.claude/skills/`. These
are the skills Claude Code uses **when working on King Context itself**, and
they are intentionally not byte-identical to the templates.

The difference is the command prefix. Template skills call the wrapper by its
full path, `.king-context/bin/kctx`, because in a host project that is where the
CLI lives. The repo's own `king-context` skill calls **bare `kctx`**, because a
developer working in this repo has the console script on `PATH` via
`pip install -e .`. For example, the repo copy of the search skill opens with
"using `kctx`" while the template opens with "using `.king-context/bin/kctx`".
Same workflow, different invocation surface. Do not "fix" this drift: each copy
is correct for its environment.

---

## king-context

**Trigger / purpose.** Documentation and research lookup. Fires on phrases like
"search docs", "find in docs", "how to use X", "what's the API for X", and "what
does our research say about X". Its job is to find the right section in three
calls or fewer while spending the minimum number of tokens.

**Commands it drives.** All `kctx` retrieval verbs:

```bash
kctx list [docs|research] [--json]
kctx search "query" [--doc <name>] [--source docs|research] [--top N] [--json]
kctx read <doc> <section-path> [--preview] [--source ...] [--json]
kctx topics <doc> [--tag <tag>] [--json]
kctx grep "pattern" [--doc <name>] [--source ...] [--context N] [--json]
kctx index <path> [--source research] | kctx index --all
```

(The template prefixes each with `.king-context/bin/`.)

**Key constraints it enforces.**

- Check `.king-context/_learned/<doc>.md` first. A learned shortcut costs about
  100 tokens and can skip the whole search.
- Scope aggressively: `--doc <name>` beats `--source <store>` beats no filter.
- Prefer `search` (metadata, cheap) over `grep` (content scan). Use `grep` only
  for exact code patterns, API names, or error strings.
- Preview before a full read. Assess relevance before paying full token cost.
- Never read all sections. Search narrows, preview confirms, then read only what
  is needed.
- After a successful find, save a shortcut to `.king-context/_learned/<doc>.md`
  for future sessions, recording which store the doc lives in.

Both stores are searched by default and every hit is tagged `[docs]` or
`[research]`. Details of the retrieval engine are in
[architecture/cli-retrieval.md](architecture/cli-retrieval.md).

---

## scraper-workflow

**Trigger / purpose.** Scraping a documentation site into an indexed corpus.
Fires on "scrape", "scrape docs", "index docs from", "crawl docs", "get
documentation for", "I want the docs for X". It orchestrates the full pipeline:
discover, filter, fetch, chunk, enrich, export, index.

**Commands it drives.** `king-scrape` for the pipeline and `kctx index` for the
final indexing step. It runs two workflows:

- **Workflow A (OpenRouter):** fully automated. One command does discover
  through export, then index:

  ```bash
  .king-context/bin/king-scrape <base_url> --name <name> --yes
  .king-context/bin/kctx index .king-context/data/<name>.json
  ```

- **Workflow B (Claude Code sub-agents):** runs fetch and chunk via
  `king-scrape`, enriches with Haiku sub-agents, then exports and indexes:

  ```bash
  .king-context/bin/king-scrape <base_url> --name <name> --no-llm-filter --stop-after chunk
  # sub-agents enrich batches, writing checkpoints to enriched/batch_NNNN.json
  .king-context/bin/king-scrape <base_url> --name <name> --step export --no-auto-seed
  .king-context/bin/kctx index .king-context/data/<name>.json
  ```

The skill picks the workflow from the user, defaulting to Workflow A when
`OPENROUTER_API_KEY` is present and suggesting Workflow B otherwise.

**Key constraints it enforces.**

- **The orchestrator never generates enrichment metadata.** Only sub-agents
  produce `keywords`, `use_cases`, `tags`, and `priority`. Filling them in by
  hand is hallucination. If a sub-agent fails, retry or skip, never fabricate.
- **Index with `kctx index`, never `seed_data`.** The skill explicitly forbids
  `seed_data` and `python -m king_context.seed_data`, because those seed the
  legacy MCP database, which does not share data with the kctx store. This is
  the load-bearing rule that keeps the scraper output in the canonical stack.
- **Always pass `--name <name>`** to every `king-scrape` call, or the export
  generates a generic name.
- **Always use `--stop-after chunk`** in Workflow B so `king-scrape` does not run
  enrichment that the sub-agents are meant to handle.
- **Use `--no-auto-seed` on the export step** to prevent auto-indexing into the
  legacy MCP database.
- After each sub-agent returns, save a checkpoint to
  `.king-context/_temp/<domain>/enriched/batch_NNNN.json`. The export step reads
  these files.

The full pipeline mechanics are in
[architecture/scraper-pipeline.md](architecture/scraper-pipeline.md). The
enriched JSON shape is in [reference/corpus-schema.md](reference/corpus-schema.md).

---

## king-research

**Trigger / purpose.** Building a research corpus on an open-web topic. Fires on
"/king-research", "research about X", "pesquise sobre Y", "build a corpus on W",
"find sources about Q", "state of the art for R". It extracts a concise topic,
picks an effort mode, and runs the research pipeline.

**Commands it drives.** `king-research` end to end:

```bash
.king-context/bin/king-research "<topic>" --<mode> --yes
```

Effort modes map to query count and deepening iterations:

| Mode | Initial queries | Deepening iterations |
|---|---|---|
| `--basic` | 3 | 0 |
| `--medium` (default) | 5 | 1 |
| `--high` | 8 | 2 |
| `--extrahigh` | 12 | 3 |

The pipeline stages are `generate → search → chunk → enrich → export`, and the
output auto-indexes into `.king-context/research/<slug>/` unless
`--no-auto-index` is passed.

**Key constraints it enforces.**

- Pass `--yes` by default. The user invoked the skill to do the work, not to be
  interrupted by the enrichment cost prompt.
- Ask one clarifying question ("What topic?") only when the topic is vague.
- For `--high` and `--extrahigh`, warn about the expected time before running,
  but do not ask permission.
- Hand off to scraper-workflow when the user names a specific product or doc URL:
  that is a docs site, not an open-web research topic.
- Requires both `EXA_API_KEY` (source retrieval) and `OPENROUTER_API_KEY`
  (query generation plus enrichment). See
  [reference/env-vars.md](reference/env-vars.md).

The research pipeline internals are in
[architecture/research-pipeline.md](architecture/research-pipeline.md).

---

## king-decisions

**Trigger / purpose.** Retrieving project architectural decision records (ADRs).
Fires when the user asks why the project uses something, whether a decision
already exists, what the current architecture decision is, what changed
historically, or whether a planned change conflicts with a prior decision. It is
the read side of the ADR workflow.

**Commands it drives.** The `kctx adr` retrieval subcommands:

```bash
.king-context/bin/kctx adr status                          # check index sync state
.king-context/bin/kctx adr index                           # rebuild index if stale
.king-context/bin/kctx adr search "<topic>" --active --top 5
.king-context/bin/kctx adr read <ADR-ID> [--preview]
.king-context/bin/kctx adr timeline "<topic>"
```

**Key constraints it enforces.**

- Never read `.king-context/adr/*.md` directly for retrieval. Discovery happens
  only through `kctx adr` commands, which read the derived decision index.
- Start with `adr status`; if the index is stale, run `adr index` before
  searching.
- Prefer active ADRs for current guidance. Use `timeline` when the user asks why
  something changed or when an active result supersedes an older decision.
- If no ADR matches, say no indexed decision was found. Do not invent one.
- Cite ADR IDs in the answer and keep it concise, leading with the current
  decision.

---

## king-record-decision

**Trigger / purpose.** Creating and maintaining ADRs. Fires when the user asks
to create an ADR, register a decision, document an architecture choice,
supersede an old decision, or record why the project changed direction. It is
the write side of the ADR workflow.

**Commands it drives.** The `kctx adr` mutation and validation subcommands, plus
the same retrieval commands used to find related decisions first:

```bash
.king-context/bin/kctx adr status
.king-context/bin/kctx adr index
.king-context/bin/kctx adr search "<topic>" --active --top 5
.king-context/bin/kctx adr new --from-file <path> \
  [--supersedes <ids> --supersession-reason "<why>"] [--related <ids>]
.king-context/bin/kctx adr validate
.king-context/bin/kctx adr timeline "<topic>"
```

**Key constraints it enforces.**

- Search for related and superseded decisions through `kctx adr` retrieval
  before writing. Do not scan `.king-context/adr/*.md` to discover relationships.
- Classify every existing match as `superseded-by-new`, `related`, `conflict`,
  or `irrelevant`. Use `--supersedes` with a concrete reason when the new
  decision replaces an old one, and `--related` when it only touches nearby
  architecture.
- If a new decision conflicts with an active ADR and the replacement is not
  explicit, ask the user before writing.
- After writing, always run `adr index`, then `adr validate`, then
  `adr timeline "<topic>"` and summarize the resulting state.
- Read or edit ADR markdown only when creating a new ADR or updating one the
  workflow selected.

For the end-to-end decision lifecycle and the `--from-file` convention this
skill relies on, see
[contributing/adr-workflow.md](contributing/adr-workflow.md).

---

## Related docs

- [architecture/overview.md](architecture/overview.md): how the kctx stack and
  the legacy MCP stack fit together.
- [architecture/cli-retrieval.md](architecture/cli-retrieval.md): the retrieval
  engine the king-context skill drives.
- [architecture/scraper-pipeline.md](architecture/scraper-pipeline.md) and
  [architecture/research-pipeline.md](architecture/research-pipeline.md): the
  two corpus producers.
- [architecture/providers.md](architecture/providers.md): the LLM provider layer
  behind enrichment and query generation.
- [architecture/mcp-legacy.md](architecture/mcp-legacy.md): the secondary stack
  the skills avoid (no shared data).
- [reference/corpus-schema.md](reference/corpus-schema.md),
  [reference/env-vars.md](reference/env-vars.md), and
  [reference/storage-layout.md](reference/storage-layout.md): the data shapes,
  keys, and on-disk layout the skills operate on.
