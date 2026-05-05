# Resumo da Implementacao

Implementado o provider layer `src/llm_providers/` com `LLMClient`, parser JSON robusto, config por stage, registry, clientes OpenRouter/Ollama, fallback Ollama -> OpenRouter e testes. `king-scrape` e `king-research` agora usam providers em enrichment, filtro LLM e geracao de queries.

Tambem foram adicionados `kctx llm-doctor`, hook no doctor Node, ADR-0003, env/docs/skills atualizados, `docs/ollama.md` com passo a passo de instalacao/configuracao, e custo de enrichment provider-aware: OpenRouter mostra estimativa em dolares; Ollama-only mostra custo local/runtime; Ollama com fallback avisa sobre possivel custo OpenRouter.

Depois do smoke do installer, tambem foi centralizado o carregamento de env em `src/king_context/env.py`: `.king-context/.env` e `.env` agora sao lidos por `king-scrape`, `king-research`, providers LLM e `kctx llm-doctor`. Isso evita precisar exportar variaveis manualmente dentro da venv.

## Ollama

Pesquisa usada: docs oficiais do Ollama para OpenAI compatibility, native chat, tags e autenticacao:
https://docs.ollama.com/api/openai-compatibility, https://docs.ollama.com/api/chat, https://docs.ollama.com/api/tags, https://docs.ollama.com/api/authentication.

- Nesta maquina: Ollama `0.23.0` instalado via Homebrew, servico iniciado com `brew services start ollama`, modelo `qwen2.5:7b` baixado e listado localmente (`4.7 GB`).
- Teste manual do usuario: `king-research` com Ollama local comecou a chunkear/enriquecer corretamente e gerou arquivo em `.king-context/_temp/research/.../enriched/batch_0001.json`.
- Cobertura manual: foi testado somente Ollama local. Ollama Cloud/native ainda nao foi testado na pratica.
- Status comunicado como beta em `kctx llm-doctor`, `docs/index.md`, `docs/CLI_GUIDE.md` e `docs/ollama.md`. Usuarios devem abrir issues com bugs ou validacoes de modelos locais que cheguem perto da qualidade do Gemini via OpenRouter.
- OpenAI local: `OLLAMA_API_MODE=openai`, `OLLAMA_BASE_URL=http://localhost:11434/v1`, endpoint `POST /chat/completions`, doctor `GET /models`.
- Native/cloud: `OLLAMA_API_MODE=native`, `OLLAMA_BASE_URL=https://ollama.com`, endpoint `POST /api/chat`, doctor `GET /api/tags`, `stream: false`, `format: "json"`.
- `OLLAMA_API_KEY` e enviado como `Authorization: Bearer ...` quando definido.

## Desvios/Notas

- O binario `.king-context/bin/kctx` nao existe neste checkout local; usei `python -m context_cli.cli ...` para ADR/doctor durante a validacao.
- O teste manual real de scrape com Ollama local nao foi executado para evitar consumir tempo de inferencia; o doctor real contra o servidor Ollama local passou. A cobertura automatizada mocka os endpoints e valida o formato das chamadas.
- `--model` no parser agora fica `None` quando omitido, para permitir que `ENRICH_MODEL` do ambiente seja respeitado. Quando passado, continua sobrescrevendo o modelo de enrichment.
- O `king-context init` do npm instala o pacote Python via `git+https://github.com/deandevz/king-context.git`. Para deploy, publique/merge as mudancas Python no GitHub antes ou junto do publish npm; se o GitHub remoto estiver antigo, o npm novo instala templates novos mas a venv fica sem `kctx llm-doctor`.

## Correcoes Pos-Review

