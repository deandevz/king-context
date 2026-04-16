# Scraper Workflow — Documentation Scraping Skill

Orchestrate the full documentation scraping pipeline: discover, filter, fetch, chunk, enrich, export, and index.

**Triggers**: "scrape", "scrape docs", "scrape documentation", "index docs from", "crawl docs", "get documentation for", "I want the docs for X", "add docs for X"

---

## Critical Rules

**READ THESE BEFORE DOING ANYTHING:**

1. **You (the orchestrator) NEVER generate enrichment metadata.** Only sub-agents generate keywords/use_cases/tags/priority. If a sub-agent fails, retry or skip — NEVER fill in the data yourself. Generating it yourself is hallucination.
2. **After each sub-agent returns, save a checkpoint file** to `.temp-docs/<domain>/enriched/batch_NNNN.json` using a Python script. This is mandatory — `king-scrape --step export` reads these files.
3. **ALWAYS pass `--name <name>`** to every `king-scrape` command. Without it, the export generates a generic name.
4. **Index with `kctx index`** (CLI, stores in `.king-context/`). NEVER use `seed_data` or `python -m king_context.seed_data` — that seeds the old MCP database.
5. **ALWAYS use `--stop-after`** in Workflow B to prevent king-scrape from running steps you want to handle via sub-agents.

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
king-scrape <base_url> --name <name> --yes --step fetch
```

This resumes from fetch (discover+filter already done via Step 2), then continues through chunk → enrich → export.

**If NO topic filter (scraping everything)**: one command does everything:

```bash
king-scrape <base_url> --name <name> --yes
```

This runs: discover → filter (with LLM) → fetch → chunk → enrich → export.

The `--yes` flag skips the enrichment cost confirmation prompt.

After it completes, index into the CLI (NOT seed_data):

```bash
kctx index data/<name>.json
```

Done. Report: "Indexed `<name>` — N sections."

### Workflow B: Claude Code Sub-Agents

This workflow runs fetch+chunk via `king-scrape`, then enriches via sub-agents, then exports+indexes.

#### Step 4a: Fetch and Chunk

**If topic filter was applied (Step 2)**: work dir has filtered URLs. Fetch + chunk, then stop:

```bash
king-scrape <base_url> --name <name> --stop-after chunk --step fetch
```

**If NO topic filter**: discover + heuristic filter + fetch + chunk, then stop:

```bash
king-scrape <base_url> --name <name> --no-llm-filter --stop-after chunk
```

**IMPORTANT**: Always use `--stop-after chunk` to prevent king-scrape from running enrichment (we'll do that with sub-agents).

#### Step 4b: Smart filter (optional, sub-agent Sonnet)

Only if there are "maybe" URLs. Read the counts:

```bash
python3 -c "import json; d=json.load(open('.temp-docs/<domain>/filtered_urls.json')); print(f'accepted: {len(d[\"accepted\"])}, maybe: {len(d[\"maybe\"])}, rejected: {len(d[\"rejected\"])}')"
```

If maybe > 10, use a Sonnet sub-agent to reclassify (batch of 50 URLs per call). Otherwise skip.

#### Step 4c: Enrich (sub-agent Haiku)

**This is the critical step. Follow exactly.**

1. Read all chunks from `.temp-docs/<domain>/chunks/`
2. Check `.temp-docs/<domain>/enriched/` for existing batch files (resume)
3. Split remaining chunks into batches of 5-8

**For each batch**, spawn a Haiku sub-agent. The sub-agent prompt MUST include:
- The exact chunks to enrich (title + content)
- Clear instruction to return ONLY a JSON array
- The validation rules

**Sub-agent prompt template:**

```
Agent(model="haiku", prompt="""
You are a documentation metadata specialist. Generate metadata for these chunks.

For EACH chunk below, generate:
- keywords: 5-12 specific technical terms (API names, methods, config keys)
- use_cases: 2-7 practical scenarios (start with verbs: "Use when", "Configure when")
- tags: 1-5 broad category labels
- priority: integer 1-10 (10 = core concept, 1 = edge case)

RESPOND WITH ONLY A VALID JSON ARRAY. No explanation, no markdown, no code fences.
One object per chunk, SAME ORDER as input.

Example output format:
[{"keywords":["k1","k2","k3","k4","k5"],"use_cases":["Use when...","Configure when..."],"tags":["api"],"priority":7},{"keywords":["k1","k2","k3","k4","k5"],"use_cases":["Use when..."],"tags":["guide"],"priority":5}]

Chunks to enrich:

---CHUNK 0---
Title: <title>
<content>

---CHUNK 1---
Title: <title>
<content>
""")
```

**After EACH sub-agent returns — run a Python script to validate, merge, and save:**

This is NOT optional. You MUST run this script after each sub-agent batch. Do NOT do the merging yourself — use this script:

```python
python3 << 'ENRICH_EOF'
import json
from pathlib import Path

WORK_DIR = Path(".temp-docs/<domain>")
ENRICHED_DIR = WORK_DIR / "enriched"
ENRICHED_DIR.mkdir(exist_ok=True)

