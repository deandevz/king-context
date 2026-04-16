# Scraper Workflow — Documentation Scraping Skill

Orchestrate the full documentation scraping pipeline: discover, filter, fetch, chunk, enrich, export, and index.

**Triggers**: "scrape", "scrape docs", "scrape documentation", "index docs from", "crawl docs", "get documentation for", "I want the docs for X", "add docs for X"

---

## Critical Rules

**READ THESE BEFORE DOING ANYTHING:**

1. **You (the orchestrator) NEVER generate enrichment metadata.** Only sub-agents generate keywords/use_cases/tags/priority. If a sub-agent fails, retry or skip — NEVER fill in the data yourself. Generating it yourself is hallucination.
2. **After each sub-agent returns, save a checkpoint file** to `.king-context/_temp/<domain>/enriched/batch_NNNN.json` using a Python script. This is mandatory — `king-scrape --step export` reads these files.
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

work_dir = Path('.king-context/_temp/<DOMAIN_SLUG>')
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

1. Derive work dir: `.king-context/_temp/<domain-slug>/`
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
5. If user wants fresh start → delete the work dir first: `rm -rf .king-context/_temp/<domain-slug>/`

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
kctx index .king-context/data/<name>.json
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
python3 -c "import json; d=json.load(open('.king-context/_temp/<domain>/filtered_urls.json')); print(f'accepted: {len(d[\"accepted\"])}, maybe: {len(d[\"maybe\"])}, rejected: {len(d[\"rejected\"])}')"
```

If maybe > 10, use a Sonnet sub-agent to reclassify (batch of 50 URLs per call). Otherwise skip.

#### Step 4c: Enrich (Haiku sub-agents)

**This is the critical step. Follow the 3 phases exactly.**

##### Phase 1: Prepare batches

Use `Bash` to run a Python script that reads chunks, checks for resume, and writes batch files:

```python
python3 << 'PREP_EOF'
import json
from pathlib import Path

WORK_DIR = Path(".king-context/_temp/<DOMAIN>")
CHUNKS_DIR = WORK_DIR / "chunks"
ENRICHED_DIR = WORK_DIR / "enriched"
ENRICHED_DIR.mkdir(exist_ok=True)
BATCH_SIZE = 7

# Load all chunks
all_chunks = []
for f in sorted(CHUNKS_DIR.glob("*.json")):
    all_chunks.extend(json.loads(f.read_text()))

# Resume: check existing enriched batches
already_enriched = 0
batch_files = sorted(ENRICHED_DIR.glob("batch_*.json"))
if batch_files:
    already_enriched = len(json.loads(batch_files[-1].read_text()))
    print(f"Resume: {already_enriched}/{len(all_chunks)} already enriched")

remaining = all_chunks[already_enriched:]
if not remaining:
    print("All chunks already enriched. Skip to export.")
    exit(0)

# Write batch files to /tmp for sub-agents
batches = []
for i in range(0, len(remaining), BATCH_SIZE):
    batch = remaining[i:i+BATCH_SIZE]
    batch_idx = len(batch_files) + len(batches)
    info = {
        "batch_idx": batch_idx,
        "global_offset": already_enriched + i,
        "chunks": [{"idx": already_enriched + i + j, "title": c["title"], "content": c["content"][:1500]} for j, c in enumerate(batch)],
    }
    path = f"/tmp/enrich_batch_{batch_idx}.json"
    Path(path).write_text(json.dumps(info))
    batches.append({"idx": batch_idx, "count": len(batch), "path": path})

print(f"Prepared {len(batches)} batches ({len(remaining)} chunks)")
for b in batches:
    print(f"  Batch {b['idx']}: {b['count']} chunks → {b['path']}")
PREP_EOF
```

##### Phase 2: Launch ALL Haiku sub-agents in ONE message

**CRITICAL**: Send ALL `Agent` tool calls in a SINGLE message for true parallelism. Use `run_in_background=true` on each one.

For each batch file from Phase 1, spawn one agent:

```
Agent(
  model="haiku",
  run_in_background=true,
  description="Enrich batch N (M chunks)",
  prompt="<see template below>"
)
```

**Sub-agent prompt template** (keep SHORT — Haiku works better with concise prompts):

```
Generate metadata for N documentation chunks. Return a JSON array.

Each object must have:
- "keywords": 5-12 strings (technical terms, API names, methods)
- "use_cases": 2-7 strings (start with verbs: "Use when...", "Configure when...")  
- "tags": 1-5 strings (broad categories)
- "priority": int 1-10 (10=core, 1=edge case)

Return ONLY a JSON array. No markdown, no explanation, no code fences.

Example: [{"keywords":["api-key","auth","bearer"],"use_cases":["Use when authenticating"],"tags":["auth"],"priority":8}]

Chunks:

---CHUNK 0---
Title: <title>
<content>

---CHUNK 1---
Title: <title>
<content>
```

**DO NOT** put validation rules in the sub-agent prompt — keep it short. Validation happens in Phase 3.

##### Phase 3: Validate and save (after EACH agent completes)

As each background agent completes, IMMEDIATELY run this `Bash` validation script. Do NOT wait for all agents — process each as it arrives:

```python
python3 << 'SAVE_EOF'
import json, re
from pathlib import Path

WORK_DIR = Path(".king-context/_temp/<DOMAIN>")
ENRICHED_DIR = WORK_DIR / "enriched"
BATCH_IDX = <N>  # which batch just completed

