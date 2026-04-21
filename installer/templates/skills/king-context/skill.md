# King Context — Documentation Search Skill

Search indexed documentation and research corpora efficiently using `.king-context/bin/kctx`. Find the right section in ≤3 calls.

**Triggers**: documentation lookup, "search docs", "find in docs", library usage questions, "how to use X", "what's the API for X", "what does our research say about X"

---

## Two Stores, One CLI

King Context keeps two separate stores:

| Store | Populated by | What's in it |
|---|---|---|
| `docs` | `.king-context/bin/king-scrape <url>` | Scraped product/API documentation |
| `research` | `.king-context/bin/king-research <topic>` | Topic-driven research corpora from the open web |

Every `kctx` command is source-aware:
- Default: searches **both** stores, merged by score.
- `--source docs|research` scopes to one store.
- `--doc <name>` scopes to a single doc (works across stores — most precise filter).

Every search/grep hit is prefixed `[docs]` or `[research]` so you can tell the source at a glance.

---

## Search Strategy

```
1. Check _learned/                           →  known shortcut?  → .king-context/bin/kctx read <doc> <path>  → DONE
2. .king-context/bin/kctx list               →  which doc + which store?
3. .king-context/bin/kctx search "query"     →  find section     → got it?
4. .king-context/bin/kctx read --preview     →  assess relevance → right section?
5. .king-context/bin/kctx read               →  full content     → DONE
6. Save discovery to _learned/
```

**Rules**:
- ALWAYS check `_learned/` FIRST — costs ~100 tokens, saves thousands.
- ALWAYS verify learned paths still exist before using them (`.king-context/bin/kctx read` errors if stale).
- Prefer `.king-context/bin/kctx search` over `.king-context/bin/kctx grep` — metadata search is faster and cheaper.
- Use `--preview` before full read — assess relevance before paying full token cost.
- Use `.king-context/bin/kctx grep` only for exact code patterns, API names, or error strings.
- **Scope aggressively**: `--doc <name>` > `--source <store>` > unfiltered.
- NEVER read all sections — search narrows, preview confirms, then read only what's needed.

---

## Picking a Filter (decision tree)

```
User asks about a specific library/product/SDK?  → --doc <name>
User asks about a research topic you scraped?    → --doc <research-slug>
User asks something generic, unsure which doc?   → --source docs or --source research
User asks "is it anywhere in our indexed stuff?" → no filter (search both)
```

`--doc` is the sharpest tool. Run `.king-context/bin/kctx list` once if you don't know the name.

---

## Query Decomposition

Transform user intent into efficient CLI queries:

| User asks | CLI query |
|-----------|-----------|
| "How to stream audio with ElevenLabs" | `.king-context/bin/kctx search "streaming" --doc elevenlabs-api` |
| "Authentication for the Exa API" | `.king-context/bin/kctx search "auth api-key" --doc exa` |
| "What does our research say on Chain of Thought" | `.king-context/bin/kctx search "chain of thought" --source research` |
| "Compare ToT vs CoT — anything indexed?" | `.king-context/bin/kctx search "tree of thoughts" --source research --top 5` |
| "Is rate limiting documented anywhere?" | `.king-context/bin/kctx search "rate limit"` (both stores) |
| "Find where `Client(` is used in httpx" | `.king-context/bin/kctx grep "Client\\(" --doc httpx` |
| "What topics does the docs cover" | `.king-context/bin/kctx topics elevenlabs-api` |
| "Show only our research corpora" | `.king-context/bin/kctx list research` |

**Tips**:
- Use 1–2 specific keywords, not full sentences.
- Scope to `--doc` when you know which doc.
- Use `--top 3` to reduce output tokens.
- Keywords match exact terms; use_cases match substrings — "stream" matches "How to stream audio".

---

## CLI Command Reference

### List indexed content
```bash
.king-context/bin/kctx list                    # both stores with == Docs == / == Research == headers
.king-context/bin/kctx list docs               # only scraped docs
.king-context/bin/kctx list research           # only research corpora
.king-context/bin/kctx list --json             # JSON (grouped dict when "all", flat list when filtered)
```

### Search by metadata (keywords, use_cases, tags)
```bash
.king-context/bin/kctx search "query"                              # cross-store, top 5, merged by score
.king-context/bin/kctx search "streaming" --doc elevenlabs-api     # scoped to a single doc (auto-resolves store)
.king-context/bin/kctx search "reasoning" --source research        # only research corpora
.king-context/bin/kctx search "livecrawl" --source docs            # only scraped docs
.king-context/bin/kctx search "auth" --top 3                       # limit results
.king-context/bin/kctx search "query" --json                       # JSON output
```
Output tags every hit with `[docs]` or `[research]`. Returns title, path, score, first use_case. **No content** — metadata only.

