---
id: ADR-0011
title: Crawl4AI selected as first local scraping backend
status: accepted
date: 2026-05-06
areas:
  - scraper
  - providers
  - dependencies
supersedes: []
superseded_by: []
related:
  - ADR-0004
  - ADR-0009
keywords:
  - crawl4ai
  - local-scraping
  - playwright
  - spa-rendering
  - trafilatura
  - opt-in
tags:
  - architecture
  - scraper
  - backend-choice
---



# ADR-0011: Crawl4AI selected as first local scraping backend

## Context

O ADR-0009 abre a porta pra ter múltiplos backends de scraping mas precisa eleger o primeiro motor local pra acompanhar o lançamento da feature. Os candidatos avaliados foram: Crawl4AI (Apache 2.0, Playwright-based, ~65k stars, ativo 2026), trafilatura (Apache 2.0, pure Python, ~5.9k stars, usado por HuggingFace e IBM Research), Scrapy + scrapy-playwright (mais boilerplate, gold standard pra crawls de milhões de páginas), e self-host de Firecrawl OSS (heavy: Redis + Node + Playwright + Docker, viola CLI-first do ADR-0001).

## Decision

Adotar Crawl4AI como primeiro motor local opt-in. Instalável via pip install king-context[crawl4ai] && crawl4ai-setup. Implementado como Crawl4AIScraperProvider em src/scraper_providers/crawl4ai_provider.py com soft import. Cobre tanto DiscoveryProvider (via deep crawl strategies) quanto FetchProvider (via AsyncWebCrawler.arun).

## Alternatives Considered

Trafilatura + httpx + crawler thin custom era a primeira recomendação durante a sessão de design, justificada pelo footprint leve (pure Python, sem browser binary, install <20MB) e excelente extração HTML→Markdown pra docs estáticas. Foi descartada porque cobertura de SPA/JS é dia-1 essencial pra ser uma alternativa de verdade ao Firecrawl, não meio-alternativa: Vercel docs, Mintlify customizado, e dashboards renderizados em React puro precisam de Playwright. Hybrid (trafilatura fast-path + Playwright fallback) seria caminho intermediário válido mas duplica trabalho que Crawl4AI já entrega numa stack só. Self-host Firecrawl OSS exige Redis + Node + Playwright + Docker e contraria o espírito CLI-first (ADR-0001). Scrapy é overkill pra docs scraping.

## Consequences

Install do modo local exige ~300MB de Chromium via crawl4ai-setup, aceitável porque o overhead só atinge quem ativamente opt-in (default Firecrawl não muda; usuário casual nunca paga esse custo). Multi-OS baseline (ADR-0004) é mantido: Crawl4AI funciona em macOS, Linux, Windows com Playwright. API churn entre minor versions de Crawl4AI exige version pin no pyproject.toml (crawl4ai>=0.8.5,<0.9) e um teste de fumaça em CI que indexe um site conhecido. Cobertura de SPA permite indexar docs modernas sem precisar de fallback pra Firecrawl. Trafilatura permanece candidata pra um futuro terceiro backend super-leve voltado pra static-only sites (roadmap v3 do ADR-0009).

## Links

.docs/PLUGGABLE-SCRAPER-PROVIDER-ARCHITECTURE.md,https://github.com/unclecode/crawl4ai,https://github.com/adbar/trafilatura
