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

Determine the **base docs URL** for discovery (map) and the **topic filter** if the user wants a subset.

### 1a. Extract base URL

The Firecrawl `map` endpoint needs the **root of the docs site**, not a specific page. If the user gives a deep page URL, strip it to the docs root:

```
User gives:        https://platform.minimax.io/docs/guides/speech-voice-clone
Base URL for map:  https://platform.minimax.io/docs
```

**Rules for extracting base URL**:
- If URL contains `/docs/`, cut at `/docs` (keep `/docs`)
- If URL contains `/api/`, `/reference/`, `/guides/`, cut at that segment
- If URL is already a root (e.g., `https://docs.stripe.com`), use as-is
- When in doubt, use `<scheme>://<host>` (domain root)

The deep page URL the user gave is a **reference hint** for what topic they care about — keep it for step 1c.

### 1b. No URL provided — search or ask

If the user provides only a name (e.g., "MiniMax docs"):

1. Search the web: `"<name> official documentation site"`
2. If found (e.g., `docs.stripe.com`, `reactjs.org/docs`):
   - Confirm: "I found https://docs.stripe.com — should I scrape this?"
3. If not found:
   - Ask: "I couldn't find the docs URL. What's the documentation URL?"

### 1c. Detect topic filter

Check if the user wants only a **subset** of the docs. Signals:

- Explicit topic: "only TTS", "just the audio docs", "only authentication"
- Reference URL implies topic: `/docs/guides/speech-voice-clone` → topic is speech/TTS/voice/audio
- Keyword: "related to", "about", "that covers"

If a topic filter is detected, save it for Step 2a. If not, scrape everything.

---

## Step 2: Discover and Filter by Topic

### 2a. Discover all URLs

Use the Firecrawl map via Python to discover all pages from the **base URL** (not the user's deep link):

```python
python3 -c "
import json, os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path('.env'))
from firecrawl import FirecrawlApp

app = FirecrawlApp(api_key=os.environ['FIRECRAWL_API_KEY'])
result = app.map('<BASE_URL>', limit=5000)
urls = [lnk.url if hasattr(lnk, 'url') else str(lnk) for lnk in result.links]
print(json.dumps(urls, indent=2))
"
```

### 2b. Topic filtering (when user requested a subset)

If a topic filter was detected in Step 1c, filter the discovered URLs **before** fetching.

**Strategy — two-pass filter**:

1. **Keyword pass (fast)**: filter URLs whose path contains topic-related keywords
   ```
   Topic: "TTS/audio"
   Keywords: speech, voice, audio, t2a, tts, clone, cloning, sound
   → Keep URLs matching any keyword in path
   ```

2. **Sonnet pass (if needed)**: if there are ambiguous URLs (e.g., `/docs/guides/pricing` — relevant to speech pricing?), spawn a Sonnet sub-agent to classify:
   ```
   Agent(model="sonnet", prompt="""
   I'm scraping documentation about: <TOPIC DESCRIPTION>

   Classify these URLs — are they relevant to the topic?
   - "keep" if the URL is about or directly related to the topic
   - "skip" if the URL is about something unrelated

   Respond ONLY with JSON: {"<url>": "keep"|"skip", ...}

   URLs:
   <list of ambiguous URLs>
   """)
   ```

3. **Report to user**: "Found N total URLs, filtered to M pages about <topic>. Proceed?"

### 2c. Prepare work directory

Write the filtered URLs into the standard work directory format so `king-scrape` can use them:

```python
python3 -c "
import json
from pathlib import Path

work_dir = Path('.temp-docs/<DOMAIN_SLUG>')
work_dir.mkdir(parents=True, exist_ok=True)

# Write discovered URLs
disc = {'base_url': '<BASE_URL>', 'discovered_at': '<ISO_DATE>', 'total_urls': <TOTAL>, 'urls': <ALL_URLS>}
(work_dir / 'discovered_urls.json').write_text(json.dumps(disc, indent=2))

# Write filtered URLs (only the topic-relevant ones in accepted)
filt = {'accepted': <TOPIC_URLS>, 'rejected': <SKIPPED_URLS>, 'maybe': [], 'filter_method': 'topic', 'llm_fallback_used': False}
(work_dir / 'filtered_urls.json').write_text(json.dumps(filt, indent=2))

# Write manifest
manifest = {
    'discovery': {'status': 'done', 'total_urls': <TOTAL>},
    'filtering': {'status': 'done'}
}
(work_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2))
print(f'Prepared work dir with {len(<TOPIC_URLS>)} URLs')
"
```

This lets you skip `king-scrape`'s discover+filter steps and go straight to fetch.

**When there is NO topic filter**: skip Step 2 entirely and let `king-scrape <base_url>` handle discover+filter normally.

---

## Step 3: Detect Resume

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

## Step 4: Run the Pipeline

### Workflow A: OpenRouter (automated)

**If topic filter was applied (Step 2)**: the work dir already has `filtered_urls.json` with only the relevant URLs and manifest with discover+filter done. Start from fetch:

```bash
king-scrape <base_url> --yes --step fetch
```

This resumes from fetch (discover+filter already done via Step 2), then continues through chunk → enrich → export.

**If NO topic filter (scraping everything)**: one command does everything:

```bash
king-scrape <base_url> --yes
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

#### Step 4a: Fetch pages

**If topic filter was applied (Step 2)**: the work dir already has the filtered URLs. Go straight to fetch:

```bash
king-scrape <base_url> --step fetch
```

**If NO topic filter**: run discover + heuristic filter + fetch:

```bash
king-scrape <base_url> --no-llm-filter --stop-after fetch
```

Fetch has **resume support** — if interrupted, re-running the same command skips already-downloaded pages.

#### Step 4b: Smart filter (optional, sub-agent Sonnet)

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

#### Step 4c: Chunk

```bash
king-scrape <base_url> --step chunk
```

#### Step 4d: Enrich (sub-agent Haiku)

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

#### Step 4e: Export

```bash
king-scrape <base_url> --step export
```

#### Step 4f: Index

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

### Simple: scrape everything with OpenRouter
```
User: "scrape the Stripe docs from https://docs.stripe.com"
→ No topic filter — scrape everything
→ king-scrape https://docs.stripe.com --yes
→ kctx index data/stripe.json
→ "Indexed stripe — 145 sections."
```

### Topic filter: only a subset of docs
```
User: "I want only the TTS/audio docs from https://platform.minimax.io/docs/guides/speech-voice-clone, use claude code"
→ Step 1a: Deep URL detected → base URL = https://platform.minimax.io/docs
→ Step 1c: Topic detected from URL hint + user request → "TTS, audio, speech, voice"
→ Step 2a: Map base URL → 141 URLs found
→ Step 2b: Keyword filter (speech, voice, audio, t2a, clone) → 23 URLs
→ Step 2c: Write work dir with 23 filtered URLs
→ "Found 141 total URLs, filtered to 23 about TTS/audio/speech. Proceed?"
→ [user confirms]
→ Step 4a: king-scrape ... --step fetch (only fetches the 23 URLs)
→ Step 4c-4d: chunk + enrich with Haiku sub-agents
→ Step 4e-4f: export + index
→ "Indexed minimax-tts — 23 sections."
```

### With sub-agents (full site)
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
