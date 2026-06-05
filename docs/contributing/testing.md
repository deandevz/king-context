# Testing

King Context is a CLI-first, local-first retrieval layer for AI agents. The test suite is the contract that keeps the retrieval layer trustworthy across its packages. This guide describes the patterns the existing tests already follow, so a new contribution lands consistent with the rest of the suite.

Every claim here is grounded in the actual test code. Read the files referenced before copying a pattern.

## Layout: `tests/` mirrors `src/`

The four shipped packages (`pyproject.toml`, `[tool.hatch.build.targets.wheel]`) each have matching test coverage under `tests/`.

| Package | What it is | Where the tests live |
| --- | --- | --- |
| `src/context_cli` | The canonical `kctx` flat-file stack | `tests/test_context_cli/` |
| `src/king_context/scraper` | `king-scrape` pipeline (discover, filter, fetch, chunk, enrich, export, audit, update) | `tests/test_scraper/`, plus `tests/test_scraper_cli_flags.py`, `tests/test_scraper_enrich_resume.py`, `tests/test_scraper_fetch_resume.py`, `tests/test_scraper_manifest.py`, `tests/test_scraper_resume_integration.py` |
| `src/king_context/research` | `king-research` pipeline | `tests/test_research/` |
| `src/scraper_providers` | Pluggable Firecrawl / Crawl4AI providers | `tests/test_scraper_providers/` |
| `src/llm_providers` | OpenRouter / Ollama clients, config, fallback, parsing | `tests/test_llm_providers/` |
| `src/king_context/web` | Local UI server, handlers, render, search, static, corpus | `tests/test_web_server.py`, `tests/test_web_handlers.py`, `tests/test_web_render.py`, `tests/test_web_search.py`, `tests/test_web_static.py`, `tests/test_web_corpus.py` |
| `src/king_context` (legacy MCP stack) | `server.py` MCP tools and `db.py` SQLite/FTS5/embeddings engine | `tests/test_server.py`, `tests/test_db.py`, `tests/test_seed_data.py`, `tests/test_embeddings.py`, `tests/test_load_embeddings.py` |
| `installer/` | npm scaffold behavior | `tests/test_installer_scaffold.py`, `tests/test_installer_gitignore.py` |

The `kctx` flat-file store under `.king-context/` is the canonical stack. The MCP server (`server.py` plus the `db.py` SQLite/FTS5/embeddings engine) is the legacy/secondary stack per ADR-0001, and the two stacks do not share data. Tests treat them as separate worlds: `tests/test_context_cli/` patches the flat-file store dirs, while `tests/test_db.py` and `tests/test_server.py` patch the SQLite `DB_PATH`. Do not mix them in one test.

## Isolation: `tmp_path` + `monkeypatch`

No test touches the real repo, the real `.king-context/` store, or a developer's `.env`. Isolation comes from two pytest fixtures, `tmp_path` and `monkeypatch`, plus a few autouse fixtures in `tests/conftest.py`.

### Autouse fixtures (apply to every test)

`tests/conftest.py` defines three fixtures that run for every test:

- `disable_project_dotenv` sets `KING_CONTEXT_DISABLE_DOTENV=1`. `src/king_context/env.py` short-circuits `load_project_env()` when that variable is truthy, so a developer's local `.king-context/.env` or `.env` cannot leak API keys or config into a test run.
- `_isolate_enrich_cache` redirects `king_context.scraper.enrich_cache.DEFAULT_CACHE_DIR` into a fresh `tmp_path`. Tests reuse identical chunk content, and without this the on-disk enrichment cache would short-circuit the LLM call paths the tests are exercising.

Both are `autouse=True`, so you do not request them. They are already in effect.

### Legacy MCP stack: `DB_PATH` override

`tests/conftest.py` also exposes the opt-in `temp_db` fixture for the SQLite stack. Requesting it points the whole `db` module at a throwaway database and resets in-process embedding state:

```python
@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    temp_db_path = tmp_path / "test_docs.db"
    monkeypatch.setattr(db, "DB_PATH", temp_db_path)
    monkeypatch.setattr(db, "EMBEDDINGS_PATH", tmp_path / "embeddings.npy")
    monkeypatch.setattr(db, "SECTION_MAPPING_PATH", tmp_path / "section_mapping.json")
    monkeypatch.setattr(db, "_embeddings", None)
    monkeypatch.setattr(db, "_section_id_to_idx", {})
    yield temp_db_path
```

The embedding sidecar overrides matter: a test that triggers embedding generation must not write into the real repo's `data/` directory. `tests/test_db.py` requests `temp_db` for every test that needs the database.

