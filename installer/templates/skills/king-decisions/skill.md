---
name: king-decisions
description: Retrieve indexed project ADRs and architectural decision history through `.king-context/bin/kctx adr`. Use when the user asks why the project uses something, whether a decision already exists, what the current architecture decision is, what changed historically, or whether a planned code change conflicts with prior decisions.
---

# King Decisions

Retrieve project architectural decisions through `.king-context/bin/kctx adr`.

Use this skill when the user asks about existing decisions, current architecture rationale, decision history, supersession, or conflicts with planned changes.

## Goal

Answer from the minimum relevant decision context.

## Behavior

Be direct and evidence-oriented. Cite ADR IDs. Prefer making a scoped retrieval attempt over asking for clarification when the topic is clear enough.

## Rules

- Prefer active ADRs for current guidance.
- Use timeline when the user asks why something changed or when active results supersede older decisions.
- Use historical ADRs only when they affect the answer.
- If no ADR exists, say that no indexed decision was found. Do not invent one.
- Do not scan or read `.king-context/adr/*.md` directly for retrieval. Use `kctx adr status`, `kctx adr index`, `kctx adr search`, `kctx adr timeline`, and `kctx adr read`.

## Retrieval Budget

- Start with `.king-context/bin/kctx adr status`; if stale, run `.king-context/bin/kctx adr index` before searching.
- First call: `.king-context/bin/kctx adr search "<topic>" --active --top 5`
- If enough: `.king-context/bin/kctx adr read <ADR-ID> --preview` or full read
- If history matters: `.king-context/bin/kctx adr timeline "<topic>"`
- Stop when the current decision and relevant history are clear.

## Output

- State the current decision first.
- Mention superseded decisions only when relevant.
- Cite ADR IDs.
- Keep the answer concise.
