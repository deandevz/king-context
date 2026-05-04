# Benchmarks

We ran two rounds against Context7, the most widely used documentation tool for code agents today.

For methodology, rubrics, and reproducibility instructions, see [`BENCHMARK.md`](../BENCHMARK.md).

---

## Round 1: MCP server vs MCP server

Original architecture. Both tools exposed as MCP servers, same corpus, same agent.

| Metric | King Context | Context7 | Improvement |
|---|---|---|---|
| Average tokens per query | 968 | 3,125 | 3.2x less |
| Latency (metadata hit) | 1.15ms | 200 to 500ms | 170x faster |
| Latency (full text search) | 97.83ms | 200 to 500ms | 2 to 5x faster |
| Duplicate results | 0 | 11 | zero waste |
| Relevance score | 3.2 / 5 | 2.8 / 5 | +14% |
| Implementability | 4.4 / 5 | 4.0 / 5 | +10% |

---

## Round 2: skill vs skill

Both tools running as CLI + Claude Code skill, driven by the same agent. Comparison ran on the Google Gemini API docs using Claude Opus 4.7.

| Metric | Context7 (skill) | King Context (skill) | Winner |
|---|---|---|---|
| Average tokens per query | ~1,896 | ~1,064 | King Context |
| Median tokens per query | 1,750 | 901 | King Context |
| Correct facts | 32 / 38 (84%) | 38 / 38 (100%) | King Context |
| Hallucinations per query | 0.33 | 0.0 | King Context |
| Composite quality (0 to 5) | 3.46 | 4.79 | King Context |
| First-shot code (Q4) | compiles | compiles | tie |

### What round 2 actually showed

The token gap shrank compared to round 1, but the story shifted from quantity to quality. With both sides now agent-driven, the difference is in how each tool shapes what the agent can ask for.

Three things King Context did that Context7 didn't:

**Self-correct.** The initial Q1 search missed the model spec page. The agent ran `grep`, found the line, read the section in preview mode, and stopped there. Total cost still lower than Context7's single bloated call. Progressive disclosure (`search, grep, preview, read`) gives the agent checkpoints to backtrack and try another angle without burning budget.

**Refuse to hallucinate.** Q5 asked about `Retry-After` headers. King Context explicitly answered "not present in the indexed docs". Context7 returned about 600 tokens of unrelated curl upload examples, purely because "rate limit" matched by proximity. When retrieval hands back large chunks picked by semantic similarity, false positives slip into context quietly. When retrieval is staged and filtered by metadata, the agent can tell when something is missing.

**Handle ambiguity.** Q3 touched `media_resolution`. The Gemini API has two generations of that parameter. King Context returned both. Context7 returned only the legacy version, which is outdated for Gemini 3. Structured metadata (keywords + use cases + tags) catches both generations; semantic similarity locks onto whichever has more mass in the corpus.

The round 2 win isn't "the agent drives retrieval". Both sides drive retrieval now. The win is the shape of what the agent can reach: small units indexed by metadata, previewable, versus bigger chunks ranked by semantics.

---

## Limitations we own

- One run per query in round 2, not two. Variance unknown.
- Context7 token counts are per-character estimates, not tiktoken. About 20% margin of error.

---

## Reproducing the results

See [`BENCHMARK.md`](../BENCHMARK.md) for the full methodology — developer profiles, question categories, evaluation rubrics, and the procedure to re-run the comparison on a different corpus.
