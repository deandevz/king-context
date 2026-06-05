# Providers

King Context is a CLI-first, local-first retrieval layer for AI agents. Two of
its pipelines, the scraper (`king-scrape`) and research (`king-research`), reach
out to external systems through pluggable provider abstractions. There are two
distinct provider layers and they do not share code or a registry:

- **Scraper providers** (`src/scraper_providers/`): fetch web content. Used by
  the scraper discover and fetch stages.
- **LLM providers** (`src/llm_providers/`): call language models. Used by the
  filter, enrich, and research stages.

Both layers solve the same shape of problem (select a backend by name, resolve
it from the environment per stage, fail with an actionable error when a backend
is missing) but they are implemented separately. This page documents each one.

For how these fit into the pipelines that call them, see
[Scraper pipeline](scraper-pipeline.md) and
[Research pipeline](research-pipeline.md). For the canonical CLI store these
pipelines feed, see [CLI retrieval](cli-retrieval.md).

## Scraper providers

Source: `src/scraper_providers/`.

A scraper provider does single-URL I/O and nothing else. The pipeline owns
concurrency, checkpoints, and disk writes (ADR-0010). This keeps a provider
small: a discovery provider enumerates URLs, a fetch provider downloads one
page. Everything around them (the `asyncio.Semaphore`, the per-page checkpoint
files, the manifest) lives in the scraper stages, not the provider.

### The protocols

`src/scraper_providers/base.py` defines two runtime-checkable Protocols and the
shared data shapes:

```python
@runtime_checkable
class DiscoveryProvider(Protocol):
    name: str
    async def discover_urls(self, base_url: str) -> list[str]: ...

@runtime_checkable
class FetchProvider(Protocol):
    name: str
    async def fetch_one(self, url: str) -> PageContent: ...
```

`PageContent` is a frozen dataclass carrying `url`, `markdown`, `fetched_at`,
and an optional `title`. A provider returns one `PageContent` per fetched URL;
the pipeline writes the markdown and a `.meta.json` sidecar from there.

`ProviderUnavailableError` is raised when a provider is selected but its
dependency or setup step is missing. It carries a `provider` name and an
actionable `hint` (an install or setup instruction), not a raw `ImportError`
traceback.

### The registry

`src/scraper_providers/registry.py` holds two in-memory factory maps, one for
discovery providers and one for fetch providers. Registration is
**first-write-wins**: `register_discovery_provider` and
`register_fetch_provider` only store a factory if the name is not already
present, so built-in providers registered first always beat later plugins on a
name conflict.

Lookup raises `ValueError` on an unknown name, and the message lists the
registered names:

```text
Unknown discovery provider 'X'. Registered: ['crawl4ai', 'firecrawl']
```

