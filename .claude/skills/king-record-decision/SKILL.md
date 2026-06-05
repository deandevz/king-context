---
name: king-record-decision
description: Create and maintain project ADRs through `.king-context/bin/kctx adr`. Use when the user asks to create an ADR, register a decision, document an architecture choice, supersede an old decision, or record why the project changed direction.
---

# King Record Decision

Create and maintain project ADRs through `.king-context/bin/kctx adr`.

## Goal

Create a valid ADR, link related or superseded decisions, rebuild the decision index, and validate the result.

## Behavior

Be careful and decisive. The CLI provides structure; you provide judgment about relationships between decisions. Ask the user only when a new decision would conflict with an active ADR and the replacement is not explicit.

## Before Creating

- Start with `.king-context/bin/kctx adr status`; if stale, run `.king-context/bin/kctx adr index`.
- Search active decisions for the topic.
- Search active decisions for key technologies or architecture areas.
- Read previews for likely matches.
- Use timeline if a previous decision may be superseded.
- Do not scan `.king-context/adr/*.md` to discover related decisions. Discovery must happen through `kctx adr` retrieval commands.

## Classify Existing ADRs

- `superseded-by-new`: the new decision replaces this ADR.
- `related`: the ADR is relevant but still valid.
- `conflict`: the new decision appears to contradict an active ADR and needs user confirmation.
- `irrelevant`: do not link.

## Creation Rules

- If the new decision replaces an old one, use `--supersedes` and include a concrete supersession reason.
- If the new decision only touches nearby architecture, use `--related`.
- If there is an unresolved conflict with an active ADR, ask the user before writing.
- If no related ADR exists, create an independent ADR.
- Read or edit ADR markdown only when creating a new ADR or updating a specific ADR selected by the workflow.

## Validation

- After writing markdown, run `.king-context/bin/kctx adr index`.
- Run `.king-context/bin/kctx adr validate`.
- Run `.king-context/bin/kctx adr timeline "<topic>"` and summarize the resulting state.

## Output

- Name the ADR created.
- List superseded and related ADRs.
- State whether validation passed.
- Include any remaining conflict or ambiguity.
