# King Context — Documentation Search Skill

Search indexed documentation efficiently using `kctx` CLI. Find the right section in ≤3 calls.

**Triggers**: documentation lookup, "search docs", "find in docs", library usage questions, "how to use X", "what's the API for X"

---

## Search Strategy

Follow this flowchart for every documentation lookup. Stop as soon as you have the answer.

```
1. Check _learned/     →  known shortcut?  → .king-context/bin/kctx read <doc> <path>  → DONE
2. .king-context/bin/kctx list           →  which doc?
3. .king-context/bin/kctx search "query" →  find section     → got it?
4. .king-context/bin/kctx read --preview →  assess relevance → right section?
5. .king-context/bin/kctx read           →  full content     → DONE
6. Save discovery to _learned/
```

**Rules**:
- ALWAYS check `_learned/` FIRST — costs ~100 tokens, saves thousands
- ALWAYS verify learned paths still exist before using them (`.king-context/bin/kctx read` will error if stale)
- Prefer `.king-context/bin/kctx search` over `.king-context/bin/kctx grep` — metadata search is faster and cheaper
- Use `--preview` before full read — assess relevance before paying full token cost
- Use `.king-context/bin/kctx grep` only when you need to find exact code patterns or API names
- NEVER read all sections — search narrows, preview confirms, then read only what's needed

---

## Query Decomposition

Transform user intent into efficient CLI queries:

| User asks | CLI query |
|-----------|-----------|
| "How to stream audio with ElevenLabs" | `.king-context/bin/kctx search "streaming" --doc elevenlabs-api` |
| "Authentication for the API" | `.king-context/bin/kctx search "auth api-key"` |
| "What WebSocket events are available" | `.king-context/bin/kctx search "websocket events"` |
| "Find where Client( is used" | `.king-context/bin/kctx grep "Client(" --doc httpx` |
| "What topics does the docs cover" | `.king-context/bin/kctx topics elevenlabs-api` |

**Tips**:
- Use 1-2 specific keywords, not full sentences
- Scope to `--doc` when you know which doc
- Use `--top 3` to reduce output tokens
- Keywords match exact terms; use_cases match substrings — "stream" matches "How to stream audio"

---

## CLI Command Reference

### List available docs
```bash
.king-context/bin/kctx list                    # compact table: name, display_name, version, sections
.king-context/bin/kctx list --json             # JSON array
```

### Search by metadata (keywords, use_cases, tags)
```bash
.king-context/bin/kctx search "query"                        # cross-doc search, top 5
.king-context/bin/kctx search "streaming" --doc elevenlabs-api  # scoped to one doc
.king-context/bin/kctx search "auth" --top 3                 # limit results
.king-context/bin/kctx search "query" --json                 # JSON output
```
Returns: title, path, score, first use_case. **No content** — metadata only.

### Read a section
```bash
.king-context/bin/kctx read <doc> <section-path>             # full content
.king-context/bin/kctx read <doc> <section-path> --preview   # first ~200 tokens + total estimate
.king-context/bin/kctx read <doc> <section-path> --json      # JSON output
```
If section not found, suggests similar paths.

### Browse by topic
```bash
.king-context/bin/kctx topics <doc>                          # all tags with sections
.king-context/bin/kctx topics <doc> --tag api-reference      # filter to one tag
.king-context/bin/kctx topics <doc> --json                   # JSON output
```

### Grep content
```bash
.king-context/bin/kctx grep "pattern"                        # regex across all docs
.king-context/bin/kctx grep "Client(" --doc httpx            # scoped to one doc
.king-context/bin/kctx grep "pattern" --context 3            # surrounding lines
.king-context/bin/kctx grep "pattern" --json                 # JSON output
```

### Index documentation
```bash
.king-context/bin/kctx index .king-context/data/example.json # index one doc
.king-context/bin/kctx index --all                           # index all .king-context/data/*.json
```

---

## Self-Learning

After finding a useful section, save a shortcut for future sessions.

### When to save
- You found the right section after searching
- You discovered a gotcha or non-obvious behavior
- You found a pattern that would help answer similar questions

### How to save
Write to `.king-context/_learned/<doc-name>.md`:

```markdown
# <Doc Name> - Learned Shortcuts

## <Topic>
- **<What>** → `<section-path>` section
- Gotcha: <non-obvious behavior>
- Related: `<other-section>` for <reason>

---
Last updated: <date>
```

### Format for each entry
- **Query pattern**: what the user asked
- **Section path**: the section that answered it
- **Gotchas**: anything non-obvious (auth quirks, parameter caveats, etc.)
- **Date**: when this was learned

### Reading learned shortcuts
Before any search, check if a learned file exists:
1. Read `.king-context/_learned/<doc-name>.md`
2. If a shortcut matches the current query, use it directly: `.king-context/bin/kctx read <doc> <path>`
3. If the path no longer exists (stale), fall back to normal search and update the learned file

---

## Good vs Bad Search Strategies

### Good (3 calls, ~400 tokens)
```
.king-context/bin/kctx search "streaming" --doc elevenlabs-api --top 3
→ Found: "WebSocket Streaming" (websocket-streaming) score=8.50

.king-context/bin/kctx read elevenlabs-api websocket-streaming --preview
→ "# WebSocket Streaming\n\nConnect to ws://..." Tokens: 450

.king-context/bin/kctx read elevenlabs-api websocket-streaming
→ Full content
```

### Bad (wasteful, ~3000+ tokens)
```
.king-context/bin/kctx list
.king-context/bin/kctx topics elevenlabs-api
.king-context/bin/kctx read elevenlabs-api getting-started        # wrong section
.king-context/bin/kctx read elevenlabs-api text-to-speech         # still wrong
.king-context/bin/kctx search "websocket streaming audio real-time"  # too many terms
.king-context/bin/kctx read elevenlabs-api websocket-streaming    # finally found it
```
