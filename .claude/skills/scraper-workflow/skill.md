# Scraper Workflow — Documentation Scraping Skill

Orchestrate the full documentation scraping pipeline: discover, filter, fetch, chunk, enrich, export, and index.

**Triggers**: "scrape", "scrape docs", "scrape documentation", "index docs from", "crawl docs", "get documentation for", "I want the docs for X", "add docs for X"

---

## Overview

This skill teaches you to run the `king-scrape` pipeline end-to-end, with two workflows:

- **Workflow A (OpenRouter)** — fully automated, uses OpenRouter API for LLM filter + enrichment
- **Workflow B (Claude Code sub-agents)** — uses your own sub-agents (Sonnet for filtering, Haiku for enrichment)

The user chooses the workflow. If they don't specify, check for `OPENROUTER_API_KEY` in the environment — if present, default to Workflow A; otherwise suggest Workflow B.

---

## Step 1: Resolve URL

If the user provides a URL, use it directly. If they provide only a name:

1. Search the web: `"<name> official documentation site"`
2. If found (e.g., `docs.stripe.com`, `reactjs.org/docs`):
   - Confirm: "I found https://docs.stripe.com — should I scrape this?"
3. If not found:
   - Ask: "I couldn't find the docs URL. What's the documentation URL?"

---

## Step 2: Detect Resume

Before starting any pipeline, check for existing progress:

1. Derive work dir: `.temp-docs/<domain-slug>/`
2. If it exists, read `manifest.json`
3. Report progress to the user:
   ```
   Found previous scraping for <name>:
   - discover: done (683 URLs)
   - filter: done (606 accepted)
   - fetch: in_progress (42/606 pages)
   Continue from where it left off?
   ```
4. If user confirms → continue (the pipeline auto-resumes)
5. If user wants fresh start → delete the work dir first: `rm -rf .temp-docs/<domain-slug>/`

---

## Step 3: Run the Pipeline

### Workflow A: OpenRouter (automated)

One command does everything:

```bash
king-scrape <url> --yes
```

This runs: discover → filter (with LLM) → fetch → chunk → enrich → export.

The `--yes` flag skips the enrichment cost confirmation prompt.

After it completes:

```bash
kctx index data/<name>.json
```

Done. Report: "Indexed `<name>` — N sections."

### Workflow B: Claude Code Sub-Agents

This workflow gives you control over filtering and enrichment using sub-agents.

#### Step 3a: Scrape up to fetch

```bash
king-scrape <url> --no-llm-filter --stop-after fetch
```

This runs: discover → filter (heuristic only) → fetch. It stops after fetching all pages.

Fetch has **resume support** — if interrupted, re-running the same command skips already-downloaded pages.

#### Step 3b: Smart filter (optional, sub-agent Sonnet)

Read the filtered URLs:

```bash
cat .temp-docs/<domain>/filtered_urls.json | python -c "import json,sys; d=json.load(sys.stdin); print(f'accepted: {len(d[\"accepted\"])}, maybe: {len(d[\"maybe\"])}, rejected: {len(d[\"rejected\"])}')"
```

If there are more than 10 "maybe" URLs, use a Sonnet sub-agent to reclassify them:

**For each batch of up to 50 URLs**, spawn:

```
Agent(model="sonnet", prompt="""
Classify these URLs from a documentation site. For each URL, respond:
- "doc" if it's a documentation/guide/reference page
- "skip" if it's a blog post, changelog, marketing page, or non-documentation

Respond ONLY with a JSON object: {"<url>": "doc"|"skip", ...}

URLs:
<list of URLs>
""")
```

Parse the result and update `filtered_urls.json` — move reclassified URLs from `maybe` to `accepted` or `rejected`.

#### Step 3c: Chunk

```bash
king-scrape <url> --step chunk
```

#### Step 3d: Enrich (sub-agent Haiku)

Read chunks from `.temp-docs/<domain>/chunks/`. Check `.temp-docs/<domain>/enriched/` for existing batch files (resume support).

**For each batch of 5-8 chunks**, spawn:

```
Agent(model="haiku", prompt="""
Generate metadata for these documentation chunks.

For EACH chunk, return:
- keywords: 5-12 specific technical terms
- use_cases: 2-7 scenarios (start with verbs like "Use when", "Configure when")
- tags: 1-5 broad categories
- priority: 1-10 (10 = core concept, 1 = edge case)

Return ONLY a JSON array with one object per chunk, in the SAME ORDER.
Each object: {"keywords": [...], "use_cases": [...], "tags": [...], "priority": N}

Chunks:
---
Chunk 1 - Title: <title>
<content>
---
Chunk 2 - Title: <title>
<content>
---
""")
```

