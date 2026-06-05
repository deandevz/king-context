# Code style

King Context is a CLI-first, local-first retrieval layer for AI agents. This
guide describes the code style that is already in the tree, extracted from the
source rather than imposed on it. There is no linter or formatter configured,
so these conventions are enforced by convention and review, not by automation.
When in doubt, match the file you are editing.

Related contributor docs:

- [Testing](testing.md)
- [Commits and PRs](commits-and-prs.md)
- [ADR workflow](adr-workflow.md)

Background on the package layout and the two stacks:

- [Architecture overview](../architecture/overview.md)
- [CLI retrieval](../architecture/cli-retrieval.md)
- [Legacy MCP stack](../architecture/mcp-legacy.md)
- [Storage layout](../reference/storage-layout.md)
- [Environment variables](../reference/env-vars.md)

## No linter or formatter

There is no ruff, black, isort, flake8, or mypy configuration. `pyproject.toml`
contains only `[tool.pytest.ini_options]` and the `[tool.hatch.*]` build
settings (`pyproject.toml`). There are no `.ruff.toml`, `.flake8`, `setup.cfg`,
`mypy.ini`, or `.pre-commit-config.yaml` files at the repo root.

Because nothing reformats your code for you, match the existing hand-formatted
style:

- 4-space indentation.
- Trailing commas in multi-line calls and definitions (for example the
  `ProviderError.__init__` signature in `src/llm_providers/base.py` and the
  `add_argument(...)` blocks in `src/king_context/scraper/cli.py`).
- Keyword arguments aligned one per line when a call spans multiple lines.

The package targets `requires-python = ">=3.10"` (`pyproject.toml`), so any
syntax you use must be valid on Python 3.10.

## English only

All identifiers, comments, and docstrings are written in English. This is a hard
project rule from `CLAUDE.md`.

The one allowance is rationale prose that references an ADR. Architecture docs
and tasks may be in Portuguese, and that extends to a small number of
ADR-referencing comments. The CI workflow has a Portuguese ADR-0011 rationale
comment (`.github/workflows/test.yml`), while the equivalent inline ADR-0009
note in `src/king_context/scraper/cli.py` is in English. Never mix two languages
inside one file: pick the language the rest of that file already uses.

The single Portuguese document by design is `README-pt-br.md`.

## Typing

Type-annotate function signatures and dataclass fields. The repo splits into two
typing styles, and the dividing line is age, not directory.

New code uses PEP 604 syntax:

- `X | None` unions instead of `typing.Optional[X]`.
- Built-in generics (`list[str]`, `dict[str, Any]`) instead of `typing.List` and
  `typing.Dict`.
- `from __future__ import annotations` at the top of the module.

This is the dominant style: 31 files carry `from __future__ import annotations`.
See `src/scraper_providers/base.py` (`title: str | None = None`),
`src/llm_providers/base.py` (`provider: str | None`,
`"ProviderError | None"`), and `src/king_context/env.py`
(`protected: set[str]`, `project_root: Path | None`).

The legacy core uses `typing.Optional` and capitalized generics
(`from typing import Optional, List, Dict, Any`), as in
`src/king_context/db.py` (`_embedding_model: Optional[SentenceTransformer]`,
`doc_name: Optional[str] = None`).

The criterion:

- New modules and refactored packages use `X | None` plus
  `from __future__ import annotations`.
- When you edit a legacy core module that already imports `typing.Optional`,
  keep its existing style for local consistency rather than mixing both forms in
  one file.

Only three modules still import `typing.Optional` today, so most files you touch
will already be on the modern style.

## Paths: pathlib over os.path

All paths resolve from the current working directory. Each package defines
`PROJECT_ROOT = Path.cwd()` in its `__init__.py` (`src/king_context/__init__.py`
and `src/context_cli/__init__.py`) and derives store directories from it. In
`src/context_cli/__init__.py`, `STORE_DIR = PROJECT_ROOT / ".king-context" /
"docs"` plus the matching `RESEARCH_STORE_DIR` and `DECISIONS_STORE_DIR` are
defined this way.

Conventions:

- Build paths with the `/` operator, never `os.path.join`. Example:
  `PROJECT_ROOT / ".king-context" / "data" / f"{name}.json"` in
  `src/king_context/scraper/cli.py`.
- Read and write files through `Path.read_text()` / `Path.write_text()`.
- Discover files with `Path.glob()` and check presence with `Path.exists()`.
- Path constants are module-level `UPPER_CASE` derived from `PROJECT_ROOT`, for
  example `DB_PATH`, `EMBEDDINGS_PATH`, and `SECTION_MAPPING_PATH` in
  `src/king_context/db.py`.

The on-disk layout is rooted at `.king-context/` (`data/`, `docs/`, `research/`,
`decisions/`). See the [storage layout reference](../reference/storage-layout.md).

## Module-level state

Mutable module-level singletons are prefixed with a single underscore, annotated
near the top of the module, and initialized empty so they can be populated
lazily. See `src/king_context/db.py`:

```python
_embedding_model: Optional[SentenceTransformer] = None
_embeddings: Optional[np.ndarray] = None
_section_id_to_idx: Dict[int, int] = {}
```

Registries follow the same rule: private underscore-prefixed module dicts,
mutated only through `register_*` functions. See
`src/scraper_providers/registry.py`:

```python
_DISCOVERY_FACTORIES: dict[str, Callable[[], DiscoveryProvider]] = {}
_FETCH_FACTORIES: dict[str, Callable[[], FetchProvider]] = {}
```

## Docstrings and comments

Most modules open with a one-line module docstring summarizing purpose, for
example `"""Shared project exceptions."""` in `src/king_context/errors.py` and
`"""Common scraper provider interfaces."""` in `src/scraper_providers/base.py`.

Public functions and classes carry docstrings: a summary line, then detail when
useful. There are no Google or NumPy docstring sections (no formal `Args:` /
`Returns:` type blocks). Informal labeled blocks do appear when they help, such
as an `Examples:` block in `_name_from_url` (`src/king_context/scraper/cli.py`)
and a `Precedence:` block in `resolve_provider_name`
(`src/scraper_providers/registry.py`).

## Configuration and value objects

Configuration is modeled with dataclasses.

- Mutable config uses `@dataclass` with typed fields and defaults, for example
  `ScraperConfig` in `src/king_context/scraper/config.py` and `ResearchConfig`
  in `src/king_context/research/config.py`.
- Immutable value and profile objects use `@dataclass(frozen=True)`, for example
  `PageContent` in `src/scraper_providers/base.py` and `EffortProfile` in
  `src/king_context/research/config.py`.
- Closed choice sets use an enum that subclasses `(str, Enum)`, for example
  `EffortLevel` in `src/king_context/research/config.py`.

Config is loaded through `load_*()` functions that read `os.environ` after
calling `load_project_env()`, then apply caller `**overrides`. The scraper
reader skips overrides whose value is `None`:

```python
def load_config(**overrides) -> ScraperConfig:
    load_project_env()
    ...
    for key, value in overrides.items():
        if value is not None:
            setattr(config, key, value)
    return config
```

See `src/king_context/scraper/config.py` and `load_research_config` in
`src/king_context/research/config.py`. Env precedence is documented in the
relevant docstrings rather than left implicit. The full environment surface is
in the [env vars reference](../reference/env-vars.md).

`load_project_env` itself (`src/king_context/env.py`) shows the env-reading
discipline: installer env is loaded without override, the developer `.env` with
override, variables already set in the process are protected, and the whole pass
is skipped when `KING_CONTEXT_DISABLE_DOTENV` is truthy.

## JSON handling

JSON uses the stdlib `json` module:

- Read with `json.loads(path.read_text())`.
- Pretty-print CLI output with `json.dumps(payload, indent=2)`.
- Serialize dataclasses with `dataclasses.asdict` and round-trip them via
  `DataclassName(**json_dict)`.
- Guard defensive reads with `try/except (json.JSONDecodeError, OSError,
  KeyError)`.

See `_detect_source` and `_cmd_list` in `src/context_cli/cli.py`, and the
`EnrichedChunk(**c)`, `DiscoveryResult(**...)`, and `FilterResult(**...)`
reconstructions in `src/king_context/scraper/cli.py`.

## CLI argparse pattern

Every CLI module follows the same shape.

- A private `_build_parser() -> argparse.ArgumentParser` builds the parser with
  `prog=` and `description=`.
- A public `main() -> None` parses args and dispatches.
- The module ends with the standard guard:

  ```python
  if __name__ == "__main__":
      main()
  ```

For `kctx`, subcommands use `add_subparsers(dest="command")`, one
`_cmd_<name>(args)` handler per subcommand, wired with
`set_defaults(func=_cmd_<name>)`. `main()` dispatches through `args.func(args)`
after checking that a subcommand was given:

```python
def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        return
    args.func(args)
```

See `src/context_cli/cli.py`.

Flag conventions:

- Long flags use kebab-case (`--display-name`, `--chunk-max-tokens`,
  `--no-llm-filter`) with an explicit `dest=` in snake_case when the names
  differ.
- Help strings that have a default end with `(default: ...)`, for example
  `"Maximum tokens per chunk (default: 800)"` in
  `src/king_context/scraper/cli.py` and `"Max results (default: 5)"` in
  `src/context_cli/cli.py`.
- Mutually exclusive option sets use `add_mutually_exclusive_group()`, as the
  effort flags do in `src/king_context/research/cli.py` (`--basic`, `--medium`,
  `--high`, `--extrahigh` share `dest="effort_flag"` via `store_const`).

## Async style

I/O-bound pipelines are async, and the CLI entry point runs them with
`asyncio.run(...)`. See `src/king_context/scraper/cli.py`, which imports
`asyncio`, defines `async def run_pipeline`, and calls
`asyncio.run(run_pipeline(args, config))`.

