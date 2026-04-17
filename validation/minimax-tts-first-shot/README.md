# MiniMax TTS — Test Case

> A simple Python script that converts text to MP3 audio using the MiniMax T2A API.
> Implemented by an LLM (Claude) on the first shot using [King Context](https://github.com/deandevz/king-context) as the sole documentation source.

## What is this

A real test case to validate the workflow of an LLM consuming documentation via King Context CLI skill and producing working code on the first attempt.

**Result**: MP3 audio generated successfully on the first run. Zero adjustments.

---

## LLM Workflow

### How the information reached me

I had no prior knowledge of the MiniMax TTS API. Everything I knew came exclusively from King Context, which had the documentation indexed across 66 sections.

```
1. kctx list                          → Discovered "minimax-tts" existed (66 sections)
2. kctx search "text to speech audio" → Found the HTTP endpoint (score 14.50)
3. kctx read ... --preview            → Confirmed it was the right section (~400 tokens)
4. kctx read ... (full)               → Read the complete API reference (1,114 tokens)
5. kctx grep "English_"               → Confirmed the default voice_id
```

From the first `kctx list` to having everything I needed: **5 lookups, ~2,800 tokens of documentation consumed**.

### Documentation token cost

| Step | Tokens |
|------|--------|
| `kctx list` (list available docs) | ~50 |
| 3x `kctx search` (find relevant sections) | ~700 |
| 1x `kctx read --preview` (validate section) | ~400 |
| 1x `kctx read` full (API reference) | ~1,114 |
| 2x `kctx grep` (voice IDs, output format) | ~500 |
| **Total docs consumed** | **~2,800** |

For comparison: the full API reference page in a browser easily exceeds 15,000+ tokens. King Context delivered only what I needed.

### What the main section gave me

A single section (`speech-t2a-http-content`, 1,114 tokens) contained:

- Endpoint URL (`POST /v1/t2a_v2`)
- Authentication format (`Bearer token`)
- Complete curl example with request and response
- All available models (`speech-2.8-hd`, `speech-2.8-turbo`, etc.)
- Structure of `voice_setting`, `audio_setting`
- Response format (`data.audio` as hex-encoded string)
- Supported `language_boost` options
- Limits (10,000 characters per request)

Literally everything needed to implement, in a single read.

### Difficulty level

**Trivial.** The documentation in King Context was well-structured, with keywords and use_cases that made the search hit on the first try. No exploratory browsing needed — the path was direct:

```
search → preview → read → implement → working
```

---

## First Shot

The script worked on the very first execution:

```
$ python minimax_tts.py "Hello! This is a test of the MiniMax text to speech API."

Sending request to MiniMax (speech-2.8-hd)...
Audio generated: 7740ms duration, 122.8KB, 99 characters billed
Audio saved to: output/tts_20260416_104349.mp3
```

No API errors, no wrong fields, no adjustments needed. The documentation indexed in King Context reflected the real, up-to-date API accurately.

---

## How to use

```bash
# Setup
cp .env.example .env         # Edit and add your API key
pip install -r requirements.txt

# Generate audio
python minimax_tts.py "Your text here"

# Or interactive mode
python minimax_tts.py
```

## Structure

```
mini-max-test-case/
├── minimax_tts.py      # Main script (~200 lines, fully commented)
├── .env.example        # Configuration template
├── .gitignore          # Ignores .env and output/
├── requirements.txt    # requests + python-dotenv
├── output/             # Generated MP3 files
└── README.md           # This file
```

---

## Total token usage by stage

End-to-end breakdown of tokens consumed across the entire workflow:

| Stage | Input (read) | Output (written) | Description |
|-------|-------------|-------------------|-------------|
| **1. Doc search** | ~2,800 | ~150 | 5 kctx calls — list, 3x search, grep |
| **2. Doc read** | ~1,514 | — | 1 preview (~400) + 1 full read (~1,114) |
| **3. Code writing** | — | ~3,000 | minimax_tts.py (~2,500), .env.example (~400), .gitignore (~50), requirements.txt (~20) |
| **4. Learn** | — | ~500 | Saved shortcuts to `.king-context/_learned/minimax-tts.md` |
| **Total** | **~4,314** | **~3,650** | **~7,964 tokens total** |

### What this means

- **~4,300 tokens to find and read docs** — out of 66 available sections, I only read 1 full section and previewed 1 other. The cascade search (`kctx search`) pointed me to the right section immediately.
- **~3,000 tokens to write the code** — a fully commented, production-ready script with env config, error handling, and CLI interface.
- **~500 tokens to learn** — saved shortcuts so the next LLM session can skip the search entirely and go straight to `kctx read`.
- **~8K tokens total** vs an estimated **15K+ tokens** just to read the raw API page in a browser. King Context cut the documentation cost by ~70% while delivering a working implementation on the first try.

---

*Test case generated on 2026-04-16 by Claude (Opus) using King Context CLI.*
