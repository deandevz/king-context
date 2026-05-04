# King Context

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![npm](https://img.shields.io/npm/v/@king-context/cli?label=installer&color=blue)](https://www.npmjs.com/package/@king-context/cli)
[![Status](https://img.shields.io/badge/status-active-brightgreen.svg)](https://github.com/deandevz/king-context)

Uma camada de retrieval pra agentes de IA. Local first, eficiente em tokens, open source.

Versão em inglês: [README.md](README.md).

---

Agente trabalha melhor quando vê o contexto certo, não tudo. O King Context indexa qualquer corpus que você passar (documentação de produto, pesquisa na web aberta, notas internas, decisões arquiteturais) e devolve pro agente exatamente a fatia que ele precisa. Cada seção recebe metadados estruturados, então o agente busca antes de ler, faz preview antes de puxar o conteúdo completo, e nunca queima o orçamento de contexto num despejo de arquivos.

## Início rápido

```bash
npx @king-context/cli init
```

Isso configura `.king-context/` em qualquer projeto: ambiente virtual Python, ferramentas CLI, skills de agente e templates de configuração. Zero setup manual.

Adicione suas chaves:

```bash
cp .king-context/.env.example .env
# FIRECRAWL_API_KEY=...     scraping
# EXA_API_KEY=...           pesquisa
# OPENROUTER_API_KEY=...    opcional, enriquecimento automatizado
```

Monte um corpus a partir de um site de docs ou de um tópico:

```bash
king-scrape https://docs.stripe.com --name stripe --yes
king-research "prompt engineering techniques" --high --yes
```

Depois busque e leia:

```bash
kctx list
kctx search "authentication" --doc stripe
kctx read stripe authentication --preview     # ~400 tokens
kctx read stripe authentication                # seção completa
kctx grep "Bearer" --doc stripe --context 3
```

Ou conduza pelo agente que você preferir. A CLI é shell native, então qualquer agente que executa comandos consegue usar. As skills hoje são pro Claude Code, com suporte ao Codex e um formato portável de skill no roadmap.

Referência completa de comandos em [`docs/CLI_GUIDE.md`](docs/CLI_GUIDE.md).

## O que você ganha

**Scrape de qualquer site de docs.** O `king-scrape` descobre páginas, baixa, divide em chunks e enriquece cada chunk com keywords, casos de uso, tags e prioridade.

**Pesquisa de qualquer tópico.** O `king-research` puxa fontes da web aberta via Exa, divide em chunks e indexa o resultado do mesmo jeito. Os níveis de esforço vão de `--basic` (~30 fontes) até `--extrahigh`.

**Busca sem despejo.** Busca por metadados retorna em milissegundos de um dígito. O agente faz preview de uns 400 tokens antes de puxar a seção completa. Um cache de queries aprende os caminhos comuns e colapsa repetições pra leituras sub-milissegundo.

**Retrieval que evolui sozinho.** Os agentes escrevem atalhos `.king-context/_learned/<corpus>.md` enquanto trabalham, mapeando perguntas comuns pra caminhos exatos de seção. A próxima sessão pula a fase de busca. O cache se aquece sozinho.

**Memória de decisões arquiteturais.** O `kctx adr` registra decisões do projeto como ADRs e indexa elas junto com docs e pesquisa. Os agentes consultam o log de decisões antes de mudar arquitetura, então o contexto sobrevive entre sessões e contribuidores.

**Uma superfície de retrieval, vários corpus.** Documentação de produto, varreduras de pesquisa, runbooks internos e ADRs, tudo acessível pelas mesmas primitivas da CLI.

## Como funciona

Cada seção de cada página coletada ou fonte pesquisada termina anotada assim:

```json
{
  "keywords": ["api-key", "bearer-token", "authentication"],
  "use_cases": ["Configure API authentication", "Rotate API keys"],
  "tags": ["security", "setup"],
  "priority": 10
}
```

O agente compara a query com keywords, casos de uso e tags primeiro. Sem scan de texto completo, sem similaridade vetorial em uns 90% das consultas. Ele só lê o conteúdo quando os metadados dizem que vale, e faz preview antes de ler tudo.

Esses metadados estruturados são o coração da ideia. São eles que fazem progressive disclosure funcionar sem perder recall, e são eles que deixam a mesma máquina servir um site de docs de produto, uma varredura de pesquisa na web e o próprio log de decisões do projeto.

## Benchmarks

Dois rounds contra o Context7, a ferramenta de documentação mais usada por agentes de código hoje.

### Round 1: MCP vs MCP

| Métrica | King Context | Context7 | Melhoria |
|---|---|---|---|
| Média de tokens por query | 968 | 3.125 | 3.2x menos |
| Latência (acerto em metadata) | 1.15ms | 200 a 500ms | 170x mais rápido |
| Latência (full text search) | 97.83ms | 200 a 500ms | 2 a 5x mais rápido |
| Resultados duplicados | 0 | 11 | zero desperdício |
| Relevância | 3.2 / 5 | 2.8 / 5 | +14% |
| Implementabilidade | 4.4 / 5 | 4.0 / 5 | +10% |

### Round 2: skill vs skill

As duas ferramentas conduzidas pelo mesmo agente (Opus 4.7) através de CLI mais skill, nas docs da Gemini API.

| Métrica | Context7 | King Context |
|---|---|---|
| Média de tokens por query | ~1.896 | ~1.064 |
| Mediana de tokens por query | 1.750 | 901 |
| Fatos corretos | 32 / 38 (84%) | 38 / 38 (100%) |
| Alucinações por query | 0.33 | 0.0 |
| Qualidade composta (0 a 5) | 3.46 | 4.79 |

O recado: progressive disclosure mais metadados estruturados dão ao agente checkpoints pra voltar atrás, recusar alucinação e mostrar várias versões do mesmo parâmetro. Similaridade semântica sozinha não consegue.

Metodologia e dados brutos em [BENCHMARK.md](BENCHMARK.md). Análise por round e discussão em [docs/benchmarks.md](docs/benchmarks.md).

## Pra onde isso vai

**Registro comunitário.** Quem fizer scrape de uma lib ou pesquisa de um tópico vai poder publicar o corpus enriquecido. As outras pessoas instalam com um comando:

```bash
kctx install stripe@v1
kctx install prompt-engineering-2026
```

Versionado, pré-enriquecido, atualizado. Documentação de produto é ponto de partida, não teto.

**Skills especialistas a partir de corpus.** Da pra alimentar um agente com um corpus indexado e ele produz uma skill portável que conhece os idiomas, pegadinhas e padrões da lib. A partir de uma pesquisa, uma skill que codifica o consenso e as divergências entre 30+ fontes. Corpus entra, skill sai, independente de agente.

**Vivendo dentro do loop de desenvolvimento.** Fixe versões de docs no projeto pro agente não desviar. Mostre as seções relevantes enquanto você trabalha. Avise quando a doc upstream mudar de um jeito que afeta código que você já entregou.

A ideia não é "o agente pergunta, o corpus responde". A ideia é que seu agente sempre tem o contexto certo na mão, em silêncio, sem você precisar pedir.

## Roadmap

- Registro comunitário com pacotes versionados de docs e pesquisa
- Distribuição via `pip install king-context`
- Skills geradas por agente a partir de corpus indexado
- Atualização incremental de docs sem rescrape completo
- Suporte a Windows no instalador
- Suíte de benchmark cobrindo docs, ADRs e corpus de pesquisa
- Hooks de workflow que mostram seções relevantes durante o desenvolvimento
- Indexação de conteúdo do usuário (md, txt, pdf, docx, transcrições de vídeo)

Veja as [issues abertas](https://github.com/deandevz/king-context/issues) pro trabalho ativo.

## Interfaces

A CLI é a interface canônica. Qualquer agente que executa comandos shell consegue usar o King Context: hoje isso significa o Claude Code via skills dedicadas, com suporte ao Codex e um formato unificado de skill no roadmap. O servidor MCP continua existindo e roda no mesmo corpus, útil pra agentes que não são de código e integrações de IDE que esperam um endpoint MCP. Mesmo corpus, mesmo formato de retrieval, escolha o que encaixa no seu ambiente.

## Como contribuir

Três áreas onde ajuda move mais o projeto.

- **Pacotes de corpus.** Faça scrape ou pesquisa de algo que você usa muito e abra um PR. A biblioteca da comunidade é a maior alavanca.
- **Confiabilidade do pipeline.** Casos de borda em descoberta de URL, estratégias de chunking, páginas renderizadas em JavaScript, filtragem de fontes.
- **Skills.** Os fluxos de skill ainda estão melhorando. Melhor confiabilidade dos sub-agentes, tratamento de erros, enriquecimento paralelo e um formato unificado que funciona entre plataformas de agente.

Este projeto é open source porque infraestrutura de retrieval pra LLMs deveria ser transparente, dirigida pela comunidade e independente de qualquer fornecedor.

## Licença

MIT. Use, faça fork, melhore.
