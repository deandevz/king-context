# King Context Documentation

In-repo wiki for King Context. Pages live next to the code so they version with it.

## Overview

- [Architecture](architecture.md): how the pipelines, the CLI, and the stores fit together.
- [Vision](vision.md): what the project is, where it is going, and the design ideas behind it.
- [Roadmap](roadmap.md): short-term and long-term plans.

## Using King Context

- [CLI guide](CLI_GUIDE.md): `kctx`, `king-scrape`, and `king-research` commands and flags.
- [Local UI](ui-local.md): browse ADRs, docs, and research in a local web UI.
- [Ollama guide](ollama.md): install Ollama and configure beta local model support.
- [Skills](skills.md): the Claude Code skills shipped by the installer.
- [Benchmarks](benchmarks.md): performance numbers vs Context7.

## Architecture deep dives

- [Overview: the two retrieval stacks](architecture/overview.md)
- [CLI retrieval](architecture/cli-retrieval.md)
- [Scraper pipeline](architecture/scraper-pipeline.md)
- [Research pipeline](architecture/research-pipeline.md)
- [Providers](architecture/providers.md)
- [Local UI](architecture/local-ui.md)
- [Legacy MCP stack](architecture/mcp-legacy.md)

## Reference

- [Corpus JSON schema](reference/corpus-schema.md): the format corpus packages must follow.
- [Environment variables](reference/env-vars.md): every env var, its default, and where it is read.
- [Storage layout](reference/storage-layout.md): the `.king-context/` tree and the legacy repo-root store.

## Contributing

- [Contributing guide](../CONTRIBUTING.md): setup, branching, PR flow.
- [Code style](contributing/code-style.md)
- [Testing](contributing/testing.md)
- [Commits and PRs](contributing/commits-and-prs.md)
- [ADR workflow](contributing/adr-workflow.md)
- [Code of Conduct](../CODE_OF_CONDUCT.md)
- [Pull request template](../.github/PULL_REQUEST_TEMPLATE.md)
- [Issue templates](../.github/ISSUE_TEMPLATE/)

## Agent guidance

- [`AGENTS.md`](../AGENTS.md): canonical rules for AI agents working in this repo.
- [`CLAUDE.md`](../CLAUDE.md): Claude-Code-specific additions on top of AGENTS.md.
- [`BENCHMARK.md`](../BENCHMARK.md): benchmark methodology and rubrics.