### Canonical CLI stack: store dir overrides

The flat-file stack has no shared DB fixture. Each test builds a `.king-context/` tree under `tmp_path` and monkeypatches the module-level path constants. From `tests/test_context_cli/test_cli.py`:

```python
store_dir = tmp_path / ".king-context" / "docs"
store_dir.mkdir(parents=True)
research_store_dir = tmp_path / ".king-context" / "research"
research_store_dir.mkdir(parents=True)
# ... index a doc ...
import context_cli.cli as cli_mod
monkeypatch.setattr(cli_mod, "STORE_DIR", store_dir)
monkeypatch.setattr(cli_mod, "RESEARCH_STORE_DIR", research_store_dir)
monkeypatch.setattr(cli_mod, "PROJECT_ROOT", tmp_path)
```

When a path is read through an indirection, patch the indirection, not every caller. `tests/test_web_handlers.py` patches `context_cli.cli.PROJECT_ROOT` once because `context_cli.adr._project_root()` funnels all ADR and decision paths through it.

Provider registries are global, so `tests/test_scraper_providers/conftest.py` snapshots and restores `registry._DISCOVERY_FACTORIES` and `registry._FETCH_FACTORIES` around every test, preventing registrations in one test from leaking into the next.

## Patch targets use full module paths

Patch the name in the module that uses it, not where it was defined. This is the single most common mistake to avoid.

From `tests/test_scraper_cli_flags.py`, the pipeline functions are patched on `king_context.scraper.cli`, the module under test, even though they are defined elsewhere:

```python
with patch(
    "king_context.scraper.cli.discover_urls", new_callable=AsyncMock, return_value=discovery,
), patch(
    "king_context.scraper.cli.filter_urls", return_value=filter_result,
):
    ...
```

The same rule shows up across stacks:

- `tests/test_server.py` patches `king_context.server.search_cascade` and `king_context.server.list_documentations` (the names the server module imported).
- `tests/test_research/test_fetch.py` patches `king_context.research.fetch.exa_search` and `king_context.research.fetch.jina_fetch`.

Async functions are replaced with `new_callable=AsyncMock`. Mocks are asserted with `assert_called_once()`, `assert_not_called()`, and `call_args` to verify behavior, not just output.

## HTTP and LLM faking: never hit the network

No test makes a real network call or a real LLM call. There are three established techniques, pick the one that fits.

### 1. `httpx.MockTransport` for real client code

When the code under test builds and drives a real `httpx` client, install a `MockTransport` with a handler that returns canned `httpx.Response` objects. From `tests/test_research/test_jina.py`:

```python
def handler(request: httpx.Request) -> httpx.Response:
    return responses.pop(0)

transport = httpx.MockTransport(handler)
async with httpx.AsyncClient(transport=transport) as client:
    result = await fetch("https://example.com/a", "", client)
```

`tests/test_llm_providers/test_clients.py` uses the same transport to exercise the OpenRouter and Ollama clients end to end, then asserts the captured request URL, headers, and JSON body shape. When the client is constructed internally rather than injected, it monkeypatches the `httpx.AsyncClient` factory to inject the transport:

```python
def _patch_async_client(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient
    def factory(*args, **kwargs):
        return original_async_client(transport=transport, timeout=kwargs.get("timeout"))
    monkeypatch.setattr(httpx, "AsyncClient", factory)
```

`tests/test_scraper/test_audit.py` also drives the audit path through `httpx.MockTransport`. `respx` is available in the `dev` extra (`pyproject.toml`) as an alternative HTTP-mocking layer.

### 2. The `FakeLLMClient` for LLM stages

For pipeline steps that take an LLM client, use the `FakeLLMClient` from `tests/conftest.py`. It implements the same `async complete(...)` interface, records every call on `self.calls`, and returns queued `responses` or runs a `side_effect`:

```python
class FakeLLMClient:
    async def complete(self, prompt, *, system=None, json_mode=True):
        self.calls.append({"prompt": prompt, "system": system, "json_mode": json_mode})
        ...
```

The `fake_stage_clients(primary, schema_fallback=None)` helper wraps a fake into the `primary` / `schema_fallback` shape the enrichment stages expect.

### 3. Patch the boundary function with `AsyncMock`

When you only care that the right thing was called with the right arguments, patch the network-facing function directly. `tests/test_research/test_fetch.py` patches `exa_search` and `jina_fetch` with `AsyncMock` and `side_effect` callables that raise `JinaPermanentError`, `JinaTransientError`, or decode errors to verify per-URL failure isolation, all without a socket.

## Async tests: `asyncio_mode = "auto"`

