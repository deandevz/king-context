# Environment variables

King Context is a CLI-first, local-first retrieval layer for AI agents. Most
configuration lives in environment variables, loaded from `.env` files at
startup. This page is the single canonical reference for every variable the
code reads, where it is read, and what it does.

Related references: [storage layout](storage-layout.md),
[corpus schema](corpus-schema.md). See also the
[scraper pipeline](../architecture/scraper-pipeline.md),
[research pipeline](../architecture/research-pipeline.md), and
[providers](../architecture/providers.md) architecture pages.

## Where env files live

CLI entry points load env files through `load_project_env()` in
`src/king_context/env.py`. Two files are read, in this order:

1. `.king-context/.env` (the installed project file). Loaded first, **without
   override**: it only fills variables that are not already in the process
   environment.
2. `.env` at the project root (the developer clone file). Loaded second,
   **with override**: values here win over the installed file and over earlier
   defaults.

Variables already present in the real process environment before either file
loads are protected and never overwritten by a `.env` file (see the `protected`
set in `src/king_context/env.py`). Precedence, highest to lowest:

| Source | Override behavior |
| --- | --- |
| Process environment (exported before the CLI runs) | Always wins |
| `.env` (clone root) | Overrides the installed file and defaults |
| `.king-context/.env` (installed project) | Fills only unset variables |
| Hardcoded defaults in code | Used when nothing else is set |

Which file should you use?

- **Installed in a project** (via `npx @king-context/cli init`): put keys in
  `.king-context/.env`.
- **Developing in a clone of this repo**: copy `.env.example` to `.env` at the
  repo root and edit that. The clone-root `.env` overrides the installed file,
  which is convenient for local development.

To disable env-file loading entirely, set `KING_CONTEXT_DISABLE_DOTENV`.

| Variable | Default | Read in | What it does |
| --- | --- | --- | --- |
| `KING_CONTEXT_DISABLE_DOTENV` | unset | `src/king_context/env.py` | When set to `1`, `true`, `yes`, or `on`, `load_project_env()` returns immediately and reads no `.env` file. The process environment is used as-is. |

## API keys

| Variable | Default | Read in | What it does |
| --- | --- | --- | --- |
| `FIRECRAWL_API_KEY` | empty | `src/king_context/scraper/config.py` | API key for the default `firecrawl` scrape provider. `get_firecrawl_key()` raises `ConfigError` if it is unset when Firecrawl is required. |
| `OPENROUTER_API_KEY` | empty | `src/king_context/scraper/config.py`, `src/llm_providers/config.py` | API key for OpenRouter LLM stages. Required when a stage provider resolves to `openrouter`, and required when `ENABLE_FALLBACK=true` for an Ollama stage. Validation raises `ConfigError` when missing. |
| `EXA_API_KEY` | empty | `src/king_context/research/config.py` | API key for Exa web search, used by `king-research`. `load_research_config()` raises `ConfigError` if it is unset. |
| `JINA_API_KEY` | empty | `src/king_context/research/config.py` | Optional API key for the Jina Reader fallback fetcher (`https://r.jina.ai/`) used by `king-research` when an Exa result comes back thin. Requests work without a key (the `Authorization` header is attached only when a key is present); setting a key raises rate limits. |

## Scraper provider selection

`king-scrape` (and the `audit` and `update` subcommands) pick a provider per
stage. Resolution order is defined in
`src/scraper_providers/registry.py` (`resolve_provider_name()`): the
stage-specific variable wins, then the global `SCRAPE_PROVIDER`, then the
hardcoded default `firecrawl`.

| Variable | Default | Read in | What it does |
| --- | --- | --- | --- |
| `SCRAPE_PROVIDER` | `firecrawl` (hardcoded) | `src/scraper_providers/registry.py`, `src/king_context/scraper/config.py` | Global scraper provider for all stages. Options: `firecrawl` (requires `FIRECRAWL_API_KEY`) and `crawl4ai` (local, beta; activate with `crawl4ai-setup`). |
| `SCRAPE_DISCOVER_PROVIDER` | falls back to `SCRAPE_PROVIDER`, then `firecrawl` | `src/scraper_providers/registry.py`, `src/king_context/scraper/config.py` | Overrides the provider for the discover stage only. |
| `SCRAPE_FETCH_PROVIDER` | falls back to `SCRAPE_PROVIDER`, then `firecrawl` | `src/scraper_providers/registry.py`, `src/king_context/scraper/config.py` | Overrides the provider for the fetch stage only. |
| `SCRAPE_CACHE_MODE` | unset (provider default) | `src/king_context/scraper/_cache_mode.py` | Overrides the scraper provider's local cache behavior. Allowed values: `default` (or unset), `enabled`, `bypass`, `disabled`, `read_only`, `write_only`. Currently honored by the `crawl4ai` provider only; other providers may ignore it. |

