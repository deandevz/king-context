# Case studies

Real agent sessions, not synthetic benchmarks. Each one captures the command sequence the agent ran, the corpus it worked against, and the artifact it produced.

## Available cases

- **[MiniMax TTS — first-shot code](../validation/minimax-tts-first-shot/)**
  Agent reads a vendor API reference through `kctx` and writes working code on the first run. 5 lookups, ~2,800 tokens of docs consumed, zero adjustments.

- **[Triage-1 — research-driven synthesis](../validation/examples/prompt-engineering-triage1/)**
  Agent queries a 172-source `king-research --high` corpus on prompt engineering and composes a production-grade customer-support prompt, cross-referencing 5–6 indexed sources. Full design conversation fits in ~4% of the context window. A `.king-context/_learned/` shortcut file is written mid-session — the retrieval cache warming itself as a side effect of the work.

More cases under [`validation/examples/`](../validation/examples/).

## Contributing a case study

Run a real session against your own corpus and document it. A useful case study includes:

- The corpus the agent worked against (scrape command or research command).
- The full sequence of `kctx` calls the agent made, with token counts.
- The artifact produced (working code, design doc, analysis).
- Any `.king-context/_learned/` shortcuts that emerged.

Open a PR adding the session under `validation/examples/<slug>/`. See [CONTRIBUTING.md](../CONTRIBUTING.md) for the workflow.
