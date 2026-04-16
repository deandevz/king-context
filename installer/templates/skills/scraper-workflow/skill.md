# Scraper Workflow — Documentation Scraping Skill

Orchestrate the full documentation scraping pipeline: discover, filter, fetch, chunk, enrich, export, and index.

**Triggers**: "scrape", "scrape docs", "scrape documentation", "index docs from", "crawl docs", "get documentation for", "I want the docs for X", "add docs for X"

---

## Critical Rules

**READ THESE BEFORE DOING ANYTHING:**

1. **You (the orchestrator) NEVER generate enrichment metadata.** Only sub-agents generate keywords/use_cases/tags/priority. If a sub-agent fails, retry or skip — NEVER fill in the data yourself. Generating it yourself is hallucination.
2. **After each sub-agent returns, save a checkpoint file** to `.king-context/_temp/<domain>/enriched/batch_NNNN.json` using a Python script. This is mandatory — `.king-context/bin/king-scrape --step export` reads these files.
3. **ALWAYS pass `--name <name>`** to every `king-scrape` command. Without it, the export generates a generic name.
4. **Index with `.king-context/bin/kctx index`** (CLI, stores in `.king-context/`). NEVER use `seed_data` or `python -m king_context.seed_data` — that seeds the old MCP database.
5. **ALWAYS use `--stop-after`** in Workflow B to prevent .king-context/bin/king-scrape from running steps you want to handle via sub-agents.

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

**When there is NO topic filter**: skip Step 2 entirely and let `.king-context/bin/king-scrape <base_url>` handle discover+filter normally.

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
.king-context/bin/king-scrape <base_url> --name <name> --yes --step fetch
```

This resumes from fetch (discover+filter already done via Step 2), then continues through chunk → enrich → export.

**If NO topic filter (scraping everything)**: one command does everything:

```bash
.king-context/bin/king-scrape <base_url> --name <name> --yes
```

This runs: discover → filter (with LLM) → fetch → chunk → enrich → export.

The `--yes` flag skips the enrichment cost confirmation prompt.

After it completes, index into the CLI (NOT seed_data):

```bash
.king-context/bin/kctx index .king-context/data/<name>.json
```

Done. Report: "Indexed `<name>` — N sections."

### Workflow B: Claude Code Sub-Agents

This workflow runs fetch+chunk via `king-scrape`, then enriches via sub-agents, then exports+indexes.

#### Step 4a: Fetch and Chunk

**If topic filter was applied (Step 2)**: work dir has filtered URLs. Fetch + chunk, then stop:

```bash
.king-context/bin/king-scrape <base_url> --name <name> --stop-after chunk --step fetch
```

**If NO topic filter**: discover + heuristic filter + fetch + chunk, then stop:

```bash
.king-context/bin/king-scrape <base_url> --name <name> --no-llm-filter --stop-after chunk
```

**IMPORTANT**: Always use `--stop-after chunk` to prevent .king-context/bin/king-scrape from running enrichment (we'll do that with sub-agents).

#### Step 4b: Smart filter (optional, sub-agent Sonnet)

Only if there are "maybe" URLs. Read the counts:

```bash
python3 -c "import json; d=json.load(open('.king-context/_temp/<domain>/filtered_urls.json')); print(f'accepted: {len(d[\"accepted\"])}, maybe: {len(d[\"maybe\"])}, rejected: {len(d[\"rejected\"])}')"
```

If maybe > 10, use a Sonnet sub-agent to reclassify (batch of 50 URLs per call). Otherwise skip.

#### Step 4c: Enrich (Haiku sub-agents)

**This is the critical step. Follow the 3 phases exactly.**

##### Phase 1: Prepare batch files on disk

Use `Bash` to run a Python script that reads chunks, checks for resume, and **writes batch files to `.king-context/_temp/<DOMAIN>/batches/`**. Sub-agents will read directly from these files.

```python
python3 << 'PREP_EOF'
import json
from pathlib import Path

WORK_DIR = Path(".king-context/_temp/<DOMAIN>")
CHUNKS_DIR = WORK_DIR / "chunks"
ENRICHED_DIR = WORK_DIR / "enriched"
BATCHES_DIR = WORK_DIR / "batches"
ENRICHED_DIR.mkdir(exist_ok=True)
BATCHES_DIR.mkdir(exist_ok=True)
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