# 1. Parse sub-agent response
raw = '''<PASTE THE SUB-AGENT'S TEXT RESPONSE HERE>'''

# Extract JSON (handles markdown fences, extra text)
try:
    metadata = json.loads(raw)
except json.JSONDecodeError:
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    metadata = json.loads(match.group()) if match else None
    if not metadata:
        print(f"ERROR batch {BATCH_IDX}: invalid JSON. Retry this batch.")
        exit(1)

# 2. Load chunk data for this batch
batch_info = json.loads(Path(f"/tmp/enrich_batch_{BATCH_IDX}.json").read_text())
all_chunks = []
for f in sorted((WORK_DIR / "chunks").glob("*.json")):
    all_chunks.extend(json.loads(f.read_text()))

# 3. Validate and merge with chunk data
RANGES = {"keywords": (5, 12), "use_cases": (2, 7), "tags": (1, 5)}
merged, failed = [], []

for i, ci in enumerate(batch_info["chunks"]):
    idx = ci["idx"]
    if i >= len(metadata):
        failed.append(idx); continue
    m = metadata[i]
    errs = [f"{k}: need {lo}-{hi}, got {len(m.get(k,[]))}" for k,(lo,hi) in RANGES.items()
            if not isinstance(m.get(k), list) or not (lo <= len(m[k]) <= hi)]
    if not isinstance(m.get("priority"), int) or not (1 <= m.get("priority",0) <= 10):
        errs.append("priority: need int 1-10")
    if errs:
        print(f"  WARN chunk {idx}: {errs}")
        failed.append(idx); continue
    chunk = all_chunks[idx]
    merged.append({
        "title": chunk["title"], "path": chunk["path"],
        "url": chunk["source_url"], "content": chunk["content"],
        "keywords": m["keywords"], "use_cases": m["use_cases"],
        "tags": m["tags"], "priority": m["priority"],
    })

# 4. Save cumulative checkpoint
existing = []
prev = sorted(ENRICHED_DIR.glob("batch_*.json"))
if prev:
    existing = json.loads(prev[-1].read_text())
cumulative = existing + merged
out = ENRICHED_DIR / f"batch_{BATCH_IDX:04d}.json"
out.write_text(json.dumps(cumulative, indent=2))
print(f"Batch {BATCH_IDX}: {len(merged)} ok + {len(failed)} failed → {len(cumulative)} total in {out.name}")
if failed:
    print(f"  Retry these chunks individually: {failed}")
SAVE_EOF
```

##### Retry failed chunks

If any chunks failed validation, retry them ONE AT A TIME with a focused Haiku call:

```
Agent(model="haiku", prompt="Generate metadata for this documentation chunk.
Return ONE JSON object: {\"keywords\":[5-12 items],\"use_cases\":[2-7 items],\"tags\":[1-5 items],\"priority\":1-10}

Title: <title>
<content>")
```

Then run the save script again to add the retried chunk to the cumulative checkpoint.

If retry also fails → skip and warn: "Chunk N skipped — sub-agent couldn't generate valid metadata."

#### Step 4d: Export

After all batches are saved to `enriched/`:

```bash
king-scrape <base_url> --name <name> --step export --no-auto-seed
```

`--no-auto-seed` prevents auto-indexing into the old MCP database.

#### Step 4e: Index

Index into the CLI (`.king-context/`):

```bash
kctx index .king-context/data/<name>.json
```

**NEVER use `seed_data` or `python -m king_context.seed_data`.** Those seed the old MCP server, not the CLI.

Report: "Indexed `<name>` — N sections. Use: `kctx search 'query' --doc <name>`"

---

## Error Handling

| Error | Action |
|-------|--------|
| `FIRECRAWL_API_KEY` not set | Tell user: "Set FIRECRAWL_API_KEY in .env" |
| `OPENROUTER_API_KEY` not set (Workflow A) | Suggest Workflow B |
| Sub-agent returns invalid JSON | Extract from markdown fences. If fails, retry batch once |
| Sub-agent metadata fails validation | Retry individual chunks (not whole batch). If fails, skip + warn |
| Fetch fails for a page | Already handled by scraper (logs and continues) |
| `king-scrape` command fails | Read stderr, report to user with suggestion |
| No chunks generated | "No content extracted. Check if the URL is valid." |
| `kctx index` path too long | Paths with `/` in section names create subdirs — sanitize with Python before indexing |

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
→ kctx index .king-context/data/stripe.json
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
→ Step 4e: kctx index .king-context/data/minimax-tts.json
→ "Indexed minimax-tts — 66 sections."
```

### With sub-agents (full site)
```
User: "scrape Stripe docs using claude code"
→ king-scrape https://docs.stripe.com --name stripe --no-llm-filter --stop-after chunk
→ [Haiku sub-agents enrich batches → Python script saves checkpoints]
→ king-scrape https://docs.stripe.com --name stripe --step export --no-auto-seed
→ kctx index .king-context/data/stripe.json
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
→ [detects .king-context/_temp/docs-stripe-com/ exists]
→ "Found previous scraping for stripe:
    - discover: done (683 URLs)
    - filter: done (606 accepted)
    - fetch: in_progress (42/606 pages)
   Continue from where it left off?"
→ [user confirms]
→ [pipeline auto-resumes, skipping already-downloaded pages]
```
