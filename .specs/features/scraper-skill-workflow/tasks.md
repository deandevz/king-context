# Scraper Skill Workflow — Tasks

**Design**: `design.md`
**Status**: Complete

---

## Plano de Execução

### Fase 1: Flags do Scraper (Sequencial)

```
T1 → T2
```

### Fase 2: Resume Engine (Paralelo)

```
      ┌→ T3 [P] ─┐
T2 ──→┤           ├──→ T5
      └→ T4 [P] ─┘
```

### Fase 3: Testes de Integração (Sequencial)

```
T3, T4 ──→ T5
```

### Fase 4: Skill (Sequencial)

```
T5 ──→ T6 → T7
```

---

## Task Breakdown

### T1: Flags `--stop-after` e `--yes` no scraper CLI

**O que**: Adicionar as duas flags ao argparse e implementar a lógica no `run_pipeline()`.
**Onde**: `src/king_context/scraper/cli.py`
**Depende de**: Nada
**Requisito**: SW-05, SW-07

**Detalhes**:
- `--stop-after`: aceita um step name de `PIPELINE_STEPS`, adiciona `break` após o step executado
- `--yes`: pula o `input("Proceed?")` no bloco de enrichment
- Ambas as flags no `_build_parser()` + lógica no `run_pipeline()`

**Done when**:
- [ ] `king-scrape <url> --stop-after chunk` roda discover→filter→fetch→chunk e para
- [ ] `king-scrape <url> --stop-after fetch` roda discover→filter→fetch e para
- [ ] `king-scrape <url> --yes` pula confirmação de enrichment
- [ ] `king-scrape <url> --stop-after chunk --no-llm-filter` funciona em conjunto
- [ ] Flags aparecem em `king-scrape --help`
- [ ] Tests: ≥4 testes (stop-after variações, yes flag, combinações)

**Gate**: `pytest tests/test_scraper_cli_flags.py -v`

**Commit**: `feat(scraper): add --stop-after and --yes flags to king-scrape CLI`

---

### T2: Manifest com progresso parcial

**O que**: Atualizar manifest durante fetch e enrich (não só no final), permitindo que resume detecte onde parou.
**Onde**: `src/king_context/scraper/fetch.py`, `src/king_context/scraper/enrich.py`
**Depende de**: T1
**Requisito**: SW-06

**Detalhes**:
- `fetch.py`: após cada página baixada, atualizar manifest com `status: "in_progress"`, `completed: N`, `total: M`
- `enrich.py`: após cada batch, atualizar manifest com `status: "in_progress"`, `enriched: N`, `total: M`
- Status muda pra `"done"` só quando o step completa integralmente
- Não afeta lógica existente — só adiciona chamadas `_update_step()` intermediárias

**Done when**:
- [ ] Durante fetch, manifest mostra `{"status": "in_progress", "completed": 5, "total": 100}`
- [ ] Ao completar fetch, manifest mostra `{"status": "done", "completed": 100, "total": 100}`
- [ ] Durante enrich, manifest mostra `{"status": "in_progress", "enriched": 30, "total": 150}`
- [ ] Ao completar enrich, manifest mostra `{"status": "done", "enriched": 150, "total": 150}`
- [ ] Tests: ≥3 testes (progresso parcial fetch, progresso parcial enrich, transição pra done)

**Gate**: `pytest tests/test_scraper_manifest.py -v`

**Commit**: `feat(scraper): track partial progress in manifest during fetch and enrich`

---

### T3: Resume no Fetch [P]

**O que**: Fazer `fetch_pages()` pular URLs cujo arquivo .md já existe em `pages/`.
**Onde**: `src/king_context/scraper/fetch.py`
**Depende de**: T2 (precisa do manifest parcial pra detectar in_progress)
**Requisito**: SW-06

**Detalhes**:
- Antes de criar tasks async, coletar `existing_slugs = {f.stem for f in pages_dir.glob("*.md")}`
- Filtrar `pending_urls = [u for u in urls if _url_to_slug(u) not in existing_slugs]`
- Printar resumo: `"Resuming: X pages already fetched, Y remaining"`
- O `FetchResult` reporta total correto (incluindo os já existentes)

