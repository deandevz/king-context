# Triage-1 — Research-to-Synthesis Case Study

> A production-grade customer support triage prompt, synthesized by Claude (Opus 4.7) using **only** a `king-research --high` corpus on "prompt and context engineering for agents" (172 sources). No prior knowledge, no web access, no other tools.

## What is this

A second validation case, qualitatively different from [`minimax-tts-first-shot`](../../minimax-tts-first-shot/).

- **MiniMax case** — doc-driven first-shot code. Agent reads a vendor's API reference via king-context and writes working code with zero adjustments.
- **This case** — research-driven synthesis. Agent queries a cross-source research corpus and *composes* an expert-level artifact (a prompt) that draws on 5–6 different sources at once.

**Result:** a Triage-1 support prompt with anti-example, XML-delimited sections, schema-enforced chain-of-thought, prompt-injection classified as a first-class category, adversarial few-shot example, and a technique-to-source mapping table. See [`triage1_prompt.md`](./triage1_prompt.md) for the full artifact.

---

## The corpus

Prepared ahead of time in another project:

```bash
king-research "prompt and context engineering for agents" --high --yes
```

- **Effort:** `--high` (8 initial queries, 2 deepening iterations)
- **Sources indexed:** 172
- **Slug:** `prompt-and-context-engineering-for-agent`
- **Store:** `.king-context/research/`

The corpus was never loaded into conversation — the agent reached into it incrementally.

---

## LLM workflow

### Turn 1 — "What are the common requirements of a good prompt?"

The agent ran progressive searches against the research store, each pulling only metadata-level hits until it had enough signal to call `kctx read` on the right sections:

```
1. kctx search "good prompt requirements common elements" --source research
2. kctx search "prompt structure components elements best practices" --source research
3. kctx read  prompt-and-context-engineering-for-agent / ...-tl-dr
4. kctx search "anatomy prompt components identity role" --source research
5. kctx topics prompt-and-context-engineering-for-agent --tag anatomy
6. kctx search "identity tool definitions constraints output format examples" --source research
7. kctx read  .../3-1-what-are-the-five-components-of-a-system-prompt
8. kctx read  .../best-practices-for-clear-instructions
```

Output: a two-part synthesis — the 5 structural components (identity / tools / constraints / output format / examples) from one source, plus a 4-item clarity checklist (goal / audience / format / example) from another, reconciled in a single "common denominator" table.

### Turn 2 — "Give me a production-grade example using these techniques"

Deeper dive. ~9 more searches covering techniques not yet retrieved in turn 1:

```
kctx search "prompt example template system"
kctx search "delimiters XML tags structure prompt"
kctx search "chain of thought reasoning step by step"
kctx search "ReAct pattern thought action observation"
kctx search "prompt injection defense delimiting sandwich"
kctx search "customer service agent example persona"
kctx search "how to structure system prompt anatomy sections"
kctx grep   "You are"
kctx grep   "customer service agent for TechCorp"
kctx read   .../structure-controls-behavior-f013a825
kctx read   .../site-blog-prompt-engineering-the-anatomy-of-a-prompt
```

Output: the full Triage-1 prompt with every technique traced back to a specific indexed section. See [`triage1_prompt.md`](./triage1_prompt.md).

### Side effect — `_learned/` shortcut cache

Mid-session the agent wrote `.king-context/_learned/prompt-and-context-engineering-for-agent.md`, mapping "common requirements of a good prompt" to the exact section paths it used. Next time another agent in that project asks a similar question, the search phase collapses to a direct `kctx read`.

This is the query cache claim realized in the wild — the retrieval layer gets faster per corpus over time, without anyone wiring it up.

---

## Cost observations

This case wasn't token-logged stage-by-stage like the MiniMax one, but the user reported the numbers live:

- **Context used to hold both turns (retrieval + synthesis + conversation):** ~4% of the model's window.
- **Total searches across both turns:** ~17 calls, each returning short metadata hits, not full sections.
- **Full section reads:** 5–6. Most calls stopped at metadata / preview.

For reference: dumping the raw scrape of 172 source pages into context would be far beyond any context window. The agent never had to.

---

## Why this matters

The MiniMax case proved King Context could replace a vendor's API reference page for code-writing. This case proves something different:

- **A research corpus behaves like a single document for the agent**, even at 172 sources, as long as the retrieval surface is metadata-first.
- **Progressive disclosure handles cross-source synthesis** — the agent doesn't need all the material in-context to reconcile multiple frameworks. It can pick up pieces one search at a time.
- **`_learned/` turns repeat queries into a warm cache** automatically, and the cache is authored by the agent itself as a side effect of working.

Together these close the gap between "retrieval tool" and "the way an agent carries knowledge across sessions".

---

*Case study captured on 2026-04-21 from a live Claude Code session using the `/king-context` skill.*
