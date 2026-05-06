---
id: ADR-0009
title: Pluggable scraper provider abstraction for king-scrape
status: accepted
date: 2026-05-06
areas:
  - cli
  - scraper
  - providers
  - plugin-system
supersedes: []
superseded_by: []
related:
  - ADR-0001
  - ADR-0003
  - ADR-0010
  - ADR-0011
keywords:
  - scraper-provider
  - registry
  - stage-aware
  - soft-import
  - python-extras
  - entry-points
tags:
  - architecture
  - scraper
  - providers
---





# ADR-0009: Pluggable scraper provider abstraction for king-scrape

## Context

O king-scrape (CLI de indexação de documentação) chama Firecrawl SaaS diretamente nas etapas discover (src/king_context/scraper/discover.py) e fetch (src/king_context/scraper/fetch.py). Essa dependência fechada contradiz o posicionamento local-first do produto declarado em ADR-0001 e cria fricção pra adoção (FIRECRAWL_API_KEY obrigatória antes de indexar a primeira documentação). ADR-0003 já estabeleceu o padrão pra LLMs (cloud default + local opt-in via abstração de provider via OpenRouter e Ollama). Falta o equivalente pra scraping.

## Decision

Criar package src/scraper_providers/ análogo ao src/llm_providers/ com Protocols separados (DiscoveryProvider, FetchProvider), registry com soft import via Python extras (pip install king-context[crawl4ai]), e stage-aware env resolution: SCRAPE_PROVIDER (global), SCRAPE_DISCOVER_PROVIDER e SCRAPE_FETCH_PROVIDER (override por stage). Suportar entry_points group king_context.scraper_providers pra plugin model futuro. Firecrawl continua como default zero-config; novos backends viram opcionais selecionáveis sem refactor de pipeline.

## Alternatives Considered

Dispatcher inline em cada stage (if provider == firecrawl: else: ...) economiza código hoje (50 linhas vs 200) mas inviabiliza plugin model via entry_points sem refactor posterior, fragmenta tratamento de soft import (ImportError precisa ser catalogado em cada stage), e perde simetria com src/llm_providers/ (custo cognitivo extra pra contributors). Provider único cobrindo discover+fetch (sem stage-aware) é mais simples conceitualmente mas inviabiliza mixing genuíno entre etapas (ex: crawl4ai discover de SPA + firecrawl fetch estável).

## Consequences

Novos backends de scraping são adicionados como módulos isolados com soft import e registro automático via entry_points. Stage-aware resolution permite mixing por etapa. Install via Python extras prepara terreno pra futuro kctx plugin install (CLI interativa) sem refactor estrutural: vira wrapper amigável em cima do mecanismo de extras + entry_points. discover.py e fetch.py passam a depender das Protocols em vez de FirecrawlApp diretamente; tests existentes precisam adaptar mocks (passar provider via param em vez de patchar SDK). Sem env var setada, comportamento default permanece idêntico ao atual (zero breaking change).

## Links

.docs/PLUGGABLE-SCRAPER-PROVIDER-ARCHITECTURE.md,src/llm_providers/