**Done when**:
- [ ] Se `pages/` tem 50 arquivos .md e há 200 URLs, fetch baixa só 150
- [ ] Print mostra "Resuming: 50 pages already fetched, 150 remaining"
- [ ] Se todas as páginas já existem, fetch completa instantaneamente
- [ ] `FetchResult.completed` inclui páginas pré-existentes + novas
- [ ] Tests: ≥4 testes (resume parcial, resume completo, sem resume, contagem correta)

**Gate**: `pytest tests/test_scraper_fetch_resume.py -v`

**Commit**: `feat(scraper): add resume support to fetch — skip already downloaded pages`

---

### T4: Resume no Enrich [P]

**O que**: Fazer `enrich_chunks()` pular chunks já enriquecidos baseado nos batch checkpoints.
**Onde**: `src/king_context/scraper/enrich.py`
**Depende de**: T2 (precisa do manifest parcial)
**Requisito**: SW-06

**Detalhes**:
- Ao iniciar, checar `enriched/` por batch files existentes
- Carregar último batch → contar chunks já enriquecidos
- Pular esses chunks: `chunks = chunks[already_enriched:]`
- Novos batches continuam a numeração (se último é `batch_0003.json`, próximo é `batch_0004.json`)
- Checkpoint cumulativo: cada batch contém TODOS os enriched até então

**Done when**:
- [ ] Se enriched/ tem batch_0002.json com 30 chunks e total é 150, enrich processa 120 restantes
- [ ] Novo batch começa em batch_0003.json
- [ ] Batch final contém todos os 150 chunks
- [ ] Print mostra "Resuming: 30/150 chunks already enriched"
- [ ] Se todos já estão enriquecidos, retorna lista completa sem API calls
- [ ] Tests: ≥4 testes (resume parcial, resume completo, sem resume, numeração correta)

**Gate**: `pytest tests/test_scraper_enrich_resume.py -v`

**Commit**: `feat(scraper): add resume support to enrich — skip already processed batches`

---

### T5: Teste de integração do resume end-to-end

**O que**: Testar que o pipeline completo funciona com resume — interromper e retomar.
**Onde**: `tests/test_scraper_resume_integration.py`
**Depende de**: T3, T4
**Requisito**: SW-06

**Detalhes**:
- Simular um scrape interrompido: criar work_dir com manifest parcial + alguns arquivos
- Rodar `run_pipeline()` e verificar que retoma de onde parou
- Testar fetch resume + enrich resume juntos
- Mockar Firecrawl e OpenRouter (não fazer chamadas reais)

**Done when**:
- [ ] Teste simula fetch interrompido (40/100 páginas) → resume baixa 60
- [ ] Teste simula enrich interrompido (30/80 chunks) → resume enriquece 50
- [ ] Teste simula pipeline completo com resume → export gera JSON correto
- [ ] Tests: ≥3 testes (fetch resume, enrich resume, full pipeline resume)

**Gate**: `pytest tests/test_scraper_resume_integration.py -v`

**Commit**: `test(scraper): add integration tests for pipeline resume`

---

### T6: Skill do Scraper Workflow

**O que**: Criar a skill que ensina Claude Code a orquestrar o fluxo completo de scraping.
**Onde**: `.claude/skills/scraper-workflow/skill.md`
**Depende de**: T5 (todos os componentes do scraper devem estar prontos)
**Requisito**: SW-01, SW-02, SW-03, SW-04, SW-08

**Detalhes**:
A skill documenta:
- Triggers e quando ativar
- Resolução de URL (web search ou perguntar)
- Detecção de resume (checar .temp-docs/)
- Workflow A (OpenRouter) — passo a passo
- Workflow B (Claude Code sub-agents) — passo a passo
- Prompt exato pro sub-agent Sonnet (filter)
- Prompt exato pro sub-agent Haiku (enrichment)
- Formato dos dados de checkpoint (contrato)
- Validação e retry dos sub-agents
- Error handling
- Exemplos de uso

