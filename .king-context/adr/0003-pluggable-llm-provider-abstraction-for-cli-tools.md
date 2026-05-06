---
id: ADR-0003
title: Pluggable LLM provider abstraction for CLI tools
status: accepted
date: 2026-05-05
areas:
  - cli
  - llm-providers
  - scraper
  - research
supersedes: []
superseded_by: []
related:
  - ADR-0001
  - ADR-0009
keywords:
  - llm-provider
  - openrouter
  - ollama
  - cli-enrichment
  - stage-aware-config
  - fallback
tags:
  - architecture
  - llm
  - cli
---



# ADR-0003: Pluggable LLM provider abstraction for CLI tools

## Context

The scraper and research CLIs called OpenRouter directly from stage modules. That made local model use, Ollama deployments, provider-specific error handling, and future provider additions leak into scraper and research code.

## Decision

Introduce a top-level llm_providers package with a small LLMClient interface, stage-aware environment resolution, provider registry, OpenRouter and Ollama clients, robust JSON parsing, and one-way Ollama to OpenRouter fallback. Scraper and research stages remain responsible for prompts and schema validation while provider HTTP details live behind the abstraction.

## Alternatives Considered

Keep direct OpenRouter calls in each stage; add Ollama branches directly inside scraper and research modules; expose provider selection as per-command flags before proving the environment-driven MVP. These options either duplicate provider logic, weaken the CLI-first stage boundaries, or add command surface before the provider contract stabilizes.

## Consequences

Default OpenRouter behavior remains compatible, while configured CLI stages can use local or remote Ollama without MCP changes. Validation must stay stage-aware so partial pipelines do not require inactive credentials. Provider failures become explicit and testable, but the abstraction adds a new package and requires call-sites to depend on provider clients instead of raw HTTP.

## Links

.specs/features/local-models-enrichment/spec.md, .specs/features/local-models-enrichment/design.md
