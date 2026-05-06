---
id: ADR-0010
title: Thin scraper provider with pipeline-owned concurrency, checkpoint, and IO
status: accepted
date: 2026-05-06
areas:
  - scraper
  - providers
  - performance
supersedes: []
superseded_by: []
related:
  - ADR-0009
keywords:
  - thin-provider
  - pipeline-owned
  - semaphore
  - checkpoint
  - resume
  - fetch-one
  - trade-off
tags:
  - architecture
  - scraper
  - providers
---


# ADR-0010: Thin scraper provider with pipeline-owned concurrency, checkpoint, and IO

## Context

Ao desenhar a abstração de scraper provider (ADR-0009), surgiu a escolha de onde manter concorrência, checkpoint, e gravação de .md em disco. fetch.py (src/king_context/scraper/fetch.py:53) já implementa um semaphore de concorrência (default 5, configurável via config.concurrency), resume por slug, retry com backoff, e gravação por página em .king-context/_temp/<host>/pages/<slug>.md. Esse código está em produção e testado. Cada provider candidato (Crawl4AI, Firecrawl) traz suas próprias capacidades de batching e throttling adaptativo.

## Decision

Manter as Protocols mínimas: FetchProvider expõe apenas async fetch_one(url) -> PageContent, e DiscoveryProvider expõe apenas async discover_urls(base_url) -> list[str]. Toda a lógica de semaphore, checkpoint slug-based, retry, e gravação .md continua no fetch.py (pipeline-owned). Gravação do discovered_urls.json continua no discover.py. Providers são finos: convertem 1 URL em 1 PageContent.

## Alternatives Considered

Provider gordo (cada backend implementa fetch_many com sua própria concorrência/checkpoint/IO) extrairia max performance específica de cada engine: Crawl4AI tem AdaptiveDispatcher que ajusta concurrency baseado em latência observada, Firecrawl SDK tem rate-limit handling automático. Foi descartado porque (a) duplica lógica de IO entre backends, (b) fragmenta resume semantics: trocar provider no meio de um run não retomaria do checkpoint anterior se cada um gravasse de um jeito, (c) complica testes (mock de filesystem por backend), (d) atrasa MVP. Híbrido (fetch_one mandatório + fetch_many opcional com default vindo de fetch_one paralelo) é a evolução natural se otimização virar gargalo medido.

## Consequences

Output em disco é idêntico independente do backend, contrato esperado de uma abstração de provider. Resume cross-provider funciona: URLs já baixadas com Firecrawl não são re-baixadas se o usuário trocar pra Crawl4AI no meio. Tests de provider isolam em PageContent retornado, sem mockar filesystem. Trade-off explícito: throttling adaptativo de cada backend não é usado; ambos compartilham a semaphore default de 5 concurrent. Se isso virar gargalo medido na prática, a evolução é local (não estrutural): adicionar método fetch_many opcional ao Protocol, providers podem fazer override quando vale a pena, default permanece o loop de fetch_one paralelo. Decisão consciente de ship-now > otimizar.

## Links

.docs/PLUGGABLE-SCRAPER-PROVIDER-ARCHITECTURE.md,src/king_context/scraper/fetch.py