The `king-scrape --provider <name>` flag sets `SCRAPE_PROVIDER` for the run via
`setdefault`, so an explicit pre-existing `SCRAPE_PROVIDER` wins over the flag
(see `run_pipeline()` in `src/king_context/scraper/cli.py`). The
`--no-fetch-cache` flag is shorthand for `SCRAPE_CACHE_MODE=bypass`, also
applied with `setdefault`, so an explicit `SCRAPE_CACHE_MODE` is not
downgraded (see `apply_cache_mode_flag()` in
`src/king_context/scraper/_cache_mode.py`).

## LLM stage configuration

The scraper and research pipelines call an LLM in named stages: `enrich`,
`filter`, and `research`. Each stage has a provider variable and a model
variable, resolved in `src/llm_providers/config.py` (`_provider_for()` and
`_stage_model()`). The provider defaults to `openrouter` and the model defaults
to `google/gemini-3-flash-preview`. Allowed providers are `openrouter` and
`ollama`.

| Variable | Default | Read in | What it does |
| --- | --- | --- | --- |
| `ENRICH_PROVIDER` | `openrouter` | `src/llm_providers/config.py` | Provider for the enrich stage. Must be `openrouter` or `ollama`. |
| `ENRICH_MODEL` | `google/gemini-3-flash-preview` | `src/llm_providers/config.py`, `src/king_context/scraper/config.py` | Model for the enrich stage. Also read by the scraper config as the enrichment model. |
| `FILTER_PROVIDER` | `openrouter` | `src/llm_providers/config.py` | Provider for the filter stage. Must be `openrouter` or `ollama`. |
| `FILTER_MODEL` | `google/gemini-3-flash-preview` | `src/llm_providers/config.py` | Model for the filter stage. |
| `RESEARCH_PROVIDER` | `openrouter` | `src/llm_providers/config.py` | Provider for the research stage. Must be `openrouter` or `ollama`. |
| `RESEARCH_MODEL` | `google/gemini-3-flash-preview` | `src/llm_providers/config.py`, `src/king_context/research/config.py` | Model for the research stage. The research config prefers this, then `OPENROUTER_MODEL_RESEARCH`. |
| `OPENROUTER_MODEL_RESEARCH` | empty | `src/llm_providers/config.py`, `src/king_context/research/config.py` | Legacy alias for the research model. Used only when `RESEARCH_MODEL` is unset. Prefer `RESEARCH_MODEL` for new configs. |

## Ollama

Ollama is the local (and Ollama Cloud) provider option. These variables are
read in `src/llm_providers/config.py` when a stage provider resolves to
`ollama`, plus the fallback path.

| Variable | Default | Read in | What it does |
| --- | --- | --- | --- |
| `OLLAMA_API_MODE` | `openai` | `src/llm_providers/config.py` | API mode for Ollama. Must be `openai` (OpenAI-compatible endpoint) or `native` (Ollama native API). Validation raises `ConfigError` for other values. |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | `src/llm_providers/config.py` | Base URL for the Ollama endpoint. A trailing slash is stripped. Use `https://ollama.com` for Ollama Cloud. |
| `OLLAMA_API_KEY` | empty | `src/llm_providers/config.py` | API key for Ollama. Optional for local Ollama; used for Ollama Cloud. |
| `CONCURRENCY_OLLAMA` | `2` | `src/llm_providers/config.py` | Number of concurrent LLM calls when the active provider is `ollama`. Read by `provider_concurrency()`. Values that are not positive integers fall back to the default. |
| `CONCURRENCY_OPENROUTER` | `5` | `src/llm_providers/config.py` | Number of concurrent LLM calls when the active provider is `openrouter`. Read by `provider_concurrency()`. |
| `ENABLE_FALLBACK` | `false` | `src/llm_providers/config.py` | When truthy (`1`, `true`, `yes`, `y`, `on`), enables one-way fallback from Ollama to OpenRouter. Requires `OPENROUTER_API_KEY` for an active Ollama stage. |
| `FALLBACK_MODEL` | `google/gemini-3-flash-preview` | `src/llm_providers/config.py` | OpenRouter model used when the Ollama-to-OpenRouter fallback triggers. |