### Read a section
```bash
.king-context/bin/kctx read <doc> <section-path>             # full content (auto-finds the store)
.king-context/bin/kctx read <doc> <section-path> --preview   # first ~200 tokens + total estimate
.king-context/bin/kctx read <doc> <section-path> --source research   # force store (rarely needed)
.king-context/bin/kctx read <doc> <section-path> --json      # JSON output
```
If the doc name isn't unique, pass `--source`. If section not found, suggests similar paths.

### Browse by topic
```bash
.king-context/bin/kctx topics <doc>                          # all tags with sections
.king-context/bin/kctx topics <doc> --tag api-reference      # filter to one tag
.king-context/bin/kctx topics <doc> --source research        # disambiguate if needed
.king-context/bin/kctx topics <doc> --json                   # JSON output
```

### Grep content
```bash
.king-context/bin/kctx grep "pattern"                        # regex across both stores
.king-context/bin/kctx grep "Client\\(" --doc httpx          # scoped to one doc
.king-context/bin/kctx grep "livecrawl" --source docs        # scoped to docs store
.king-context/bin/kctx grep "pattern" --context 3            # surrounding lines
.king-context/bin/kctx grep "pattern" --json                 # JSON output
```

### Index / re-index
```bash
.king-context/bin/kctx index .king-context/data/example.json         # auto-detects via section.source_type
.king-context/bin/kctx index .king-context/data/research/topic.json  # also auto-detected as research
.king-context/bin/kctx index <path> --source research                # force-route to research store
.king-context/bin/kctx index --all                                   # walks data/*.json + data/research/*.json
```

---

## Generating New Content

Two producers feed the stores:

```bash
# Scrape a product/API doc site → .king-context/docs/<name>/
.king-context/bin/king-scrape https://docs.example.com

# Research a topic from the open web → .king-context/research/<slug>/
.king-context/bin/king-research "prompt engineering techniques" --basic     # 3 queries, no deepening
.king-context/bin/king-research "retrieval augmented generation" --medium   # 5 queries + 1 deepening iteration
.king-context/bin/king-research "mixture of experts" --high                 # 8 + 2 iterations
.king-context/bin/king-research "<topic>" --extrahigh                       # 12 + 3 iterations (most thorough)
```

Both auto-index on completion — the new doc is immediately searchable via `kctx`. `king-research` outputs are tagged `source_type: "research"` in every section so `--source research` and the `[research]` prefix work automatically.

---

## Self-Learning

After finding a useful section, save a shortcut for future sessions.

### When to save
- You found the right section after searching.
- You discovered a gotcha or non-obvious behavior.
- You found a pattern that would help answer similar questions.

### How to save
Write to `.king-context/_learned/<doc-name>.md`:

```markdown
# <Doc Name> - Learned Shortcuts

## <Topic>
- **<What>** → `<section-path>` section
- Store: docs | research
- Gotcha: <non-obvious behavior>
- Related: `<other-section>` for <reason>

---
Last updated: <date>
```

Tracking the store lets you skip `kctx list` on the next lookup.

### Reading learned shortcuts
Before any search:
1. Read `.king-context/_learned/<doc-name>.md`.
2. If a shortcut matches the current query, use it directly: `.king-context/bin/kctx read <doc> <path>`.
3. If the path no longer exists (stale), fall back to normal search and update the learned file.

---

## Good vs Bad Search Strategies

### Good (3 calls, ~400 tokens)
```
.king-context/bin/kctx search "streaming" --doc elevenlabs-api --top 3
→ 1. [docs] WebSocket Streaming (elevenlabs-api/websocket-streaming) score=8.50

.king-context/bin/kctx read elevenlabs-api websocket-streaming --preview
→ "# WebSocket Streaming\n\nConnect to ws://..." Tokens: 450

.king-context/bin/kctx read elevenlabs-api websocket-streaming
→ Full content
```

### Good (research-scoped, 2 calls)
```
.king-context/bin/kctx search "zero shot cot" --source research --top 3
→ 1. [research] Zero-Shot CoT (prompt-engineering-techniques/ai-prompt-engineering-...) score=12.50

.king-context/bin/kctx read prompt-engineering-techniques ai-prompt-engineering-patterns-cot-react-tot-zero-shot-cot
→ Full content
```

### Bad (wasteful, ~3000+ tokens)
```
.king-context/bin/kctx list
.king-context/bin/kctx topics elevenlabs-api
.king-context/bin/kctx read elevenlabs-api getting-started              # wrong section
.king-context/bin/kctx read elevenlabs-api text-to-speech               # still wrong
.king-context/bin/kctx search "websocket streaming audio real-time"     # too many terms
.king-context/bin/kctx read elevenlabs-api websocket-streaming          # finally found it
```
