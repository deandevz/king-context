# Benchmark Methodology

## Objective

Compare **King Context** vs **Context7** in real-world AI coding scenarios, measuring:

- Token efficiency (less context pollution = fewer hallucinations)
- Documentation quality (can you actually implement from it?)
- Noise and duplication

---

## Test Configuration

| System | Type | Description |
|--------|------|-------------|
| **King Context** | Local | Custom MCP with cascade search (Cache → Metadata → FTS5 → Hybrid Rerank) |
| **Context7** | Cloud | External documentation service with remote API |

---

## Metrics

| Metric | Description | Range |
|--------|-------------|-------|
| **Relevance** | Does the doc answer the question? | 1-5 |
| **Implementability** | Can you implement with this? | 1-5 |
| **Noise** | Repeated/irrelevant info | 1-5 (1=clean) |
| **Completeness** | Is anything critical missing? | 1-5 |
| **Tokens** | char_count / 4 | int |

### Implementability Rubric

| Score | Criteria |
|-------|----------|
| 5 | Code example + parameters + edge cases |
| 4 | Code example + main parameters |
| 3 | Conceptual information, no code |
| 2 | Missing critical information |
| 1 | Cannot implement |

### Relevance Rubric

| Score | Criteria |
|-------|----------|
| 5 | Answers exactly the query, no noise |
| 4 | Answers the query with useful extra context |
| 3 | Partially answers, includes unrequested info |
| 2 | Tangentially related, too much noise |
| 1 | Irrelevant or mostly duplicated |

---

## Developer Profiles

Tests simulate real queries from two developer profiles:

### Junior Developer
- Basic, direct questions
- Focus on "how to start", "simple example"

### Senior Developer
- Specific, advanced questions
- Focus on edge cases, performance, integration

---

## Question Categories

| Category | Junior Query | Senior Query |
|----------|--------------|--------------|
| **Auth** | How to authenticate | Token refresh, security |
| **Core Feature** | Basic usage | Streaming with timestamps |
| **Error Handling** | What errors exist | Retry strategy, rate limits |
| **Integration** | How to use with Python | WebSocket, multiplexing |
| **Edge Cases** | Supported formats | Timeout handling, partial responses |

Total: 5 categories x 2 profiles = 10 queries per benchmark

---

## Execution Procedure

### Phase 1: Question Generation

For each combination (5 categories x 2 profiles):

```
You are a {PROFILE} developer wanting to use the API.
Generate 1 realistic question about {CATEGORY}.
```

### Phase 2: Query Execution

Run queries in parallel against both systems:

```bash
# King Context
search_docs(query="{question}", doc_name="api-name", max_results=5)

# Context7
query-docs(libraryId="/library/path", query="{question}")
```

### Phase 3: Evaluation (LLM Judge)

For each result pair, evaluate:

- Relevance (1-5)
- Implementability (1-5)
- Noise (1-5, 1=clean)
- Completeness (1-5)
- Token count

Determine winner with reasoning.

### Phase 4: Consolidation

Aggregate into:
- Executive summary with averages
- Breakdown by developer profile
- Breakdown by question category

---

## Latency Reference

### King Context - Cascade Search

```
1. Cache hit     → <1ms   (exact query previously executed)
2. Metadata hit  → <5ms   (match on keywords/use_cases/tags)
3. FTS5 hit      → <10ms  (full-text search with BM25)
4. Hybrid rerank → <15ms  (semantic similarity reordering)
```

### Context7

```
Cloud round-trip → 200-500ms typical
```

---

## Token Efficiency Formula

```
efficiency_ratio = context7_tokens / king_context_tokens
```

- `ratio > 1.5`: King Context significantly more efficient
- `ratio 1.0-1.5`: King Context slightly more efficient
- `ratio < 1.0`: Context7 more efficient

---

## Reproducibility

All benchmarks can be reproduced by:

1. Indexing the same documentation in King Context
2. Using the same library IDs in Context7
3. Running identical queries against both systems
4. Applying the same evaluation rubric

Raw results stored in `BENCHMARK_RESULTS_*.md` files for transparency