`pyproject.toml` sets `asyncio_mode = "auto"` under `[tool.pytest.ini_options]` (the `pytest-asyncio` plugin ships in the `dev` extra). Under auto mode, a coroutine test function is collected and run without any decorator. `tests/test_research/test_fetch.py` relies on this: every test is a bare `async def test_...` with no marker.

`@pytest.mark.asyncio` still works and is used where a contributor preferred to be explicit, for example in `tests/test_scraper_cli_flags.py` and `tests/test_llm_providers/test_clients.py`. Both styles are fine. The bare-`async def` style is the lighter default this suite leans on.

## Running tests

The suite is invoked with plain `pytest`. `testpaths = ["tests"]` is set in `pyproject.toml`, so you can run it from the repo root.

```bash
pip install -e ".[firecrawl,dev]"   # test deps live in the dev extra
pytest                              # full suite
pytest -q                           # quiet, matches CI
pytest -k <expr>                    # select tests by name expression
pytest tests/test_db.py            # one file
pytest tests/test_db.py -v          # one file, verbose
pytest tests/test_context_cli/      # one package's tests
```

CLI tests run `main()` by patching `sys.argv` and capturing output. From `tests/test_context_cli/test_cli.py`:

```python
def _run_cli(args, monkeypatch):
    from context_cli.cli import main
    monkeypatch.setattr(sys, "argv", ["kctx"] + args)
    main()
```

Output is read with the `capsys` fixture (`capsys.readouterr().out` / `.err`). Error paths assert on the exit: `kctx` raises `SystemExit` via `sys.exit(1)` everywhere, so failure tests use `with pytest.raises(SystemExit):` and then check `capsys.readouterr().err` for the message.

The scraper CLI is the one exception with distinct exit codes. `src/king_context/scraper/cli.py` exits `2` on a `ValueError` and `3` on a `ProviderUnavailableError`. Those codes exist only in the scraper CLI; they are not used anywhere in `kctx`.

## CI reality

The workflow is `.github/workflows/test.yml`. Two jobs run on push to `main` and on pull requests against `main`:

1. **Pytest (firecrawl path)** runs on `ubuntu-latest`, Python **3.11 only**. It installs `pip install -e ".[firecrawl,dev]"` and runs `pytest -q`. (The package supports 3.10 to 3.12 per `pyproject.toml`, but CI exercises 3.11.)
2. **Crawl4AI smoke test** depends on the pytest job (`needs: [test]`), installs `pip install -e ".[crawl4ai,dev]"`, runs `crawl4ai-setup`, then runs `python scripts/smoke-crawl4ai.py` with a 5 minute timeout.

The smoke job is **blocking by design** (ADR-0011). It exists to catch API churn between crawl4ai minor versions (the pin is `>=0.8.5,<0.9`). If it breaks, the team wants to know before a release, not after. Do not move it to `continue-on-error`.

There is **no lint job and no type-check job** in CI. Style is enforced by review and convention (see [code-style.md](code-style.md)), not by a pipeline step. Keep your diff clean accordingly.

## What a feature PR is expected to include

Based on the patterns above, a new feature or fix should land with tests that:

- Live under the matching package directory in the table above (a new `kctx` subcommand goes in `tests/test_context_cli/`, a new research step in `tests/test_research/`, and so on).
- Isolate all state through `tmp_path` and `monkeypatch`. Build any `.king-context/` tree under `tmp_path` and patch the relevant store-dir or `DB_PATH` constants. Never read or write the real repo.
- Make zero network and zero LLM calls. Use `httpx.MockTransport`, the `FakeLLMClient`, or an `AsyncMock` patch at the boundary, whichever fits.
- Patch by full module path, on the module that imported the name.
- Cover the failure path, not just the happy path. Assert the exit (`pytest.raises(SystemExit)` for CLIs) and the stderr message, mirroring `tests/test_context_cli/test_cli.py`.
- Pass under `pytest -q` on Python 3.11, since that is exactly what CI runs.

## Related docs

- [Architecture overview](../architecture/overview.md)
- [CLI retrieval stack](../architecture/cli-retrieval.md)
- [Scraper pipeline](../architecture/scraper-pipeline.md)
- [Research pipeline](../architecture/research-pipeline.md)
- [Providers](../architecture/providers.md)
- [Legacy MCP stack](../architecture/mcp-legacy.md)
- [Environment variables](../reference/env-vars.md)
- [Storage layout](../reference/storage-layout.md)
- [Code style](code-style.md)
- [Commits and PRs](commits-and-prs.md)
- [ADR workflow](adr-workflow.md)
