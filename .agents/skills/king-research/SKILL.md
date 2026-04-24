---
name: king-research
description: Build an open-web research corpus on a topic using the king-research pipeline (generate → search → chunk → enrich → export) and auto-index it for later search. Trigger when the user asks to research / pesquisar / build a corpus / find sources / survey state-of-the-art on a general topic (papers, blog posts, discussions, comparisons). Do NOT trigger when the user points to a specific product documentation site — use the scraper-workflow skill for that. Do NOT trigger when the user wants to query already-indexed content — use the king-context skill (`kctx search`) for that.
---

# King Research — Topic Research Skill

Invoke `king-research` to build a research corpus on any topic. The user describes what they want; you extract the topic, pick the effort mode, and run the pipeline.

---

## When to use this skill

| User wants... | Use |
|---|---|
| Sources on an open-web topic (papers, blog posts, discussions) | **king-research** (this skill) |
| A specific product/API doc site scraped | **scraper-workflow** (`king-scrape`) |
| To query already-indexed content | **king-context** (`kctx search`) |

If the user already mentions a URL or a specific product's docs, hand off to `scraper-workflow`.

---

## Step 1: Extract the topic

Pull the topic from the user's message as a concise phrase (2–6 words).

**Rules**:
- Strip filler: "please", "por favor", "pode fazer", "quero que", "me faça".
- Keep semantic qualifiers: "for RAG pipelines", "in production", "2025".
- Prefer the user's wording over paraphrase.
- Quote multi-word topics when passing to the CLI.

If the topic is vague (e.g. "faz um research aí", "pesquise algo"), ask ONE clarifying question before running: **"What topic?"**

---

## Step 2: Pick the effort mode

### Explicit signals (override inference)

| Signal in the user's message | Mode |
|---|---|
| "rápido", "quick", "basic", "só uma ideia", "overview", "simples" | `--basic` |
| (no qualifier) | `--medium` (default) |
| "detalhado", "aprofundado", "profundo", "detailed", "in-depth", "completo" | `--high` |
| "exaustivo", "estado da arte", "thorough", "comprehensive", "state of the art", "máximo", "tudo que tiver" | `--extrahigh` |

### Inferred from complexity (when no explicit signal)

| Topic shape | Mode |
|---|---|
| Narrow, well-known (e.g. "httpx timeouts") | `--basic` |
| Standard technical topic (e.g. "prompt caching strategies") | `--medium` (default) |
| Broad or comparative (e.g. "RAG vs fine-tuning") | `--high` |
| Bleeding-edge / multi-domain survey (e.g. "mixture of experts state of the art 2025") | `--extrahigh` |

### Cost & time budget

| Mode | Initial queries | Deepening iterations | ~Time | API cost |
|---|---|---|---|---|
| `--basic` | 3 | 0 | ~30s | minimal |
| `--medium` | 5 | 1 | ~2 min | low |
| `--high` | 8 | 2 | ~5 min | medium |
| `--extrahigh` | 12 | 3 | ~10 min | high |

For `--high` or `--extrahigh`, state the expected time before running so the user isn't surprised. No need to ask permission — just warn.

---

## Step 3: Run the pipeline

```bash
.king-context/bin/king-research "<topic>" --<mode> --yes
```

**Flags to remember**:
- `--yes` / `-y` — skip the enrichment cost prompt (default ON from this skill; the user invoked us to do the work, not to be interrupted).
- `--name <slug>` — override the auto-generated slug (rarely needed; only if the user explicitly names it).
- `--no-auto-index` — don't auto-index into `.king-context/research/` (rarely; only if the user explicitly asks for JSON-only output).
- `--step <stage>` / `--stop-after <stage>` — resume or partial-run (only for debugging; don't use proactively).

**Pipeline stages** (for reference when resuming): `generate → search → chunk → enrich → export`.

---

## Step 4: Report + hand off to search

After the pipeline finishes, report concisely:

1. The slug it was saved under (auto-indexed in `.king-context/research/<slug>/`).
2. Section count.
3. Example commands to search it.

Template:
```
Indexed "<slug>" — N sections. Try:
  kctx search "<keyword>" --doc <slug>
  kctx topics <slug>
  kctx list research
```

Don't dump the full topic tree or section titles — let the user drive the search.

---

## Error handling

| Error | Action |
|---|---|
| `EXA_API_KEY is not set` | "Set `EXA_API_KEY` in `.king-context/.env` or `./.env`, then retry." |
| `OPENROUTER_API_KEY` missing | Same — both are required (query generation + enrichment). |
| Zero results from Exa | Topic may be too niche or mis-spelled. Suggest rephrasing or adding context. |
| Pipeline fails with "no chunks" or "no enriched sections" | Report which stage; usually means the topic returned no fetchable pages. Try broadening the topic. |
| User hit a high/extrahigh run by mistake | Remind them `Ctrl+C` cancels; partial progress in `.king-context/_temp/research/<slug>/` is kept for resume via `--step`. |

---

## Examples

### Implicit mode (inferred from complexity)
```
User: "pesquise sobre chain of thought prompting"
→ Topic: "chain of thought prompting"
→ Standard technical topic → --medium
→ .king-context/bin/king-research "chain of thought prompting" --medium --yes
→ "Indexed chain-of-thought-prompting — 14 sections."
```

### Explicit mode — quick
```
User: "faz um research rápido sobre retry backoff"
→ Topic: "retry backoff"
→ Signal "rápido" → --basic
→ .king-context/bin/king-research "retry backoff" --basic --yes
```

### Explicit mode — exhaustive
```
User: "quero tudo sobre mixture of experts, estado da arte"
→ Topic: "mixture of experts"
→ Signal "estado da arte" → --extrahigh
→ Warn: "~10 minutes and higher API cost — proceeding"
→ .king-context/bin/king-research "mixture of experts" --extrahigh --yes
```

### Comparative (inferred high)
```
User: "compare RAG vs fine-tuning for code assistants"
→ Topic: "RAG vs fine-tuning code assistants"
→ Comparative, broad → --high
→ .king-context/bin/king-research "RAG vs fine-tuning code assistants" --high --yes
```

### Vague topic (ask first)
```
User: "faz um research aí"
→ Ask: "What topic?"
→ (wait for reply, then resume from Step 1)
```

### User provides a URL — hand off
```
User: "research stripe docs"
→ This is a doc site, not an open-web topic.
→ Hand off to scraper-workflow: king-scrape https://docs.stripe.com
```
