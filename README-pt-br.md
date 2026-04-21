# King Context

Versão em inglês: [README.md](README.md).

> *O que começou como uma solução open-source pro Context7 acaba de iniciar algo bem maior do que a gente imaginava.*

Uma camada de retrieval de conhecimento pra agentes de AI.

Alimenta com qualquer corpus — documentação de vendor, pesquisa da web aberta, notas internas — e ele devolve pro agente exatamente a fatia que ele precisa, no momento em que precisa. Metadados estruturados, progressive disclosure, zero round-trip pra nuvem.

Local first. Eficiente em tokens. Open source.

**Status:** em desenvolvimento ativo. **Licença:** MIT.

---

## Por que isso existe

Agente escreve código melhor, análise melhor, qualquer coisa melhor quando tem o contexto certo. O problema é descobrir o que "certa" significa sem despejar a pia da cozinha inteira no contexto.

Uma única página de API custa 15 mil tokens de markdown cru, e a maior parte é ruído. Ferramentas de retrieval na nuvem tipo Context7 mandam chunks baseados em similaridade semântica — um servidor remoto decide o que seu agente vê, e o agente paga a conta dos tokens independente de ter precisado de tudo aquilo. Você não consegue ver o que tá indexado, não controla a atualização, e não funciona offline.

Forçar um agente a ler dez arquivos `.md` de 400 linhas é o mesmo problema com outra roupagem: a maioria desses tokens nunca importou pro passo atual.

King Context vai por outro caminho. Cada seção de cada página coletada ou fonte pesquisada recebe metadados estruturados (keywords, casos de uso, tags, prioridade). O agente busca nos metadados primeiro, faz preview antes de ler, e só puxa o conteúdo completo quando realmente precisa. O cache de queries aprende os caminhos mais comuns no seu corpus, então lookups repetidos caem pra menos de um milissegundo. Progressive disclosure, não dump.

Na prática: um agente sem conhecimento prévio de uma API consegue ler os docs e produzir código funcional de primeira, geralmente com uns 2.800 tokens no total. Uma varredura `--high` de pesquisa sobre prompt engineering indexou 172 fontes, e o agente ainda conseguiu conversar longamente sobre design em cima desse corpus gastando uns ~4% da janela de contexto. Os mesmos workflows navegando webpages crus custam 15 mil+ tokens por página e ainda obrigam o agente a achar o que importa.

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

Ou pesquisa um tópico da web aberta — mesmo índice, sem precisar de URL inicial:

```bash
.king-context/bin/king-research "prompt engineering techniques" --high --yes
.king-context/bin/king-research "retry backoff" --basic --yes
```

O `king-research` descobre fontes pela web via Exa, faz chunking e enrichment do mesmo jeito que o scraper, e joga o resultado em `.king-context/research/<slug>/`. O tamanho do corpus escala com o esforço: `--basic` tipicamente cobre ~30 fontes em menos de um minuto, `--high` alcança bem mais de 150 em alguns minutos, `--extrahigh` é a varredura estado da arte.

Ou simplesmente pede pro Claude Code em linguagem natural: *"faz scraping da documentação do Stripe"* ou *"pesquisa prompt engineering, detalhado"*. As skills instaladas roteiam pro pipeline certo.

Depois busca, faz preview e lê — mesmos comandos pra docs e pra pesquisa:

```bash
kctx list                                           # docs
kctx list research                                  # corpus de pesquisa
kctx search "authentication" --doc stripe          # busca por metadados
kctx read stripe authentication --preview          # uns 400 tokens
kctx read stripe authentication                    # seção completa
kctx topics prompt-engineering-techniques          # navega a árvore de um research
kctx grep "Bearer" --doc stripe --context 3       # regex como fallback
```

Todo comando aceita `--json` pra saída legível por máquina.

---

## Como funciona

Quatro peças.

**king-scrape** — aponta pra um site de docs. Ele descobre as páginas, baixa, faz chunking do conteúdo e enriquece cada chunk via LLM.

**king-research** — passa um tópico. Ele gera queries de busca, puxa fontes da web aberta via Exa, busca e faz chunking do conteúdo, e entrega os chunks pra mesma etapa de enrichment que o scraper usa. `--basic` até `--extrahigh` controla quantas queries e quantas iterações de aprofundamento rodam.

Os dois produzem o mesmo formato de saída. Cada seção acaba anotada assim:

```json
{
  "keywords": ["api-key", "bearer-token", "authentication"],
  "use_cases": ["Configure API authentication", "Rotate API keys"],
  "tags": ["security", "setup"],
  "priority": 10
}
```

**kctx index** transforma o JSON enriquecido numa estrutura de arquivos plana com índices reversos. Docs vão pra `.king-context/docs/`; pesquisas vão pra `.king-context/research/`. Stores separados, mesma superfície de retrieval.

**kctx** é a interface de busca. Ela pontua as seções comparando os termos da query com os índices de keyword e use case. Sem full text scan, sem similaridade vetorial em uns 90% das lookups. Um cache local de queries colapsa lookups repetidos pra leituras em sub-milissegundo. Em cima disso, o próprio agente pode escrever shortcuts em `.king-context/_learned/<corpus>.md` conforme trabalha — mapeando perguntas comuns pros paths exatos das seções — e a próxima sessão pula a fase de busca inteira. A camada de retrieval fica mais rápida por corpus com o tempo, sem ninguém ter que configurar nada.

A etapa de enrichment é o coração da ideia. Os agentes acham a seção certa via metadados estruturados, em vez de escanear conteúdo cru. É isso que faz o progressive disclosure funcionar sem perder recall — e é o que permite a mesma máquina servir tanto um site de doc de vendor quanto uma varredura de pesquisa cruzando a web.

---

## Benchmarks

Rodamos dois rounds contra o Context7, que é a ferramenta de documentação mais usada pra code agents hoje.

### Round 1: MCP server vs MCP server

Arquitetura original. As duas ferramentas expostas como MCP server, mesmo corpus, mesmo agente.

| Métrica | King Context | Context7 | Melhoria |
|---|---|---|---|
| Tokens médios por query | 968 | 3.125 | 3,2x menos |
| Latência (metadata hit) | 1,15ms | 200 a 500ms | 170x mais rápido |
| Latência (full text search) | 97,83ms | 200 a 500ms | 2 a 5x mais rápido |
| Resultados duplicados | 0 | 11 | zero desperdício |
| Score de relevância | 3,2 / 5 | 2,8 / 5 | +14% |
| Implementabilidade | 4,4 / 5 | 4,0 / 5 | +10% |

Dados completos no [BENCHMARK.md](BENCHMARK.md).

### Round 2: skill vs skill

As duas ferramentas agora rodando como CLI + skill do Claude Code, com o mesmo agente dirigindo. A comparação foi feita sobre a doc da Google Gemini API usando Claude Opus 4.7.

| Métrica | Context7 (skill) | King Context (skill) | Vencedor |
|---|---|---|---|
| Tokens médios por query | ~1.896 | ~1.064 | King Context |
| Tokens medianos por query | 1.750 | 901 | King Context |
| Fatos corretos | 32 / 38 (84%) | 38 / 38 (100%) | King Context |
| Alucinações por query | 0,33 | 0,0 | King Context |
| Qualidade composta (0 a 5) | 3,46 | 4,79 | King Context |
| Código first-shot (Q4) | compila | compila | empate |

### O que o round 2 realmente mostrou

O gap de tokens diminuiu em relação ao round 1, mas a história mudou de quantidade pra qualidade. Com os dois lados agora dirigidos pelo agente, a diferença tá em como cada ferramenta estrutura aquilo que o agente pode pedir.

Três coisas que o King Context fez e o Context7 não:

**Se corrigir sozinho.** A busca inicial da Q1 não pegou a página de spec do modelo. O agente rodou `grep`, achou a linha, leu a seção em modo preview, e parou ali. Custo total ainda menor que a chamada única e inchada do Context7. Progressive disclosure (`search, grep, preview, read`) dá checkpoints pro agente voltar atrás e tentar outro ângulo sem gastar muito.

**Se recusar a alucinar.** A Q5 perguntou sobre headers `Retry-After`. O King Context respondeu explicitamente "não presente nos docs indexados". O Context7 retornou uns 600 tokens de exemplos curl de upload sem relação nenhuma, só porque "rate limit" bateu por proximidade. Quando o retrieval devolve chunks grandes escolhidos por similaridade semântica, falso positivo entra no contexto silenciosamente. Quando o retrieval é em etapas e filtrado por metadados, o agente sabe reconhecer quando tá faltando alguma coisa.