- `king-research` nao herda mais `ENRICH_MODEL` para geracao de queries. Quando `RESEARCH_MODEL` nao esta definido, o stage `research` usa sua propria resolucao/default em `resolve("research")`.
- O enrichment nao engole mais `ProviderError`. Se Ollama falha e o fallback OpenRouter tambem falha, o erro do `FallbackClient` sobe preservando `primary_error` e `fallback_error`, em vez de transformar o chunk em `None` silenciosamente.
- O filtro LLM de URLs tambem nao engole mais falhas provider-aware. `ConfigError` e `ProviderError` vindos de `_call_llm` sobem para a CLI, entao configuracoes invalidas de `FILTER_PROVIDER` ou falhas de Ollama/OpenRouter ficam visiveis em vez de cair silenciosamente no resultado heuristico.
- O enrichment agora retenta `ProviderError` transiente ate 3 tentativas no primary. Timeouts, rate limits e erros 5xx de OpenRouter ou Ollama nao abortam o batch na primeira falha; erros nao transientes continuam falhando imediatamente.
- O fallback Ollama -> OpenRouter agora respeita concorrencia por provider. Quando `CONCURRENCY_OLLAMA` e maior que `CONCURRENCY_OPENROUTER`, chamadas de fallback para OpenRouter ficam protegidas pelo semaforo do OpenRouter, nao pelo limite do primary.
- A factory de providers agora resolve `CONCURRENCY_OPENROUTER` tambem para o cliente OpenRouter usado como fallback, em vez de usar um valor fixo.
- Erros combinados do `FallbackClient` agora usam a transiencia do erro do fallback. Se Ollama falha de forma transiente, mas OpenRouter falha com erro nao transiente, como `auth_error`, o caller falha imediatamente em vez de retentar uma configuracao invalida.
- O schema fallback do enrichment tambem nao engole mais metadados invalidos. Se Ollama falha validacao 3 vezes e o fallback OpenRouter retorna JSON parseavel mas fora do schema, o enrichment levanta `ProviderError(reason="validation_failed_3x")` em vez de descartar o chunk silenciosamente.
- Testes de regressao cobrem isolamento do modelo de research, surfacing dos erros combinados de fallback, surfacing de falhas de config/provider no filtro LLM, retry de erros transientes no enrichment, erro apos 3 tentativas, fail-fast para fallback nao transiente, concorrencia do OpenRouter em fallback e falha explicita quando o schema fallback tambem retorna metadados invalidos.

## Validacao

- `pytest` -> `466 passed`
- `pytest tests/test_scraper/test_enrich.py` -> `11 passed`
- `pytest tests/test_llm_providers/test_fallback.py tests/test_scraper/test_enrich.py` -> `15 passed`
- `pytest tests/test_llm_providers tests/test_scraper tests/test_scraper_manifest.py tests/test_scraper_enrich_resume.py tests/test_scraper_resume_integration.py` -> `96 passed`
- `python -m context_cli.cli adr status` -> index up to date
- `python -m context_cli.cli adr validate` -> passed
- `python -m context_cli.cli llm-doctor --json` -> `{"ollama": null}` quando nenhum stage usa Ollama
- `ENRICH_PROVIDER=ollama ENRICH_MODEL=qwen2.5:7b OLLAMA_API_MODE=openai OLLAMA_BASE_URL=http://localhost:11434/v1 CONCURRENCY_OLLAMA=1 python -m context_cli.cli llm-doctor --json` -> reachable, model present
- Smoke installer em `/private/tmp/kctx-installer-smoke...`: `npm pack --dry-run` OK; `king-context init` OK; venv com arvore local pos-merge; `.env` com Ollama local; `.king-context/bin/kctx llm-doctor --json` -> reachable/model present; `king-context doctor` -> `16 passed, 0 warnings, 0 failed`.

## Teste Rapido na Pratica

1. Local Ollama:

```bash
ollama pull qwen2.5:7b
ENRICH_PROVIDER=ollama ENRICH_MODEL=qwen2.5:7b OLLAMA_API_MODE=openai OLLAMA_BASE_URL=http://localhost:11434/v1 python -m context_cli.cli llm-doctor --json
```

2. Scrape pequeno ate enrichment:

```bash
ENRICH_PROVIDER=ollama ENRICH_MODEL=qwen2.5:7b OLLAMA_API_MODE=openai OLLAMA_BASE_URL=http://localhost:11434/v1 king-scrape https://docs.example.com --name smoke --stop-after enrich --yes --no-llm-filter
```

3. Fallback:

```bash
ENRICH_PROVIDER=ollama ENRICH_MODEL=modelo-inexistente ENABLE_FALLBACK=true OPENROUTER_API_KEY=... king-scrape https://docs.example.com --name smoke-fallback --stop-after enrich --yes --no-llm-filter
```

Procure uma linha como:

```text
[fallback] enrich: ollama (...) -> openrouter (...) -- reason: model_not_found
```
