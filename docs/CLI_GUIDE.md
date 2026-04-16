# King Context CLI Guide

The `kctx` CLI is how AI agents (and humans) search indexed documentation. This guide covers all commands, the recommended search strategy, and real-world usage examples.

---

## Commands

### `kctx list`

List all indexed documentation.

```bash
$ kctx list
Available documentation:
  elevenlabs-api  187 sections
  minimax-tts      66 sections
  openrouter       14 sections
```

Use this first to discover what's available. Costs ~50 tokens.

### `kctx search <query>`

Search across all docs (or a specific doc) by keywords and use cases. Returns metadata only — titles, scores, and use_case hints. No content.

```bash
$ kctx search "text to speech audio"
1. T2A HTTP API Reference (minimax-tts/speech-t2a-http-content) score=14.50
   Use when implementing synchronous text-to-speech via HTTP
2. WebSocket Streaming (minimax-tts/speech-t2a-websocket) score=11.20
   Use when implementing real-time TTS streaming

$ kctx search "auth" --doc elevenlabs-api --top 3
1. Authentication (elevenlabs-api/authentication) score=18.00
   Use when configuring API authentication
```

Flags:
- `--doc <name>` — search within a specific documentation
- `--top N` — limit results (default: 5)
- `--json` — machine-parseable output

### `kctx read <doc> <path>`

Read a section's full content. Use `--preview` first to check relevance before paying the full token cost.

```bash
# Preview: titles, metadata, first ~400 tokens
$ kctx read minimax-tts speech-t2a-http-content --preview

# Full read: complete section content
$ kctx read minimax-tts speech-t2a-http-content
```

If the path is ambiguous, `kctx read` suggests matching paths:

```bash
$ kctx read elevenlabs-api auth
Did you mean?
  elevenlabs-api/authentication
  elevenlabs-api/auth-websocket
```

### `kctx topics <doc>`

Browse a documentation by topic tags.

```bash
$ kctx topics minimax-tts
Topics for minimax-tts:
  api-reference    28 sections
  voice-cloning     8 sections
  configuration     6 sections
  guides            5 sections

$ kctx topics minimax-tts --tag voice-cloning
Sections tagged "voice-cloning":
  voice-cloning-intro
  voice-cloning-clone
  voice-cloning-upload-audio
  ...
```

### `kctx grep <pattern>`

Search inside section content for exact patterns. Use when you know the specific API name, method, or error code.

```bash
$ kctx grep "Bearer" --doc minimax-tts
minimax-tts/speech-t2a-http-content:
  Authorization: Bearer {api_key}

$ kctx grep "WebSocket" --doc elevenlabs-api --context 3
elevenlabs-api/websocket-streaming:
  ## WebSocket Connection
  Connect to wss://api.elevenlabs.io/v1/...
  The WebSocket accepts JSON frames with...
```

Flags:
- `--doc <name>` — search within a specific doc
- `--context N` — show N lines of context around matches
- `--json` — machine-parseable output

### `kctx index <path>`

Index a documentation JSON file into the `.king-context/` data store.

```bash
# Index one doc
$ kctx index data/stripe.json
Indexed stripe: 145 sections

# Index all docs
$ kctx index --all
Indexed elevenlabs-api: 187 sections
Indexed minimax-tts: 66 sections
Indexed openrouter: 14 sections
```

---

## Recommended Search Strategy

The optimal pattern for finding documentation is **progressive disclosure** — start cheap, go deeper only when needed:

```
1. kctx list                          → what docs exist? (~50 tokens)
2. kctx search "query"                → which section? (~100 tokens)
3. kctx read <doc> <path> --preview   → is this the right one? (~400 tokens)
4. kctx read <doc> <path>             → full content (~1,000 tokens)
```

Most lookups resolve at step 2 or 3. You rarely need to read more than 1-2 full sections.

### When to use which command