Provider concurrency is resolved generically by `provider_concurrency()`:
the variable name is `CONCURRENCY_<PROVIDER>` (uppercased), so a registered
custom provider named `foo` would read `CONCURRENCY_FOO`. The defaults are `5`
for `openrouter` and `2` for any other provider.

## Research effort ladder

`king-research` scales how many queries and deepening iterations it runs by
effort level. The effort ladder variables are read in
`src/king_context/research/config.py` (`load_research_config()`). All are
optional integer overrides; non-integer values fall back to the default.

| Variable | Default | Read in | What it does |
| --- | --- | --- | --- |
| `RESEARCH_BASIC_QUERIES` | `3` | `src/king_context/research/config.py` | Initial queries for the basic effort level (0 iterations, 0 followups). |
| `RESEARCH_MEDIUM_QUERIES` | `5` | `src/king_context/research/config.py` | Initial queries for the medium effort level. |
| `RESEARCH_MEDIUM_ITERATIONS` | `1` | `src/king_context/research/config.py` | Deepening iterations for the medium effort level. |
| `RESEARCH_MEDIUM_FOLLOWUPS` | `3` | `src/king_context/research/config.py` | Followup queries per iteration for the medium effort level. |
| `RESEARCH_HIGH_QUERIES` | `8` | `src/king_context/research/config.py` | Initial queries for the high effort level. |
| `RESEARCH_HIGH_ITERATIONS` | `2` | `src/king_context/research/config.py` | Deepening iterations for the high effort level. |
| `RESEARCH_HIGH_FOLLOWUPS` | `5` | `src/king_context/research/config.py` | Followup queries per iteration for the high effort level. |
| `RESEARCH_EXTRAHIGH_QUERIES` | `12` | `src/king_context/research/config.py` | Initial queries for the extra-high effort level. |
| `RESEARCH_EXTRAHIGH_ITERATIONS` | `3` | `src/king_context/research/config.py` | Deepening iterations for the extra-high effort level. |
| `RESEARCH_EXTRAHIGH_FOLLOWUPS` | `8` | `src/king_context/research/config.py` | Followup queries per iteration for the extra-high effort level. |
| `EXA_RESULTS_PER_QUERY` | `10` | `src/king_context/research/config.py` | Number of Exa results requested per query. |
| `EXA_MAX_CHARS` | `15000` | `src/king_context/research/config.py` | Maximum characters retrieved per Exa source. |

## Local UI

| Variable | Default | Read in | What it does |
| --- | --- | --- | --- |
| `KCTX_UI_PORT` | `7373` | `src/king_context/web/server.py` | Start port for `kctx ui`. Read by `_resolve_start_port()` only when `--port` is not passed. If busy, the server auto-increments up to 20 ports. An invalid value prints `Invalid KCTX_UI_PORT` to stderr and the server exits with code 2. |

See the [local UI architecture](../architecture/local-ui.md) page for details.

## Notes

- The `kctx` flat-file store under `.king-context/` is the canonical stack. The
  MCP server (`src/king_context/server.py` plus `src/king_context/db.py` with
  SQLite, FTS5, and embeddings) is the legacy stack per ADR-0001. The two
  stacks do not share data; see [MCP (legacy)](../architecture/mcp-legacy.md).
- Boolean variables (`ENABLE_FALLBACK`, `KING_CONTEXT_DISABLE_DOTENV`) accept
  `1`, `true`, `yes`, `on` (and `y` for `ENABLE_FALLBACK`), case-insensitive.
  Anything else reads as false.
- Empty-string values are treated as unset by the config loaders (they strip
  whitespace and fall back to defaults).
- A starter file lives at `.env.example` in the repo root. Copy it to `.env`
  and fill in the keys you need.