**Lidar com ambiguidade.** A Q3 tocou em `media_resolution`. A Gemini API tem duas gerações desse parâmetro. O King Context retornou as duas. O Context7 retornou só a versão legada, que tá defasada pro Gemini 3. Metadados estruturados (keywords + use cases + tags) pegam as duas gerações; similaridade semântica trava na que tem mais massa no corpus.

A vitória do round 2 não é "o agente dirige o retrieval". Os dois lados dirigem o retrieval agora. A vitória é o formato daquilo que o agente pode alcançar: unidades pequenas, indexadas por metadados, previewáveis, versus chunks maiores rankeados por semântica.

### Limitações que a gente assume

* Só uma run por query no round 2, não duas. Variância desconhecida.
* Contagem de tokens do Context7 é estimativa por caractere, não tiktoken. Margem de erro de uns 20%.

---

## Case studies

Sessões reais, não benchmarks sintéticos. Cada uma registra a sequência de comandos que o agente rodou, o corpus que ele consultou, e o artefato que ele produziu.

- **[MiniMax TTS — first-shot code](validation/minimax-tts-first-shot/)** — Agente lê a API reference de um vendor via `kctx` e escreve código que funciona de primeira. 5 lookups, ~2.800 tokens de doc consumidos, zero ajustes.
- **[Triage-1 — síntese a partir de pesquisa](validation/examples/prompt-engineering-triage1/)** — Agente consulta um corpus de 172 fontes do `king-research --high` sobre prompt engineering e compõe um prompt de suporte nível produção cruzando 5–6 seções indexadas. Conversa de design inteira cabe em ~4% da janela de contexto. Um arquivo `.king-context/_learned/` é escrito pelo próprio agente no meio da sessão — o cache de retrieval se aquecendo como efeito colateral do trabalho.

Mais casos em [`validation/examples/`](validation/examples/). PRs bem-vindos.

---

## Pra onde isso vai

King Context começou como ferramenta de busca contra docs coletados. A direção daqui pra frente é maior: uma camada de retrieval que qualquer agente, em qualquer tópico, pode encostar sem queimar a janela de contexto.

### O problema do `.md`, resolvido de lado

O padrão dominante hoje pra dar conhecimento pra agente é uma pasta de arquivos markdown. Ele desmorona no momento em que a pasta fica séria. Dez docs de 400 linhas é um imposto de cinco dígitos de token em cada turno, e os agentes ainda perdem o parágrafo específico que importava.

King Context substitui esse padrão. O corpus pode ser arbitrariamente grande porque o agente nunca carrega ele inteiro. A busca por metadados filtra pra seção certa, o preview devolve ~400 tokens, o read completo só devolve o resto se precisar. O cache de queries aprende seus caminhos mais comuns. Quanto maior o corpus, mais a disciplina de retrieval compensa.

### Skills e agentes rodando em vários corpus

Uma skill ou sub-agente não devia precisar carregar o material de referência dentro do contexto. Ele devia consultar o corpus do mesmo jeito que um dev faz grep num codebase — com precisão, progressivamente, só quando precisa.

Com o King Context, um único agente pode ter na manga o índice da API do Stripe, a varredura de pesquisa em "webhook security", o runbook interno do time, e um corpus de pesquisa específico de domínio (culinária LATAM, estado da arte em prompt engineering), e alcançar qualquer um deles no meio de uma tarefa. O formato de retrieval é o mesmo em todos. Constrói uma vez, pluga várias bases de conhecimento.

### Registry comunitário de conhecimento

Qualquer pessoa que fizer scraping de uma lib ou pesquisar um tópico pode publicar o corpus enriquecido. Outras pessoas instalam com um comando:

```bash
kctx install stripe@v1
kctx install prompt-engineering-2026
```

Mantido pela comunidade, versionado, sempre atualizado. Pré-enriquecido, então você pula a etapa de scraping ou de pesquisa. Docs de vendor são ponto de partida, não o teto — o registry pode guardar corpus de pesquisa, coleções internas curadas, e alternativas mantidas pela comunidade com exemplos melhores e ciclos de update mais rápidos.

### Agentes que escrevem skills especializadas a partir de um corpus