| You want to... | Use |
|---|---|
| Find which section covers a topic | `kctx search "topic"` |
| Check if a section is relevant before reading | `kctx read <doc> <path> --preview` |
| Read the full API reference | `kctx read <doc> <path>` |
| Find a specific method/class/error code | `kctx grep "pattern"` |
| Explore what topics a doc covers | `kctx topics <doc>` |
| See all available docs | `kctx list` |

---

## Usage Examples with Claude Code

These are real scenarios showing how to ask Claude to use King Context.

### Example 1: Implement an API you've never used

**You say:**
> "Use the MiniMax TTS API to convert text to speech. Check king-context for the docs."

**What Claude does:**
```
kctx list                                    → finds "minimax-tts" (66 sections)
kctx search "text to speech HTTP"            → finds speech-t2a-http-content (score 14.50)
kctx read minimax-tts speech-t2a-http --preview  → confirms it's the endpoint reference
kctx read minimax-tts speech-t2a-http        → reads full API spec (1,114 tokens)
→ writes working code
```

Total docs consumed: ~2,800 tokens. Result: working code on first try.

### Example 2: Debug a specific error

**You say:**
> "I'm getting a 401 from the ElevenLabs API. Check the docs for auth setup."

**What Claude does:**
```
kctx search "authentication api-key" --doc elevenlabs-api
kctx read elevenlabs-api authentication --preview
→ finds the issue (wrong header format)
```

### Example 3: Explore an unfamiliar API

**You say:**
> "What can the ElevenLabs API do? I want an overview."

**What Claude does:**
```
kctx topics elevenlabs-api                   → lists all topic categories
kctx topics elevenlabs-api --tag getting-started
kctx read elevenlabs-api quickstart --preview
```

### Example 4: Find exact code patterns

**You say:**
> "How do I set up WebSocket streaming with ElevenLabs? Show me the connection code."

**What Claude does:**
```
kctx grep "WebSocket" --doc elevenlabs-api --context 5
kctx read elevenlabs-api websocket-streaming
→ gets the exact connection setup code
```

### Example 5: Compare approaches

**You say:**
> "Should I use HTTP or WebSocket for MiniMax TTS? Check the docs."

**What Claude does:**
```
kctx search "HTTP synchronous" --doc minimax-tts
kctx search "WebSocket streaming" --doc minimax-tts
kctx read minimax-tts speech-t2a-http --preview
kctx read minimax-tts speech-t2a-websocket --preview
→ compares both approaches from the previews alone (~800 tokens total)
```

### Example 6: Scrape and use new docs

**You say:**
> "I need the Stripe API docs. Scrape them, then help me implement a payment flow."

**What Claude does (with scraper-workflow skill):**
```
king-scrape https://docs.stripe.com --name stripe --yes
kctx index data/stripe.json
kctx search "payment intent create" --doc stripe
kctx read stripe payment-intents-create
→ implements payment flow from freshly scraped docs
```

---

## Tips for Effective Searches

### Good queries (specific, keyword-based)
```
kctx search "WebSocket streaming audio"
kctx search "voice cloning API"
kctx search "rate limits concurrency"
```

### Less effective queries (natural language)
```
kctx search "how do I stream audio in real time"     # too verbose
kctx search "what are the limits"                      # too vague
```

The search engine matches against keywords and use_cases in the metadata. Use technical terms, API names, and specific concepts for best results.

### Use grep for exact matches
```
kctx grep "sample_rate"           # find a specific parameter
kctx grep "Error 429"             # find error handling docs
kctx grep "class Client"          # find SDK class definitions
```

---

## Machine-Readable Output

All commands support `--json` for integration with scripts and tools:

```bash
$ kctx search "auth" --doc stripe --json
{
  "results": [
    {
      "doc": "stripe",
      "path": "authentication",
      "title": "Authentication",
      "score": 18.0,
      "use_cases": ["Configure API authentication"],
      "tags": ["security"]
    }
  ]
}
```
