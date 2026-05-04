# Contributing to King Context

Thanks for your interest in improving King Context. This document explains how to set up the project locally, the standards we follow, and the workflow for getting changes merged.

By participating, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

---

## Where to start

The three areas where the project benefits the most from outside help:

1. **Corpus packages** — scrape an API or research a topic and open a PR with the enriched JSON. A community library of pre-enriched corpora is the project's biggest lever.
2. **Pipeline reliability** — edge cases in URL discovery, chunking, JavaScript-rendered pages, or source filtering in `king-research`.
3. **Skill improvements** — sub-agent reliability, error handling, parallel enrichment in the Claude Code skills.

If unsure where to start, browse [open issues](https://github.com/deandevz/king-context/issues) labeled `good first issue` or `help wanted`, or open a discussion describing what you want to work on.

---

## Project standards

### Language

- All code, comments, variable names, function names, and documentation must be in **English**.
- Git commit messages and PR descriptions must be in **English**.
- Architecture docs and design notes can be in Portuguese when scoped that way, but never mix languages inside the same file.

### Code style

- Python: follow the existing style in `src/` (PEP 8, type hints where helpful, no broad `except` clauses without a reason).
- Shell scripts: POSIX-compatible when possible, `#!/usr/bin/env bash` otherwise.
- Keep changes focused. A bug fix should not include unrelated refactors. A refactor should not change behavior.
- Prefer editing existing files over creating new ones unless a new module is clearly needed.

### Tests

- Tests live in `tests/`. Use `pytest`.
- Add or update tests when fixing a bug or adding a feature. Tests should fail before your fix and pass after.
- See `tests/conftest.py` for shared fixtures and patterns.

---

## Local development setup

### 1. Fork and clone

```bash
git clone git@github.com:<your-username>/king-context.git
cd king-context
git remote add upstream git@github.com:deandevz/king-context.git
```

### 2. Create a virtual environment and install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. Configure environment variables

```bash
cp .env.example .env
# Fill in FIRECRAWL_API_KEY, EXA_API_KEY, OPENROUTER_API_KEY as needed
```

### 4. Seed the database (optional, for MCP work)

```bash
python -m king_context.seed_data
```

### 5. Run the test suite

```bash
pytest
```

For more detail on the codebase, see [`CLAUDE.md`](CLAUDE.md) and the [architecture overview](docs/architecture.md).

---

## Branching and commits

### Branch names

Use a short, descriptive prefix:

- `feat/<short-name>` — new feature
- `fix/<short-name>` — bug fix
- `docs/<short-name>` — documentation only
- `refactor/<short-name>` — internal cleanup, no behavior change
- `chore/<short-name>` — tooling, dependencies, build

Example: `feat/parallel-enrichment`, `fix/cache-collision`.

### Commit messages

The project follows [Conventional Commits](https://www.conventionalcommits.org/):

```txt
<type>(<scope>): <short description>

<optional longer body explaining the why>
```

Common types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`.
Common scopes: `cli`, `mcp`, `scraper`, `research`, `installer`, `skill`, `db`, `docs`, `tests`.

Examples:

```txt
feat(scraper): add JavaScript rendering fallback
fix(db): handle empty FTS query without raising
docs(readme): trim quick start, link to docs/architecture
```

Keep the subject under ~72 characters. Use the body to explain *why*, not *what* (the diff already shows what).

---

## Pull request workflow

1. **Discuss first for large changes.** Open an issue or a discussion before starting on anything that takes more than a couple of hours. Saves rework.
2. **Branch off `main`.** Keep your branch focused on one logical change.
3. **Run tests locally.** `pytest` should pass before you push.
4. **Open the PR against `main`.** Fill in the [PR template](.github/PULL_REQUEST_TEMPLATE.md) — summary, related issue, type, how it was tested, checklist.
5. **Be responsive to review.** Push follow-up commits on the same branch. Squash on merge is fine; we will handle that.
6. **Sign-off is not required**, but `Co-Authored-By` trailers for pair work are welcome.

### What makes a PR easy to merge

- Small, focused diff.
- Clear motivation in the description (link the issue, explain the why).
- Tests that fail before and pass after, when applicable.
- Documentation updated when behavior changes.
- No unrelated formatting or refactor noise.

---

## Reporting bugs

Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md). Include:

- King Context version or commit SHA
- Install method, OS, Python and Node versions
- Exact steps to reproduce
- Expected vs actual behavior
- Logs, stack traces, or output

---

## Suggesting features

Use the [feature request template](.github/ISSUE_TEMPLATE/feature_request.md). Lead with the *problem*, then propose a solution. Alternatives considered help reviewers understand your reasoning.

For broad direction questions ("should King Context do X?"), open a discussion instead of an issue.

---

## Security

If you find a security issue, do **not** open a public issue. Email the maintainers at `bruucetscontact@gmail.com` with details. We will respond and coordinate disclosure.

---

## Questions

- **Open-ended questions:** [GitHub Discussions](https://github.com/deandevz/king-context/discussions)
- **Bugs:** [Issues](https://github.com/deandevz/king-context/issues)
- **Conduct concerns:** `bruucetscontact@gmail.com`

Thanks again for contributing.