**After each batch**:
1. Parse the JSON array from the sub-agent response
2. Validate each object:
   - `keywords`: list, 5-12 items
   - `use_cases`: list, 2-7 items
   - `tags`: list, 1-5 items
   - `priority`: int, 1-10
3. If validation fails for a chunk, retry once with an individual sub-agent call for that chunk
4. Merge sub-agent metadata with chunk data:
   ```python
   enriched_chunk = {
       "title": chunk["title"],
       "path": chunk["path"],
       "url": chunk["source_url"],  # note: source_url → url
       "content": chunk["content"],
       **subagent_metadata,  # keywords, use_cases, tags, priority
   }
   ```
5. Save cumulative checkpoint: `.temp-docs/<domain>/enriched/batch_NNNN.json`
   - Each batch file contains ALL enriched chunks so far (cumulative)
   - Numbering continues from existing files (e.g., if batch_0002.json exists, next is batch_0003.json)

#### Step 3e: Export

```bash
king-scrape <url> --step export
```

#### Step 3f: Index

```bash
kctx index data/<name>.json
```

Report: "Indexed `<name>` — N sections. Use: `kctx search 'query' --doc <name>`"

---

## Checkpoint Data Contracts

### Chunk input format (from `chunks/<slug>.json`):

```json
{
  "title": "string",
  "breadcrumb": "string",
  "content": "string",
  "source_url": "string",
  "path": "string",
  "token_count": 123
}
```

### Enriched output format (saved to `enriched/batch_NNNN.json`):

Cumulative array — the last batch file has ALL enriched chunks:

```json
[
  {
    "title": "string",
    "path": "string",
    "url": "string",
    "content": "string",
    "keywords": ["string"],
    "use_cases": ["string"],
    "tags": ["string"],
    "priority": 1-10
  }
]
```

**Important**: `url` in enriched = `source_url` from chunk. The sub-agent generates ONLY `keywords`, `use_cases`, `tags`, `priority`. You merge them with the chunk's `title`, `path`, `url`, `content`.

---

## Error Handling

| Error | Action |
|-------|--------|
| `FIRECRAWL_API_KEY` not set | Tell user: "Set FIRECRAWL_API_KEY in .env" |
| `OPENROUTER_API_KEY` not set (Workflow A) | Suggest Workflow B |
| Sub-agent returns invalid JSON | Retry once. If still fails, skip the chunk and warn |
| Sub-agent metadata fails validation | Retry once with individual chunk. If fails, skip and warn |
| Fetch fails for a page | Already handled by scraper (logs and continues) |
| `king-scrape` command fails | Read stderr, report to user with suggestion |
| No chunks generated | "No content extracted. Check if the URL is valid and accessible." |

---

## Batch Size Reference

| Operation | Batch Size | Model | Reason |
|-----------|-----------|-------|--------|
| Filter (Sonnet) | 50 URLs | sonnet | URLs are short strings, Sonnet handles large context |
| Enrich (Haiku) | 5-8 chunks | haiku | ~800 tokens/chunk × 5 = ~4K tokens input, comfortable for Haiku |

---

## Examples

### Simple: scrape with OpenRouter
```
User: "scrape the Stripe docs from https://docs.stripe.com"
→ king-scrape https://docs.stripe.com --yes
→ kctx index data/stripe.json
→ "Indexed stripe — 145 sections."
```

### With sub-agents
```
User: "scrape Stripe docs using claude code"
→ king-scrape https://docs.stripe.com --no-llm-filter --stop-after fetch
→ [Sonnet sub-agent filters maybes]
→ king-scrape https://docs.stripe.com --step chunk
→ [Haiku sub-agents enrich in batches of 5-8]
→ king-scrape https://docs.stripe.com --step export
→ kctx index data/stripe.json
→ "Indexed stripe — 145 sections."
```

### By name (no URL)
```
User: "I want the React docs"
→ [web search: "React official documentation site"]
→ "Found https://react.dev. Scrape this?"
→ [user confirms]
→ [proceeds with chosen workflow]
```

### Resume interrupted scrape
```
User: "scrape https://docs.stripe.com"
→ [detects .temp-docs/docs-stripe-com/ exists]
→ "Found previous scraping for stripe:
    - discover: done (683 URLs)
    - filter: done (606 accepted)
    - fetch: in_progress (42/606 pages)
   Continue from where it left off?"
→ [user confirms]
→ [pipeline auto-resumes from fetch, skipping 42 already-downloaded pages]
```
