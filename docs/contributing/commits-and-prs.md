# Commits and pull requests

King Context is a CLI-first, local-first retrieval layer for AI agents. This
page covers how to write commit messages and pull requests that fit the
project history. For environment setup, forking, and the broader workflow, the
entry point is the root [CONTRIBUTING.md](../../CONTRIBUTING.md). This page does
not duplicate that setup.

## Commit messages

Commits follow [Conventional Commits](https://www.conventionalcommits.org/):

```txt
<type>(<scope>): <subject>

<optional body explaining the why>
```

Rules for the subject line:

- Written in **English**, like everything else in the repo.
- Imperative mood: "add", "fix", "drop", not "added" or "adds".
- No trailing period.
- Keep it short. Most subjects in the history sit well under 72 characters.

Use the optional body to explain *why* the change exists, not *what* changed.
The diff already shows what changed.

### Types

The history uses a small set of types. By frequency in recent commits:

| Type    | Used for                                            |
| ------- | --------------------------------------------------- |
| `feat`  | New user-facing capability                          |
| `fix`   | Bug fix, no new capability                          |
| `docs`  | Documentation only, no behavior change              |
| `chore` | Tooling, dependencies, version bumps, gitignore     |
| `test`  | Adding or adjusting tests                           |

`refactor` and `perf` are also valid Conventional Commit types and are listed
in [CONTRIBUTING.md](../../CONTRIBUTING.md), but the recent history leans on the
five above.

### Scopes

The scope names the part of the project the change touches. Scopes seen in the
history include:

| Scope        | Area                                                          |
| ------------ | ------------------------------------------------------------- |
| `scraper`    | `king-scrape` pipeline (`src/king_context/scraper/`)          |
| `installer`  | npm installer (`installer/`)                                  |
| `ui`         | Local UI server (`kctx ui`)                                   |
| `cli`        | `kctx` command surface (`src/context_cli/`)                   |
| `llm`        | LLM enrichment and filter stages                              |
| `providers`  | Pluggable scraper and LLM providers (`src/llm_providers/`)    |
| `adr`        | Architecture decision records (`.king-context/adr/`)          |
| `ci`         | GitHub Actions and test workflows                             |
| `release`    | Version bumps and release prep                                |

Other scopes appear when they read naturally (`db`, `research`, `readme`,
`changelog`, `gitignore`). Pick the smallest scope that describes the change.
The scope is optional in Conventional Commits, but the project history almost
always sets one.

### Examples

These are real subjects from the log:

```txt
feat(scraper): king-scrape audit subcommand for corpus drift
fix(scraper): drop invalid kwargs from audit discover provider lookup
fix(installer): include [all] extra in pip install
docs(adr): record pluggable llm provider decision
chore(release): bump to 0.4.0 with pluggable scraper provider
feat(cli): add llm doctor diagnostics
```

## Pull requests

Branch off `main`, keep the branch focused on one logical change, and open the
PR against `main`. The full workflow (fork, remote, running `pytest`) lives in
[CONTRIBUTING.md](../../CONTRIBUTING.md).

### Squash merge appends the PR number

PRs are squash-merged. The merge appends the PR number to the squashed subject,
so a merged commit looks like:

```txt
Unified scraper stack (#56)
feat(scraper): king-scrape audit subcommand for corpus drift (#49)
```

You do not need to add the `(#NN)` yourself. It comes from the squash merge.

### Keep PR bodies minimal

The repository fills in the
[PR template](../../.github/PULL_REQUEST_TEMPLATE.md), but in practice a good PR
body is short. For docs and chore PRs especially, two sections are enough:

```md
## Summary
One or two sentences on what this PR does and why.

## Scope
The files or areas it touches, and what it deliberately leaves out.
```

Larger feature or fix PRs add the template sections that matter (related issue,
how it was tested), but resist padding the body. Reviewers read the diff.

### Keep PR scope fixed

A PR should land one logical change. If you discover an unrelated bug or a
worthwhile improvement while working, do not fold it into the open PR. Open a
separate issue and route it there. This keeps diffs small, reviews fast, and the
squashed history readable.

## Hard rules for commits, PRs, issues, and comments

- **English only.** Commit messages, PR titles, PR bodies, issues, and review
  comments are all written in English. (The single repo-wide exception is the
  intentionally Portuguese `README-pt-br.md`, which does not apply here.)
- **No em-dashes or en-dashes.** Do not use the `U+2014` or `U+2013` characters
  anywhere in commits, PR bodies, issues, or comments. Use periods, commas,
  colons, or parentheses instead. This is a hard project rule.

## Related

- [CONTRIBUTING.md](../../CONTRIBUTING.md): setup, branching, and the full PR workflow.
- [Code style](code-style.md): language and typing conventions.
- [Testing](testing.md): how to run and write tests before opening a PR.
- [ADR workflow](adr-workflow.md): recording architecture decisions.
- [Skills](../skills.md): the Claude Code skills that automate these flows.
