# King Context — Documentation Search Skill

Search indexed documentation and research corpora efficiently using `kctx`. Find the right section in ≤3 calls.

**Triggers**: documentation lookup, "search docs", "find in docs", library usage questions, "how to use X", "what's the API for X", "what does our research say about X"

---

## Two Stores, One CLI

King Context keeps two separate stores:

| Store | Populated by | What's in it |
|---|---|---|
| `docs` | `king-scrape <url>` | Scraped product/API documentation (e.g. `exa`, `elevenlabs-api`, `httpx`) |
| `research` | `king-research <topic>` | Topic-driven research corpora pulled from the open web (e.g. `prompt-engineering-techniques`) |

Every `kctx` command is source-aware:
- Default: searches **both** stores, merged by score.
- `--source docs|research` scopes to one store.
- `--doc <name>` scopes to a single doc (works across stores — most precise filter).

Every search/grep hit is prefixed `[docs]` or `[research]` so you can tell the source at a glance.

---

## Search Strategy

```
1. Check _learned/     →  known shortcut?  → kctx read <doc> <path>  → DONE
2. kctx list           →  which doc + which store?
3. kctx search "query" →  find section     → got it?
4. kctx read --preview →  assess relevance → right section?
5. kctx read           →  full content     → DONE
6. Save discovery to _learned/
```

**Rules**:
- ALWAYS check `_learned/` FIRST — costs ~100 tokens, saves thousands.
- ALWAYS verify learned paths still exist before using them (`kctx read` errors if stale).
- Prefer `kctx search` over `kctx grep` — metadata search is faster and cheaper.
- Use `--preview` before full read — assess relevance before paying full token cost.
- Use `kctx grep` only for exact code patterns, API names, or error strings.
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

`--doc` is the sharpest tool. Run `kctx list` once if you don't know the name.

---

## Query Decomposition

Transform user intent into efficient CLI queries:

| User asks | CLI query |
|-----------|-----------|
| "How to stream audio with ElevenLabs" | `kctx search "streaming" --doc elevenlabs-api` |
| "Authentication for the Exa API" | `kctx search "auth api-key" --doc exa` |
| "What does our research say on Chain of Thought" | `kctx search "chain of thought" --source research` |
| "Compare ToT vs CoT — anything indexed?" | `kctx search "tree of thoughts" --source research --top 5` |
| "Is rate limiting documented anywhere?" | `kctx search "rate limit"` (both stores) |
| "Find where `Client(` is used in httpx" | `kctx grep "Client\\(" --doc httpx` |
| "What topics does the docs cover" | `kctx topics elevenlabs-api` |
| "Show only our research corpora" | `kctx list research` |

**Tips**:
- Use 1–2 specific keywords, not full sentences.
- Scope to `--doc` when you know which doc.
- Use `--top 3` to reduce output tokens.
- Keywords match exact terms; use_cases match substrings — "stream" matches "How to stream audio".

---

## CLI Command Reference

### List indexed content
```bash
kctx list                    # both stores with == Docs == / == Research == headers
kctx list docs               # only scraped docs
kctx list research           # only research corpora
kctx list --json             # JSON (grouped dict when "all", flat list when filtered)
```

### Search by metadata (keywords, use_cases, tags)
```bash
kctx search "query"                              # cross-store, top 5, merged by score
kctx search "streaming" --doc elevenlabs-api     # scoped to a single doc (auto-resolves store)
kctx search "reasoning" --source research        # only research corpora
kctx search "livecrawl" --source docs            # only scraped docs
kctx search "auth" --top 3                       # limit results
kctx search "query" --json                       # JSON output
```
Output tags every hit with `[docs]` or `[research]`. Returns title, path, score, first use_case. **No content** — metadata only.

### Read a section
```bash
kctx read <doc> <section-path>             # full content (auto-finds the store)
kctx read <doc> <section-path> --preview   # first ~200 tokens + total estimate
kctx read <doc> <section-path> --source research   # force store (rarely needed)
kctx read <doc> <section-path> --json      # JSON output
```
If the doc name isn't unique, pass `--source`. If section not found, suggests similar paths.

### Browse by topic
```bash
kctx topics <doc>                          # all tags with sections
kctx topics <doc> --tag api-reference      # filter to one tag
kctx topics <doc> --source research        # disambiguate if needed
kctx topics <doc> --json                   # JSON output
```

### Grep content
```bash
kctx grep "pattern"                        # regex across both stores
kctx grep "Client\\(" --doc httpx          # scoped to one doc
kctx grep "livecrawl" --source docs        # scoped to docs store
kctx grep "pattern" --context 3            # surrounding lines
kctx grep "pattern" --json                 # JSON output
```

### Index / re-index
```bash
kctx index .king-context/data/example.json         # auto-detects via section.source_type
kctx index .king-context/data/research/topic.json  # also auto-detected as research
kctx index <path> --source research                # force-route to research store
kctx index --all                                   # walks data/*.json + data/research/*.json
```

---

## Generating New Content

Two producers feed the stores:

```bash
# Scrape a product/API doc site → .king-context/docs/<name>/
king-scrape https://docs.example.com

# Research a topic from the open web → .king-context/research/<slug>/
king-research "prompt engineering techniques" --basic     # 3 queries, no deepening
king-research "retrieval augmented generation" --medium   # 5 queries + 1 deepening iteration
king-research "mixture of experts" --high                 # 8 + 2 iterations
king-research "<topic>" --extrahigh                       # 12 + 3 iterations (most thorough)
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
2. If a shortcut matches the current query, use it directly: `kctx read <doc> <path>`.
3. If the path no longer exists (stale), fall back to normal search and update the learned file.

---

## Good vs Bad Search Strategies

### Good (3 calls, ~400 tokens)
```
kctx search "streaming" --doc elevenlabs-api --top 3
→ 1. [docs] WebSocket Streaming (elevenlabs-api/websocket-streaming) score=8.50

kctx read elevenlabs-api websocket-streaming --preview
→ "# WebSocket Streaming\n\nConnect to ws://..." Tokens: 450

kctx read elevenlabs-api websocket-streaming
→ Full content
```

### Good (research-scoped, 2 calls)
```
kctx search "zero shot cot" --source research --top 3
→ 1. [research] Zero-Shot CoT (prompt-engineering-techniques/ai-prompt-engineering-...) score=12.50

kctx read prompt-engineering-techniques ai-prompt-engineering-patterns-cot-react-tot-zero-shot-cot
→ Full content
```

### Bad (wasteful, ~3000+ tokens)
```
kctx list
kctx topics elevenlabs-api
kctx read elevenlabs-api getting-started              # wrong section
kctx read elevenlabs-api text-to-speech               # still wrong
kctx search "websocket streaming audio real-time"     # too many terms
kctx read elevenlabs-api websocket-streaming          # finally found it
```