# Sub-agent raw response (paste the JSON array the sub-agent returned)
raw_response = '''<PASTE SUB-AGENT JSON RESPONSE HERE>'''

# Parse sub-agent response
try:
    metadata_list = json.loads(raw_response)
except json.JSONDecodeError:
    # Try to extract JSON from markdown fences
    import re
    match = re.search(r'\[.*\]', raw_response, re.DOTALL)
    if match:
        metadata_list = json.loads(match.group())
    else:
        print("ERROR: Sub-agent did not return valid JSON. Retry this batch.")
        exit(1)

# The chunks for this batch (indices into the full chunk list)
batch_chunk_indices = <LIST_OF_CHUNK_INDICES>  # e.g., [0,1,2,3,4,5,6]

# Load all chunks
all_chunks = []
for f in sorted((WORK_DIR / "chunks").glob("*.json")):
    all_chunks.extend(json.loads(f.read_text()))

# Validate and merge
VALID_RANGES = {"keywords": (5, 12), "use_cases": (2, 7), "tags": (1, 5)}
failed = []
merged = []

for i, idx in enumerate(batch_chunk_indices):
    if i >= len(metadata_list):
        failed.append(idx)
        continue
    m = metadata_list[i]
    chunk = all_chunks[idx]
    errors = []
    for field, (lo, hi) in VALID_RANGES.items():
        if not isinstance(m.get(field), list) or not (lo <= len(m[field]) <= hi):
            errors.append(f"{field}: expected {lo}-{hi} items")
    if not isinstance(m.get("priority"), int) or not (1 <= m["priority"] <= 10):
        errors.append("priority: must be int 1-10")
    if errors:
        print(f"  WARNING: chunk {idx} failed validation: {errors}")
        failed.append(idx)
        continue
    merged.append({
        "title": chunk["title"],
        "path": chunk["path"],
        "url": chunk["source_url"],
        "content": chunk["content"],
        "keywords": m["keywords"],
        "use_cases": m["use_cases"],
        "tags": m["tags"],
        "priority": m["priority"],
    })

# Load existing enriched data (cumulative)
existing = []
batch_files = sorted(ENRICHED_DIR.glob("batch_*.json"))
if batch_files:
    existing = json.loads(batch_files[-1].read_text())

# Save cumulative checkpoint
all_enriched = existing + merged
batch_num = len(batch_files)
out_path = ENRICHED_DIR / f"batch_{batch_num:04d}.json"
out_path.write_text(json.dumps(all_enriched, indent=2))
print(f"Saved {len(merged)} new + {len(existing)} existing = {len(all_enriched)} total to {out_path.name}")
if failed:
    print(f"Failed chunks (retry individually): {failed}")
ENRICH_EOF
```

**If chunks fail validation**: retry those specific chunks individually with a single Haiku sub-agent call per chunk. If still fails, skip and warn the user.

**NEVER write enrichment data yourself. The Python script above does the merging.**

#### Step 4d: Export

After all batches are saved to `enriched/`, run export:

```bash
king-scrape <base_url> --name <name> --step export --no-auto-seed
```

Use `--no-auto-seed` to prevent auto-indexing into the MCP database.

#### Step 4e: Index

Index into the CLI (`.king-context/`):

```bash
kctx index data/<name>.json
```

**NEVER use `seed_data` or `python -m king_context.seed_data`.** Those seed the old MCP server database, not the CLI.

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
→ king-scrape https://docs.stripe.com --name stripe --yes
→ kctx index data/stripe.json
→ "Indexed stripe — 145 sections."
```

### Topic filter with sub-agents
```
User: "I want only the TTS/audio docs from https://platform.minimax.io/docs/guides/speech-voice-clone, use claude code"
→ Step 1a: Deep URL → base = https://platform.minimax.io/docs
→ Step 1c: Topic = "TTS, audio, speech, voice"
→ Step 2a: Map base URL → 141 URLs
→ Step 2b: Keyword filter → 23 TTS URLs
→ Step 2c: Write work dir with 23 filtered URLs
→ "Found 141 total, filtered to 23 TTS/audio pages. Proceed?"
→ Step 4a: king-scrape ... --name minimax-tts --stop-after chunk --step fetch
→ Step 4c: For each batch of 5-8 chunks:
    → Haiku sub-agent returns JSON array of metadata
    → Python script validates, merges with chunk data, saves to enriched/batch_NNNN.json
→ Step 4d: king-scrape ... --name minimax-tts --step export --no-auto-seed
→ Step 4e: kctx index data/minimax-tts.json
→ "Indexed minimax-tts — 66 sections."
```

### With sub-agents (full site)
```
User: "scrape Stripe docs using claude code"
→ king-scrape https://docs.stripe.com --name stripe --no-llm-filter --stop-after chunk
→ [Haiku sub-agents enrich batches → Python script saves checkpoints]
→ king-scrape https://docs.stripe.com --name stripe --step export --no-auto-seed
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
→ [pipeline auto-resumes, skipping already-downloaded pages]
```
