# King Context

Versão em inglês: [README.md](README.md).

Infraestrutura de documentação pra agentes de código AI.

Faz scraping de qualquer site de documentação, enriquece cada seção com metadados estruturados, e entrega pro seu agente exatamente os docs que ele precisa pra escrever código correto. Nada além disso.

Local first. Eficiente em tokens. Open source.

**Status:** em desenvolvimento ativo. **Licença:** MIT.

---

## Por que isso existe

LLM escreve código melhor quando tem a documentação certa no contexto. O problema é descobrir o que "certa" significa.

Jogar doc cru no contexto queima 15 mil tokens numa única página de API, e a maior parte é irrelevante. Ferramentas na nuvem tipo Context7 mandam chunks baseados em similaridade semântica, ou seja, um servidor remoto decide o que seu agente vê, e o agente paga a conta dos tokens independente de ter precisado de tudo aquilo. Você não consegue ver o que tá indexado, não controla a atualização, e não funciona offline.

King Context vai por outro caminho. Cada seção de cada doc coletado recebe metadados estruturados (keywords, casos de uso, tags, prioridade). O agente busca nos metadados primeiro, faz preview antes de ler, e só puxa o conteúdo completo quando realmente precisa. Progressive disclosure, não dump.

Na prática, um agente sem conhecimento prévio de uma API consegue usar o King Context pra ler os docs e produzir código funcional de primeira, geralmente com uns 2.800 tokens no total. O mesmo workflow navegando numa webpage custa 15 mil+ tokens e ainda obriga o agente a achar o que importa.

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
# OPENROUTER_API_KEY=...    opcional, pra enrichment automatizado
```

Faz scraping de um site de docs:

```bash
.king-context/bin/king-scrape https://docs.stripe.com --name stripe --yes
.king-context/bin/kctx index .king-context/data/stripe.json
```

Ou simplesmente pede pro Claude Code em linguagem natural: *"faz scraping da documentação do Stripe e indexa."* A skill instalada cuida do pipeline todo.

Depois busca, faz preview e lê:

```bash
kctx list                                        # mostra os docs disponíveis
kctx search "authentication" --doc stripe       # busca por metadados
kctx read stripe authentication --preview       # uns 400 tokens
kctx read stripe authentication                 # seção completa
kctx grep "Bearer" --doc stripe --context 3     # regex como fallback
```

Todo comando aceita `--json` pra saída legível por máquina.

---

## Como funciona

Três peças.

**king-scrape** descobre as páginas num site de docs, baixa elas, faz chunking do conteúdo e enriquece cada chunk via LLM. Cada seção acaba anotada assim:

```json
{
  "keywords": ["api-key", "bearer-token", "authentication"],
  "use_cases": ["Configure API authentication", "Rotate API keys"],
  "tags": ["security", "setup"],
  "priority": 10
}
```

**kctx index** transforma o JSON enriquecido numa estrutura de arquivos plana com índices reversos. Sem banco. Sem embeddings pra maioria das queries.

**kctx** é a interface de busca. Ela pontua as seções comparando os termos da query com os índices de keyword e use case. Sem full text scan, sem similaridade vetorial em uns 90% das lookups.

A etapa de enrichment é o coração da ideia. Os agentes acham a seção certa via metadados estruturados, em vez de escanear conteúdo cru. É isso que faz o progressive disclosure funcionar sem perder recall.

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

## Pra onde isso vai

King Context começou como ferramenta de busca. A direção daqui pra frente é maior.

O objetivo é virar a camada de documentação que code agents usam todo dia. Três peças já estão tomando forma.

### Registry comunitário de documentação

Qualquer pessoa que fizer scraping dos docs de uma lib pode publicar o corpus enriquecido. Outras pessoas instalam com um comando:

```bash
kctx install stripe@v1
kctx install fastapi@latest
```

Mantido pela comunidade, versionado, sempre atualizado. Pré-enriquecido, então você pula a etapa de scraping. Os docs oficiais dos vendors são ponto de partida, não o teto. Comunidades em torno de libs específicas podem publicar versões melhores, com mais exemplos, casos de uso mais profundos, e ciclos de update mais rápidos que as páginas oficiais.

### Agentes que escrevem skills especializadas a partir de docs

Os docs em si já contêm tudo que é preciso pra ensinar um agente a usar bem uma lib. Um agente que lê seu corpus pode gerar uma skill do Claude Code que conhece as convenções da lib, as pegadinhas, e os padrões idiomáticos. Docs entram, skills saem.

É aqui que o King Context deixa de ser só uma ferramenta de retrieval e vira uma fábrica de skills. Todo pacote de docs público vira candidato a agente especializado gerado automaticamente.

### Integração no workflow de dev

Retrieval é a base. A camada seguinte é fazer o King Context morar dentro do loop de desenvolvimento: pinar versões de doc pro projeto pra seu agente nunca dar drift, monitorar mudanças upstream nos docs que possam afetar código que você já escreveu, trazer à tona as seções relevantes quando o agente te vê trabalhando em algo.

A ideia não é "agente pergunta, doc responde". A ideia é que seu agente sempre tenha o contexto certo de documentação, silenciosamente, sem você precisar pedir.

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
├── src/king_context/       # MCP server e scraper
│   ├── server.py           # MCP server
│   ├── db.py               # cascade search em SQLite
│   └── scraper/            # pipeline do king-scrape
├── .king-context/          # data store (gerado)
├── validation/             # casos de teste do mundo real
└── .claude/skills/         # skills do Claude Code
```

---

## Roadmap

Curto prazo:

* Registry comunitário com pacotes de doc versionados
* Distribuição via `pip install king-context`
* Skills geradas por agente a partir dos docs coletados
* Melhor confiabilidade dos sub-agentes durante o enrichment

Mais pra frente:

* Pin de versão por projeto, com notificação quando docs upstream mudam
* Hooks de workflow que trazem docs relevantes durante coding ativo
* Scraping mais esperto: descoberta de URL, limites de chunk, conteúdo renderizado por JavaScript
* Mais casos de validação cobrindo estilos de API e tasks de agente variadas

---

## Contribuindo

Três áreas em que o projeto mais precisa de ajuda.

**Pacotes de documentação.** Se tem alguma API ou framework que você usa bastante, faz scraping e abre um PR. Uma biblioteca comunitária de docs pré-enriquecidos é a maior alavanca desse projeto.

**Confiabilidade do scraper.** Casos extremos na descoberta de URL, estratégias de chunking pra formatos de doc incomuns, tratamento melhor de páginas renderizadas por JavaScript.

**Melhorias nas skills.** Os workflows do Claude Code tão em beta. Deixar os sub-agentes mais confiáveis, lidar com erros direito, rodar as etapas de enrichment em paralelo.

Esse projeto é open source porque infraestrutura de documentação pra LLM tem que ser transparente, movida pela comunidade, e independente de qualquer provider único.

---

## Licença

MIT. Usa, faz fork, melhora.