Um agente que lê seu corpus pode gerar uma skill do Claude Code que conhece as convenções da lib, as pegadinhas, e os padrões idiomáticos. Ou, a partir de um corpus de pesquisa, uma skill que codifica o consenso e as divergências entre 30+ fontes. Corpus entra, skill sai.

É aqui que o King Context deixa de ser só uma ferramenta de retrieval e vira uma fábrica de skills.

### Integração no workflow de dev

Retrieval é a base. A camada seguinte é morar dentro do loop de desenvolvimento: pinar versões de doc pro projeto pra seu agente nunca dar drift, monitorar mudanças upstream nos docs que possam afetar código que você já escreveu, trazer à tona as seções relevantes quando o agente te vê trabalhando em algo.

A ideia não é "agente pergunta, corpus responde". A ideia é que seu agente sempre tenha o contexto certo na mão, silenciosamente, sem você precisar pedir.

---

## CLI e MCP

King Context entrega duas interfaces. Elas servem ambientes diferentes.

A **CLI e a skill do Claude Code** são o foco. É onde code agents trabalham melhor, e é de onde saem os números de qualidade do benchmark. Se você usa King Context dentro do Claude Code, Cursor, ou qualquer workflow de coding agentic, esse é o caminho.

O **MCP server** continua com suporte. Algumas ferramentas e workflows precisam de MCP nativo: agentes não coders, integração com IDE, e qualquer coisa que espera um endpoint MCP. Roda em cima do mesmo corpus e continua recebendo melhorias, só que num ritmo menos agressivo que a CLI.

Escolhe com base no seu ambiente. O corpus é o mesmo dos dois jeitos.

---

## Estrutura do projeto

```
king-context/
├── src/context_cli/        # pacote da CLI (kctx)
│   ├── searcher.py         # busca por metadados
│   ├── reader.py           # leitor de seção com preview
│   ├── indexer.py          # indexador de JSON pra arquivo
│   └── grep.py             # fallback de regex
├── src/king_context/       # MCP server, scraper, researcher
│   ├── server.py           # MCP server
│   ├── db.py               # cascade search em SQLite
│   ├── scraper/            # pipeline do king-scrape (URL → corpus)
│   └── research/           # pipeline do king-research (tópico → corpus)
├── .king-context/          # data store (gerado)
│   ├── docs/               # documentação coletada
│   ├── research/           # tópicos pesquisados
│   └── _learned/           # cache de shortcuts escrito pelo agente (cresce com o uso)
├── validation/
│   ├── minimax-tts-first-shot/   # case doc-driven (código first-shot)
│   └── examples/                 # cases de síntese / multi-fonte
└── .claude/skills/         # skills do Claude Code (king-context, scraper-workflow, king-research)
```

---

## Roadmap

Curto prazo:

* Registry comunitário com pacotes de doc e pesquisa versionados
* Distribuição via `pip install king-context`
* Skills geradas por agente a partir dos docs coletados e dos corpus de pesquisa
* Melhor confiabilidade dos sub-agentes durante o enrichment
* Pipeline de pesquisa mais rico: filtros por domínio, deduplicação de fontes entre tópicos

Mais pra frente:

* Pin de versão por projeto, com notificação quando docs upstream mudam
* Hooks de workflow que trazem seções relevantes durante coding ativo
* Scraping mais esperto: descoberta de URL, limites de chunk, conteúdo renderizado por JavaScript
* Busca cross-corpus (query em vários índices numa chamada só)
* Mais casos de validação cobrindo estilos de API e tasks de agente variadas

---

## Contribuindo

Três áreas em que o projeto mais precisa de ajuda.

**Pacotes de corpus.** Se tem alguma API, framework ou tópico que você usa bastante, faz scraping ou pesquisa e abre um PR. Uma biblioteca comunitária de bases de conhecimento pré-enriquecidas é a maior alavanca desse projeto.

**Confiabilidade dos pipelines.** Casos extremos na descoberta de URL, estratégias de chunking pra formatos de doc incomuns, páginas renderizadas por JavaScript, filtragem melhor de fontes no `king-research`.

**Melhorias nas skills.** Os workflows do Claude Code tão em beta. Deixar os sub-agentes mais confiáveis, lidar com erros direito, rodar as etapas de enrichment em paralelo.

Esse projeto é open source porque infraestrutura de retrieval pra LLM tem que ser transparente, movida pela comunidade, e independente de qualquer provider único.

---

## Licença

MIT. Usa, faz fork, melhora.