This `ValueError` is what the scraper CLI maps to exit code 2 (see
[Exit codes](#exit-codes) below).

### Env resolution chain

`resolve_provider_name(stage)` picks a provider name per stage with this
precedence:

```text
SCRAPE_<STAGE>_PROVIDER  >  SCRAPE_PROVIDER  >  "firecrawl"
```

The `<STAGE>` token is `DISCOVER` or `FETCH`. So `SCRAPE_DISCOVER_PROVIDER`
overrides `SCRAPE_PROVIDER` for the discover stage only, `SCRAPE_FETCH_PROVIDER`
does the same for fetch, and when nothing is set both stages fall back to the
hardcoded `firecrawl` default (ADR-0009).

| Variable | Effect |
|----------|--------|
| `SCRAPE_PROVIDER` | Sets the provider for both stages. |
| `SCRAPE_DISCOVER_PROVIDER` | Overrides `SCRAPE_PROVIDER` for the discover stage. |
| `SCRAPE_FETCH_PROVIDER` | Overrides `SCRAPE_PROVIDER` for the fetch stage. |

The `king-scrape --provider <name>` flag is shorthand for setting
`SCRAPE_PROVIDER` for one run. In `src/king_context/scraper/cli.py` it is
applied with `os.environ.setdefault`, so an explicit `SCRAPE_PROVIDER` already
in the environment wins over the flag, and stage-specific variables win over
both. See [Env vars](../reference/env-vars.md) for the full table.

### Built-in providers

The package ships two built-ins. Both their SDKs are optional dependencies, so
each provider module soft-imports its SDK and registers itself only when the
import succeeds.

| Provider | Status | Dependency | Discover | Fetch | Notes |
|----------|--------|------------|----------|-------|-------|
| `firecrawl` | default | `firecrawl-py` (extra: `firecrawl`) | `app.map(base_url)` | `app.scrape(url, formats=["markdown"])` | Cloud. Needs `FIRECRAWL_API_KEY`. |
| `crawl4ai` | beta | `crawl4ai` (extra: `crawl4ai`) | `BFSDeepCrawlStrategy(max_depth=2)` | local Playwright | Free, local. One-time `crawl4ai-setup` for the browser binary. |

`firecrawl` (ADR-0009, `src/scraper_providers/firecrawl_provider.py`) wraps the
`firecrawl-py` SDK. It builds a `FirecrawlApp` with `FIRECRAWL_API_KEY` and runs
the blocking SDK calls in a worker thread via `asyncio.to_thread`. If the SDK is
not installed it raises `ProviderUnavailableError("firecrawl", ...)` with an
install hint.

`crawl4ai` (ADR-0011, `src/scraper_providers/crawl4ai_provider.py`) is a local
Playwright-based backend. Discovery uses `BFSDeepCrawlStrategy(max_depth=2,
include_external=False)`. It is the only provider that honours the
`SCRAPE_CACHE_MODE` env (mapped to Crawl4AI's `CacheMode` enum, with an unknown
value warned once and treated as the library default). It distinguishes two
failure modes:

- SDK not installed: `ProviderUnavailableError("crawl4ai", install_hint)`.
- SDK installed but the chromium binary missing: detected from the Playwright
  error text and re-raised as `ProviderUnavailableError("crawl4ai", setup_hint)`
  pointing at `crawl4ai-setup`.

### Third-party plugins

Third-party scraper providers register through the
`king_context.scraper_providers` entry-point group (declared in
`pyproject.toml`). A plugin exposes a `register()` callable that calls
`register_discovery_provider` and/or `register_fetch_provider`.

`load_entry_point_providers()` in the registry loads every entry point in that
group. It runs **after** the built-ins are registered in
`src/scraper_providers/__init__.py`, so first-write-wins keeps built-ins
authoritative on a name clash. A plugin that fails to import or register is
silently skipped, so one broken third-party package cannot break the import of
the whole provider layer.

The two built-ins are themselves declared in that entry-point group in
`pyproject.toml`, which keeps the registration path uniform even though they are
also soft-imported eagerly at package init.

### Exit codes

`ProviderUnavailableError` and the registry's `ValueError` surface through the
scraper CLI as distinct exit codes. From `src/king_context/scraper/cli.py`:

| Exception | Exit code | Meaning |
|-----------|-----------|---------|
| `ProviderUnavailableError` | `3` | Provider selected but its dependency or setup step is missing. The hint is printed to stderr. |
| `ValueError` | `2` | Unknown provider name (registry lookup failed) or other invalid argument. |

These exit codes exist only in the scraper CLI (`king-scrape`). The `kctx`
command uses `sys.exit(1)` for all errors. See [the CLI
guide](../CLI_GUIDE.md) for user-facing troubleshooting of these errors.

## LLM providers

Source: `src/llm_providers/`.

The LLM provider layer (ADR-0003) is shared by the filter, enrich, and research
stages. A client makes a single JSON completion call and returns a parsed JSON
object. The abstract interface in `src/llm_providers/base.py`:

```python
class LLMClient(ABC):
    name: str
    model: str
    concurrency: int

    @abstractmethod
    async def complete(
        self, prompt: str, *, system: str | None = None, json_mode: bool = True
    ) -> dict[str, Any]: ...
```

`ProviderError` carries a stable machine-readable `reason`, a `transient` flag,
and the originating `provider`. The transient flag and the reason drive the
fallback logic below.

### Stage-aware config resolution

`resolve(stage)` in `src/llm_providers/config.py` reads the environment for one
active stage. Valid stages are `enrich`, `filter`, and `research`. Each stage
has its own prefixed variables:

```text
<STAGE>_PROVIDER   default "openrouter"
<STAGE>_MODEL      default "google/gemini-3-flash-preview"
```

So `ENRICH_PROVIDER` / `ENRICH_MODEL` configure the enrich stage,
`FILTER_PROVIDER` / `FILTER_MODEL` the filter stage, and `RESEARCH_PROVIDER` /
`RESEARCH_MODEL` the research stage. Each stage can pick a different provider and
model independently.

The default model `google/gemini-3-flash-preview` is defined as `DEFAULT_MODEL`
in `src/llm_providers/config.py`. The scraper config module carries the same
value as `DEFAULT_ENRICHMENT_MODEL` in
`src/king_context/scraper/config.py`.

`resolve()` validates the resolved config by default:

- An OpenRouter stage requires `OPENROUTER_API_KEY`.
- An Ollama stage requires `OLLAMA_API_MODE` to be `openai` or `native`.
- An Ollama stage with `ENABLE_FALLBACK=true` also requires `OPENROUTER_API_KEY`
  (the fallback target).

A bad stage name or an invalid provider raises `ConfigError`. See
[Env vars](../reference/env-vars.md) for the complete variable list.

### Built-in clients

| Provider | Default | API | Notes |
|----------|---------|-----|-------|
| `openrouter` | yes | `https://openrouter.ai/api/v1/chat/completions` | OpenAI-shaped. Needs `OPENROUTER_API_KEY`. |
| `ollama` | no | OpenAI-compatible (`/v1/chat/completions`) or native (`/api/chat`) | Local or remote. Selected by `OLLAMA_API_MODE`. |

`OpenRouterClient` (`src/llm_providers/openrouter.py`) posts a chat completion
and maps HTTP status codes to `ProviderError` reasons: `401/403` to `auth_error`
(not transient), `400` to `bad_request`, `404` to `model_not_found`, `429` to
`rate_limit` (transient), and `5xx` to `server_error` (transient).

`OllamaClient` (`src/llm_providers/ollama.py`) supports two API modes. In
`openai` mode it posts to `chat/completions` with a `json_object` response
format; in `native` mode it posts to `api/chat` with `format: "json"`. It reuses
two helpers (`_content_from_openai_shape`, `_http_error`) imported directly from
the OpenRouter module, so the OpenAI-shaped response and status-code handling
stay consistent between the two clients.

### One-way fallback

`get_stage_clients(stage)` in `src/llm_providers/__init__.py` returns a
`StageClients` with a `primary` client and an optional `schema_fallback`. When
the resolved provider is `ollama` **and** `ENABLE_FALLBACK` is set, the primary
is wrapped in a `FallbackClient` (`src/llm_providers/fallback.py`):

- The fallback is **one-way**: Ollama (primary) to OpenRouter (fallback). The
  wrapper rejects any other pairing with `ConfigError`.
- The OpenRouter fallback uses `FALLBACK_MODEL` (default
  `google/gemini-3-flash-preview`).
- It retries only on a fixed set of transient reasons: `connection_refused`,
  `model_not_found`, `invalid_response`, `rate_limit`, `server_error`,
  `timeout`. A non-transient primary failure re-raises immediately.
- If the fallback also fails, the original `ProviderError` is re-raised carrying
  both `primary_error` and `fallback_error`.

When the fallback fires, `log_fallback` in `src/llm_providers/logging.py`
records the transition (stage, primary, fallback, reason). Logging in this
package goes through that helper rather than ad-hoc print calls, so do not assume
a print-only convention here.

### JSON parsing

Model responses are not always clean JSON. `parse_json_object` in
`src/llm_providers/parser.py` accepts a dict as-is, and from a string it
handles fenced blocks (```` ```json ````), prose-wrapped objects (it extracts
the first balanced `{...}`), and otherwise-valid JSON with trailing commas.
Unparseable content raises `ProviderError("invalid_response", transient=False)`.
Both built-in clients run their response content through this parser, so callers
always receive a plain dict.

### Extending the LLM layer

New LLM providers register through `register_provider(name, cls)` in
`src/llm_providers/registry.py`, which stores the class and adds the name to the
set of valid providers. The two built-ins are registered this way at import time
in `src/llm_providers/__init__.py`:

```python
register_provider("openrouter", OpenRouterClient)
register_provider("ollama", OllamaClient)
```

Unlike the scraper layer, the LLM layer has no entry-point group: it has no
`king_context.llm_providers` entry point in `pyproject.toml`, so extension is
in-process via `register_provider` rather than via installable plugins
(ADR-0003).

## How the two layers differ

| Aspect | Scraper providers | LLM providers |
|--------|-------------------|---------------|
| Source | `src/scraper_providers/` | `src/llm_providers/` |
| Interface | `DiscoveryProvider` / `FetchProvider` Protocols | `LLMClient` ABC |
| Stages | discover, fetch | filter, enrich, research |
| Env chain | `SCRAPE_<STAGE>_PROVIDER` > `SCRAPE_PROVIDER` > `firecrawl` | `<STAGE>_PROVIDER` (default `openrouter`) |
| Default | `firecrawl` | `openrouter`, model `google/gemini-3-flash-preview` |
| Registry | first-write-wins, two maps | name to class map |
| Plugins | entry-point group `king_context.scraper_providers` | in-process `register_provider` only |
| Missing backend | `ProviderUnavailableError` (CLI exit 3) | `ConfigError` at resolve |

## Type-hint convention

New provider code uses PEP 604 unions (`str | None`), which is why the provider
modules open with `from __future__ import annotations`. Legacy core modules keep
`typing.Optional` for local consistency within those modules. The criterion is
the module's lineage, not a fixed file list: new code follows the PEP 604 style,
older core modules stay internally consistent. See
[Code style](../contributing/code-style.md).

## Related

- [Scraper pipeline](scraper-pipeline.md): the discover and fetch stages that
  call scraper providers.
- [Research pipeline](research-pipeline.md): the search and enrich stages that
  call LLM providers (and Exa / Jina for retrieval).
- [Env vars](../reference/env-vars.md): every provider-related variable.
- [Architecture overview](overview.md): how the pipelines connect.
- [MCP legacy stack](mcp-legacy.md): the secondary `server.py` stack, which does
  not use these providers.