# Write batch files to disk for sub-agents to read
total_batches = 0
for i in range(0, len(remaining), BATCH_SIZE):
    batch = remaining[i:i+BATCH_SIZE]
    batch_idx = len(batch_files) + (i // BATCH_SIZE)
    info = {
        "batch_idx": batch_idx,
        "global_offset": already_enriched + i,
        "count": len(batch),
        "chunks": [{"idx": already_enriched + i + j, "title": c["title"], "content": c["content"][:1500]} for j, c in enumerate(batch)],
    }
    (BATCHES_DIR / f"batch_{batch_idx:04d}.json").write_text(json.dumps(info, indent=2))
    total_batches += 1

print(f"Prepared {total_batches} batches ({len(remaining)} chunks)")
print(f"WORK_DIR={WORK_DIR}")
PREP_EOF
```

##### Phase 2: Launch enricher agents ONE AT A TIME, sequentially

**CRITICAL RULES:**
1. **MUST call the `enricher` agent** defined in `.claude/agents/enricher.md`. Use `Agent(description="Enrich batch N", prompt="...")` — the agent is invoked by name via the Agent tool, NOT as a sub-agent type. This is important: calling it as a full agent gives it Bash/Read/Write permissions.
2. **ONE agent at a time, sequentially.** Wait for each to complete before launching the next. Parallel launches lose permissions.
3. The orchestrator sends ONLY the batch number and domain path. The enricher reads chunks from disk, generates metadata, validates, and writes the result — all by itself.
4. **The orchestrator NEVER copies, pastes, or rewrites chunk content or metadata JSON.** All data flows through disk.
5. **NEVER fall back to Workflow A or inline enrichment.** If an enricher agent fails, retry it. If it fails 3 times, skip that batch and continue.

For each batch from Phase 1, launch one agent and wait for it to complete:

```
Agent(
  subagent_type="enricher",
  run_in_background=true,
  description="Enrich batch N",
  prompt="Enrich documentation chunks with metadata. Read your batch, generate metadata, validate, and write results to disk.

Run this script via Bash — fill in your generated metadata where indicated:

python3 << 'ENRICH_EOF'
import json
from pathlib import Path

WORK_DIR = Path(\".king-context/_temp/<DOMAIN>\")
BATCH_FILE = WORK_DIR / \"batches\" / \"batch_<N padded to 4 digits>.json\"
ENRICHED_DIR = WORK_DIR / \"enriched\"
ENRICHED_DIR.mkdir(exist_ok=True)

# 1. Read your batch
batch = json.loads(BATCH_FILE.read_text())
BATCH_IDX = batch[\"batch_idx\"]
OFFSET = batch[\"global_offset\"]
chunks = batch[\"chunks\"]

# Print chunks so you can see them
for c in chunks:
    print(f\"--- Chunk {c['idx']}: {c['title']} ---\")
    print(c['content'][:500])
    print()
ENRICH_EOF

After reading the chunks, generate a JSON array with one metadata object per chunk. Each object must have:
- \"keywords\": 5-12 strings (technical terms, API names, methods)
- \"use_cases\": 2-7 strings starting with verbs (\"Use when...\", \"Configure when...\")
- \"tags\": 1-5 strings (broad categories)
- \"priority\": int 1-10 (10=core, 1=edge case)

Then save by running this script (replace YOUR_JSON_ARRAY with your generated array):

python3 << 'SAVE_EOF'
import json
from pathlib import Path

WORK_DIR = Path(\".king-context/_temp/<DOMAIN>\")
ENRICHED_DIR = WORK_DIR / \"enriched\"
BATCH_FILE = WORK_DIR / \"batches\" / \"batch_<N padded to 4 digits>.json\"
batch = json.loads(BATCH_FILE.read_text())
BATCH_IDX = batch[\"batch_idx\"]
OFFSET = batch[\"global_offset\"]

raw_metadata = YOUR_JSON_ARRAY

# Load full chunk data for merging
all_chunks = []
for f in sorted((WORK_DIR / \"chunks\").glob(\"*.json\")):
    all_chunks.extend(json.loads(f.read_text()))

# Validate and merge
RANGES = {\"keywords\": (5, 12), \"use_cases\": (2, 7), \"tags\": (1, 5)}
merged, failed = [], []
for i, m in enumerate(raw_metadata):
    idx = OFFSET + i
    if idx >= len(all_chunks): break
    errs = [f\"{k}: {len(m.get(k,[]))}\" for k,(lo,hi) in RANGES.items()
            if not isinstance(m.get(k), list) or not (lo <= len(m[k]) <= hi)]
    if not isinstance(m.get(\"priority\"), int) or not (1 <= m.get(\"priority\",0) <= 10):
        errs.append(\"priority\")
    if errs:
        print(f\"WARN chunk {idx}: {errs}\")
        failed.append(idx); continue
    chunk = all_chunks[idx]
    merged.append({
        \"title\": chunk[\"title\"], \"path\": chunk[\"path\"],
        \"url\": chunk[\"source_url\"], \"content\": chunk[\"content\"],
        \"keywords\": m[\"keywords\"], \"use_cases\": m[\"use_cases\"],
        \"tags\": m[\"tags\"], \"priority\": m[\"priority\"],
    })

out = ENRICHED_DIR / f\"batch_{BATCH_IDX:04d}.json\"
out.write_text(json.dumps(merged, indent=2))
print(f\"Batch {BATCH_IDX}: {len(merged)} ok, {len(failed)} failed -> {out.name}\")
SAVE_EOF
"
)
```

##### Phase 3: Verify results (after ALL agents complete)

After all sub-agents finish, the orchestrator runs ONE verification script:

```python
python3 << 'VERIFY_EOF'
import json
from pathlib import Path

WORK_DIR = Path(".king-context/_temp/<DOMAIN>")
ENRICHED_DIR = WORK_DIR / "enriched"

# Load all chunks to get expected count
all_chunks = []
for f in sorted((WORK_DIR / "chunks").glob("*.json")):
    all_chunks.extend(json.loads(f.read_text()))

# Merge all batch files into cumulative checkpoint
all_enriched = []
for bf in sorted(ENRICHED_DIR.glob("batch_*.json")):
    all_enriched.extend(json.loads(bf.read_text()))

# Deduplicate by title (in case of retries)
seen = set()
unique = []
for item in all_enriched:
    if item["title"] not in seen:
        seen.add(item["title"])
        unique.append(item)

# Save final cumulative checkpoint (export.py reads the last batch file)
final = ENRICHED_DIR / f"batch_final.json"
final.write_text(json.dumps(unique, indent=2))

print(f"Total chunks: {len(all_chunks)}")
print(f"Enriched: {len(unique)}")
print(f"Missing: {len(all_chunks) - len(unique)}")
print(f"Saved to: {final.name}")
VERIFY_EOF
```

If `Missing > 0`, retry the missing chunks individually (see below).

##### Retry failed chunks

If any chunks failed validation or are missing, retry them ONE AT A TIME with a focused Haiku call. The sub-agent must also write to disk:

```
Agent(subagent_type="enricher", prompt="Generate metadata for this documentation chunk and save it to disk.

Metadata format: {\"keywords\":[5-12 items],\"use_cases\":[2-7 items],\"tags\":[1-5 items],\"priority\":1-10}

Title: <title>
<content>

After generating, run: python3 -c \"import json; from pathlib import Path; ...save to .king-context/_temp/<DOMAIN>/enriched/retry_<IDX>.json...\"
")
```

Then run the save script again to add the retried chunk to the cumulative checkpoint.

If retry also fails → skip and warn: "Chunk N skipped — sub-agent couldn't generate valid metadata."

#### Step 4d: Export

After all batches are saved to `enriched/`:

```bash
.king-context/bin/king-scrape <base_url> --name <name> --step export --no-auto-seed
```

`--no-auto-seed` prevents auto-indexing into the old MCP database.

#### Step 4e: Index

Index into the CLI (`.king-context/`):

```bash
.king-context/bin/kctx index .king-context/data/<name>.json
```

**NEVER use `seed_data` or `python -m king_context.seed_data`.** Those seed the old MCP server, not the CLI.

Report: "Indexed `<name>` — N sections. Use: `.king-context/bin/kctx search 'query' --doc <name>`"

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
| `.king-context/bin/kctx index` path too long | Paths with `/` in section names create subdirs — sanitize with Python before indexing |

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
→ .king-context/bin/king-scrape https://docs.stripe.com --name stripe --yes
→ .king-context/bin/kctx index .king-context/data/stripe.json
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
→ Step 4a: .king-context/bin/king-scrape ... --name minimax-tts --stop-after chunk --step fetch
→ Step 4c: For each batch of 5-8 chunks:
    → Haiku sub-agent returns JSON array of metadata
    → Python script validates, merges with chunk data, saves to enriched/batch_NNNN.json
→ Step 4d: .king-context/bin/king-scrape ... --name minimax-tts --step export --no-auto-seed
→ Step 4e: .king-context/bin/kctx index .king-context/data/minimax-tts.json
→ "Indexed minimax-tts — 66 sections."
```

### With sub-agents (full site)
```
User: "scrape Stripe docs using claude code"
→ .king-context/bin/king-scrape https://docs.stripe.com --name stripe --no-llm-filter --stop-after chunk
→ [Haiku sub-agents enrich batches → Python script saves checkpoints]
→ .king-context/bin/king-scrape https://docs.stripe.com --name stripe --step export --no-auto-seed
→ .king-context/bin/kctx index .king-context/data/stripe.json
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
