# Examples

Case studies that show King Context used in real sessions, not just benchmarks.

Each subdirectory captures:
- the corpus the agent was working against,
- the actual command sequence the agent ran,
- the artifact it produced,
- the token/context cost observed.

## Available case studies

| Case | Corpus | What it shows |
|---|---|---|
| [prompt-engineering-triage1](./prompt-engineering-triage1/) | `king-research --high` on prompt & context engineering for agents (172 sources) | Research-driven synthesis — agent composes a production-grade customer-support prompt by cross-referencing 5–6 indexed sources, without loading the corpus whole. Context footprint ~4%. |

See also [`validation/minimax-tts-first-shot/`](../minimax-tts-first-shot/) — a doc-driven first-shot code case (not a synthesis case, so it lives one level up).

## How new examples are added

A new case belongs here when it demonstrates *a retrieval pattern or synthesis behavior that isn't already covered*. Don't add a case that only varies the corpus — add one that shows something new about how the agent uses the retrieval surface.

Each case directory should contain at minimum:
- `README.md` — scenario, corpus, command sequence, observations, cost
- the artifact the agent produced (code, prompt, analysis, etc.)