Optional parameters on async functions are keyword-only, declared after `*`. See
`LLMClient.complete` in `src/llm_providers/base.py`:

```python
async def complete(
    self,
    prompt: str,
    *,
    system: str | None = None,
    json_mode: bool = True,
) -> dict[str, Any]:
```

HTTP uses `httpx.AsyncClient`.

## Error handling

Custom exceptions are defined per concern and subclass the most specific builtin
that fits:

- `ConfigError(Exception)` for missing or invalid configuration
  (`src/king_context/errors.py`).
- `ProviderError(Exception)` carries structured fields (`reason`, `transient`,
  `message`, `provider`, `primary_error`, `fallback_error`) plus a
  human-readable message built in `__init__` (`src/llm_providers/base.py`).
- `ProviderUnavailableError(RuntimeError)` carries `provider` and an actionable
  `hint`, never a raw `ImportError` traceback
  (`src/scraper_providers/base.py`).
- CLI-internal errors subclass `RuntimeError`, for example `AmbiguousDocError`
  in `src/context_cli/cli.py`.

Exceptions carry actionable hints; users never see a raw traceback.

At the CLI boundary, catch domain exceptions, print `error: <msg>` to
`sys.stderr`, and exit with a stable numeric code. Normal output goes to stdout;
user-facing error text goes to stderr.

Exit codes differ by entry point, so do not assume a single scheme:

| Entry point | Exit codes |
| --- | --- |
| `king-scrape` (`src/king_context/scraper/cli.py`) | `1` general failure, `2` for `ValueError`, `3` for `ProviderUnavailableError` |
| `kctx` (`src/context_cli/cli.py`) | `1` for every failure path it handles directly; `kctx ui` delegates and propagates the web server's code (which can be `2`) |

The scraper CLI maps the typed failures explicitly:

```python
except ProviderUnavailableError as exc:
    print(f"error: {exc.hint}", file=sys.stderr)
    sys.exit(3)
except ValueError as exc:
    print(f"error: {exc}", file=sys.stderr)
    sys.exit(2)
```

Every `sys.exit(...)` literal in `kctx` is `sys.exit(1)` (for example the
ambiguous-doc and not-found branches in `_cmd_read`,
`src/context_cli/cli.py`). The one place `kctx` surfaces another code is
`kctx ui`, which calls `sys.exit(web_main(argv))` and so propagates whatever the
web server's `main()` returns (it returns `2` on bind and port failures, see
`src/king_context/web/server.py`). The explicit `ValueError`-to-`2` and
`ProviderUnavailableError`-to-`3` mapping is unique to the scraper CLI: do not
add that exception-mapping convention elsewhere.

## Logging versus print

There are two conventions, split by package.

The research package uses the stdlib `logging` module. Each module declares a
module-level logger (`log = logging.getLogger(__name__)`, occasionally named
`logger`), and `main()` configures it once:

```python
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
```

See `src/king_context/research/cli.py`, plus the loggers in
`pipeline.py`, `deepen.py`, `fetch.py`, `queries.py`, `export.py`, `jina.py`,
and `exa.py`.

Every other package uses plain `print()` for user-facing progress and output,
and `print(..., file=sys.stderr)` for errors. The scraper CLI prints throughout
(`src/king_context/scraper/cli.py`), and `kctx` prints results and errors
directly (`src/context_cli/cli.py`). Note that `src/llm_providers/logging.py`
exists, but despite the filename it does not use the stdlib `logging` module: its
`log_fallback` helper emits a `[fallback]` line with `print()`. Verify the actual
mechanism in the package you are editing before adding output: outside
`research`, use `print` and match the surrounding style.

## Provider registry patterns

Pluggable providers are defined as `typing.Protocol` interfaces and registered
into private module-level factory dicts. See the
`@runtime_checkable` `DiscoveryProvider` and `FetchProvider` protocols in
`src/scraper_providers/base.py`, and the abstract `LLMClient(ABC)` with an
`@abstractmethod async def complete` in `src/llm_providers/base.py`.

Two rules govern registration in `src/scraper_providers/registry.py`:

- First-write-wins. `register_discovery_provider` and `register_fetch_provider`
  only set a name if it is not already present, so built-ins (registered eagerly)
  win over later third-party registrations.

  ```python
  def register_discovery_provider(name, factory) -> None:
      if name not in _DISCOVERY_FACTORIES:
          _DISCOVERY_FACTORIES[name] = factory
  ```

- Soft entry-point loading. `load_entry_point_providers` reads the
  `king_context.scraper_providers` entry-point group (declared in
  `pyproject.toml`) and wraps every step in `try/except`, skipping any provider
  that fails to load. A broken third-party provider must never break the import.

Stage-aware env resolution has a documented precedence in
`resolve_provider_name`: `SCRAPE_<STAGE>_PROVIDER`, then `SCRAPE_PROVIDER`, then
the hardcoded `firecrawl` default.

See [providers](../architecture/providers.md) for the full provider model.