**Done when**:
- [ ] Skill tem triggers claros
- [ ] Workflow A documentado com comandos exatos
- [ ] Workflow B documentado com cada passo e prompts dos sub-agents
- [ ] Resolução de URL (busca ou pergunta)
- [ ] Detecção de resume documentada
- [ ] Contrato de dados (formato de checkpoint) explícito
- [ ] Validação de metadata documentada (5-12 keywords, 2-7 use_cases, etc)
- [ ] Error handling documentado
- [ ] Batch sizes definidos (50 URLs pro Sonnet, 5-8 chunks pro Haiku)

**Gate**: Revisão manual

**Commit**: `feat(skill): add scraper-workflow skill with dual-mode orchestration`

---

### T7: Registrar skill e atualizar STATE.md

**O que**: Registrar a nova skill no sistema, atualizar estado do projeto.
**Onde**: `.specs/project/STATE.md`, `CLAUDE.md` (se necessário)
**Depende de**: T6
**Requisito**: Documentação

**Done when**:
- [ ] STATE.md atualizado com decisões e status
- [ ] CLAUDE.md referencia a nova skill se necessário
- [ ] Skill aparece na lista de skills disponíveis

**Gate**: Revisão manual

**Commit**: `docs: update project state and register scraper-workflow skill`

---

## Mapa de Execução Paralela

```
Fase 1 (Sequencial):
  T1 ──→ T2

Fase 2 (Paralelo):
  T2 complete, then:
    ├── T3 [P]  (fetch resume)
    └── T4 [P]  (enrich resume)    } Rodam simultâneo

Fase 3 (Sequencial):
  T3, T4 complete, then:
    T5 (integration tests)

Fase 4 (Sequencial):
  T5 ──→ T6 (skill) ──→ T7 (docs)
```

---

## Checklist de Granularidade

| Task | Escopo | Status |
|------|--------|--------|
| T1: Flags CLI | 1 arquivo, 2 flags | ✅ Done |
| T2: Manifest parcial | 2 arquivos, chamadas extras | ✅ Done |
| T3: Fetch resume | 1 arquivo, ~15 linhas | ✅ Done |
| T4: Enrich resume | 1 arquivo, ~20 linhas | ✅ Done |
| T5: Integration tests | 1 arquivo de testes | ✅ Done |
| T6: Skill | 1 arquivo .md | ✅ Done |
| T7: Docs update | 2 arquivos, atualizações leves | ✅ Done |

---

## Cobertura de Requisitos

| Requisito | Descrição | Tasks | Status |
|-----------|-----------|-------|--------|
| SW-01 | Scrape por URL | T6 | Coberto |
| SW-02 | Scrape por nome | T6 | Coberto |
| SW-03 | Enrichment sub-agents Haiku | T6 | Coberto |
| SW-04 | Filter sub-agent Sonnet | T6 | Coberto |
| SW-05 | Flag --stop-after | T1 | Coberto |
| SW-06 | Resume pipeline | T2, T3, T4, T5 | Coberto |
| SW-07 | Flag --yes | T1 | Coberto |
| SW-08 | Workflow completo na skill | T6 | Coberto |

**Cobertura**: 8/8 requisitos mapeados ✅

---

## Diagrama × Dependências — Cross-check

| Task | Depende de (body) | Diagrama mostra | Status |
|------|-------------------|-----------------|--------|
| T1 | Nada | Start | ✅ Match |
| T2 | T1 | T1 → T2 | ✅ Match |
| T3 | T2 | T2 → T3 [P] | ✅ Match |
| T4 | T2 | T2 → T4 [P] | ✅ Match |
| T5 | T3, T4 | T3,T4 → T5 | ✅ Match |
| T6 | T5 | T5 → T6 | ✅ Match |
| T7 | T6 | T6 → T7 | ✅ Match |
