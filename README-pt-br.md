# King Context

Versão em inglês: [README.md](README.md).

> *O que começou como uma solução open-source pro Context7 acaba de iniciar algo bem maior do que a gente imaginava.*

Uma camada de retrieval de conhecimento pra agentes de AI.

Alimenta com qualquer corpus — documentação de vendor, pesquisa da web aberta, notas internas — e ele devolve pro agente exatamente a fatia que ele precisa, no momento em que precisa. Metadados estruturados, progressive disclosure, zero round-trip pra nuvem.

Local first. Eficiente em tokens. Open source.

**Status:** em desenvolvimento ativo. **Licença:** MIT.

---

## Por que isso existe

Agente escreve código melhor, análise melhor, qualquer coisa melhor quando tem o contexto certo. O problema é descobrir o que "certo" significa sem despejar a pia da cozinha inteira no contexto.

Uma única página de API custa 15 mil tokens de markdown cru, e a maior parte é ruído. Ferramentas de retrieval na nuvem tipo Context7 mandam chunks baseados em similaridade semântica — um servidor remoto decide o que seu agente vê, e o agente paga a conta dos tokens independente de ter precisado de tudo aquilo. Você não consegue ver o que tá indexado, não controla a atualização, e não funciona offline.

King Context vai por outro caminho. Cada seção de cada página coletada ou fonte pesquisada recebe metadados estruturados (keywords, casos de uso, tags, prioridade). O agente busca nos metadados primeiro, faz preview antes de ler, e só puxa o conteúdo completo quando realmente precisa. O cache de queries aprende os caminhos mais comuns no seu corpus, então lookups repetidos caem pra menos de um milissegundo. Progressive disclosure, não dump.

Na prática: um agente sem conhecimento prévio de uma API consegue ler os docs e produzir código funcional de primeira, geralmente com uns 2.800 tokens no total. Uma varredura `--high` de pesquisa sobre prompt engineering indexou 172 fontes, e o agente ainda conseguiu conversar longamente sobre design em cima desse corpus gastando uns ~4% da janela de contexto.

---

## Quick start

Um comando pra instalar em qualquer projeto:

```bash
npx @king-context/cli init
```

Isso cria `.king-context/` com um virtual env Python, as ferramentas de CLI, skills do Claude Code, e templates de config. Zero setup manual.

Adiciona suas chaves:

```bash
cp .king-context/.env.example .env
# FIRECRAWL_API_KEY=...     obrigatória pra scraping
# EXA_API_KEY=...           obrigatória pro king-research
# OPENROUTER_API_KEY=...    opcional, pra enrichment automatizado
```

Faz scraping de um site de docs:

```bash
.king-context/bin/king-scrape https://docs.stripe.com --name stripe --yes
.king-context/bin/kctx index .king-context/data/stripe.json
```

Ou pesquisa um tópico na web aberta — mesmo índice, sem precisar de URL inicial:

```bash
.king-context/bin/king-research "prompt engineering techniques" --high --yes
.king-context/bin/king-research "retry backoff" --basic --yes
```

`king-research` descobre fontes pela web, faz chunk e enrichment do mesmo jeito que o `king-scrape`, e despeja o resultado em `.king-context/research/<slug>/`. Tamanho do corpus escala com o esforço: `--basic` geralmente indexa ~30 fontes em menos de um minuto, `--high` chega a mais de 150 em alguns minutos, `--extrahigh` é a varredura state-of-the-art.

Ou simplesmente pede pro Claude Code em português: *"faz scraping dos docs do Stripe"* ou *"pesquisa prompt engineering, detalhado"*. As skills instaladas roteiam pra pipeline certa.

Aí busca, faz preview e lê — mesmos comandos pra docs e research:

```bash
kctx list                                           # docs
kctx list research                                  # corpora de research
kctx search "authentication" --doc stripe          # busca por metadados
kctx read stripe authentication --preview          # ~400 tokens
kctx read stripe authentication                    # seção completa
kctx topics prompt-engineering-techniques          # navega na árvore de research
kctx grep "Bearer" --doc stripe --context 3       # fallback regex
```

Todo comando aceita `--json` pra output legível por máquina. Referência completa: [`docs/CLI_GUIDE.md`](docs/CLI_GUIDE.md).

---

## Documentação

Wiki dentro do repo em [`docs/`](docs/index.md):

- [Architecture](docs/architecture.md) — como o cascade search, o scraper e o researcher se conectam
- [Vision](docs/vision.md) — pra onde o projeto tá indo, e as ideias de design por trás
- [Benchmarks](docs/benchmarks.md) — números de performance contra Context7
- [Case studies](docs/case-studies.md) — sessões reais de agente, com trace completo
- [Roadmap](docs/roadmap.md) — planos de curto e longo prazo
- [CLI guide](docs/CLI_GUIDE.md) — comandos e flags do `kctx`

> Os documentos da wiki estão em inglês pra alinhar com as regras do projeto. Este README PT-BR é o ponto de entrada localizado.

---

## Em resumo

- **Eficiente em tokens.** ~1.000 tokens por query versus ~3.000 do Context7 no benchmark original, e 100% de precisão factual versus 84% no round skill-vs-skill. Números e metodologia em [Benchmarks](docs/benchmarks.md).
- **Local first.** Seu corpus, sua máquina. Zero round-trip pra nuvem na hora de buscar. Funciona offline.
- **Dois caminhos de entrada, uma superfície de retrieval.** `king-scrape` pra docs de vendor, `king-research` pra tópicos da web aberta. Mesmo JSON enriquecido, mesma interface `kctx`.
- **Progressive disclosure.** Busca por metadados → preview → leitura completa. Agente só puxa o que precisa.
- **Cache que se aquece sozinho.** Agentes escrevem shortcuts em `.king-context/_learned/<corpus>.md` enquanto trabalham. Retrieval fica mais rápido por corpus ao longo do tempo, sem ninguém configurar nada.

---

## Contribuindo

O projeto é open source porque infraestrutura de retrieval pra LLMs deveria ser transparente, dirigida pela comunidade, e independente de qualquer provedor.

Três áreas onde o projeto mais precisa de ajuda externa:

- **Pacotes de corpus.** Faz scraping de uma API ou pesquisa um tópico que você usa muito, e abre um PR. Uma biblioteca comunitária de corpora pré-enriquecidos é a maior alavanca do projeto.
- **Confiabilidade da pipeline.** Edge cases em URL discovery, chunking, páginas com JavaScript, filtragem de fontes.
- **Melhorias de skill.** Confiabilidade de sub-agente, tratamento de erro, enrichment paralelo.

Lê o [contributing guide](CONTRIBUTING.md) pra setup, branches, estilo de commit e workflow de PR. Participando, você concorda com o [Code of Conduct](CODE_OF_CONDUCT.md).

---

## Licença

MIT. Usa, dá fork, melhora.
