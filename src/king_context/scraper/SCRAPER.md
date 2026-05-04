# King Context Scraper

A 6-stage pipeline that turns any documentation website into a structured,
searchable JSON ready for King Context.

## Requirements

Two API keys, set as environment variables or in a `.env` file at the project
root:

| Variable | Service | Used for |
|---|---|---|
| `FIRECRAWL_API_KEY` | [Firecrawl](https://firecrawl.dev) | URL discovery and page fetching |
| `OPENROUTER_API_KEY` | [OpenRouter](https://openrouter.ai) | Metadata enrichment and URL filtering fallback |

Install the project in editable mode to get the `king-scrape` CLI:

```bash
pip install -e .
```

## Quick Start

```bash
king-scrape https://docs.stripe.com
```

This runs the full pipeline: discovers all URLs on the site, filters for
documentation pages, fetches them as Markdown, splits them into chunks,
enriches each chunk with metadata via LLM, and exports a JSON file to
`.king-context/data/stripe.json`.

The doc name is inferred from the URL (`docs.stripe.com` -> `stripe`).
Override it with `--name` and `--display-name`.

To check whether a previously scraped documentation set has changed without
re-running fetch, chunking, or enrichment, use:

```bash
king-scrape https://docs.stripe.com --check-updates
```

## How the Pipeline Works

The scraper runs 6 sequential stages. Each stage saves its output to a working
directory at `.king-context/_temp/{domain}/`, enabling resumption if anything
fails.

### 1. Discover

Uses Firecrawl's `map()` to crawl the site and collect all reachable URLs.
Output: `discovered_urls.json`.

### 2. Filter

Classifies URLs into **accepted**, **rejected**, or **maybe** using regex
heuristics:

- Paths like `/docs/`, `/api/`, `/guides/`, `/reference/` are accepted
- Paths like `/blog/`, `/pricing/`, `/careers/`, `/login/` are rejected
- Everything else is marked `maybe`

If too few URLs pass (`< 10 accepted` or `> 60% rejected`), an LLM fallback
reclassifies the uncertain ones. Disable with `--no-llm-filter`.

### 3. Fetch

Downloads each accepted URL as Markdown using Firecrawl's `scrape()`. Runs
concurrently (default: 5 parallel requests). Failed pages are logged but do
not stop the pipeline.

### 4. Chunk

Splits each Markdown page at `##` and `###` headers into token-bounded chunks.
Oversized chunks are split further by paragraph. Tiny chunks are merged with
their predecessor. Tables are never split mid-row.

### 5. Enrich

Sends each chunk to an LLM (via OpenRouter) to generate structured metadata:

- **keywords**: specific technical terms (API names, config keys, methods)
- **use_cases**: practical scenarios starting with action verbs
- **tags**: broad category labels
- **priority**: 1-10 importance score

Processed in batches with checkpoints saved after each batch. Before starting,
the CLI shows an estimated cost and asks for confirmation.

### 6. Export

Assembles all enriched chunks into a single JSON file matching King Context's
documentation schema and saves it to `.king-context/data/{name}.json`.

## CLI Reference

```text
king-scrape <URL> [options]
```

| Option | Default | Description |
|---|---|---|
| `--name` | inferred from URL | Unique doc identifier |
| `--display-name` | titlecased name | Human-readable name |
| `--step STAGE` | run all | Start from a specific stage (loads earlier data from checkpoints) |
| `--check-updates` | off | Discover current URLs and compare them against the saved page manifest |
| `--model` | `google/gemini-3-flash-preview` | OpenRouter model for enrichment |
| `--chunk-max-tokens` | 800 | Max tokens per chunk |
| `--chunk-min-tokens` | 50 | Min tokens before merging with previous chunk |
| `--concurrency` | 5 | Parallel fetch requests |
| `--no-llm-filter` | off | Disable LLM fallback in URL filtering |
| `--no-auto-seed` | off | Skip database indexing after export |
| `--include-maybe` | off | Also fetch URLs classified as `maybe` |
| `--stop-after STAGE` | none | Run up to and including one stage, then stop |
| `--yes`, `-y` | off | Skip enrichment confirmation prompts |

## Resuming a Failed Run

The pipeline tracks progress in a `manifest.json` file inside the working
directory. If a run is interrupted:

- Re-run the same command: completed stages are skipped automatically.
- Jump to a specific stage: use `--step` to restart from that point. Earlier
  stages are loaded from their saved checkpoints.

```bash
# Re-run from enrichment after tweaking the model
king-scrape https://docs.stripe.com --step enrich --model openai/gpt-4o-mini
```

## Detecting Changes Without Re-Scraping

The scraper now stores a page-level sync baseline alongside the normal
pipeline progress manifest.

When a page is fetched, King Context records metadata such as:

- URL
- slug
- fetch timestamp
- markdown hash
- `etag`
- `last_modified`
- fallback body hash when cache headers are not enough

Later, `king-scrape --check-updates` can:

- rediscover the current URL set
- detect new pages
- detect removed pages
- detect changed pages with `etag`, `last_modified`, or fallback body hashes
- write a `sync_report.json` summary without re-enriching content

This is the phase-1 foundation for future incremental update flows.

## Working Directory

Each scrape creates a working directory at `.king-context/_temp/{domain}/`
containing:

```text
.king-context/_temp/docs-stripe-com/
|-- manifest.json           # Pipeline progress tracker
|-- page_manifest.json      # Per-page sync metadata baseline
|-- sync_report.json        # Latest change-detection report
|-- discovered_urls.json    # All found URLs
|-- filtered_urls.json      # Classification results
|-- pages/                  # Fetched Markdown files
|-- chunks/                 # Per-page chunk JSONs
`-- enriched/               # Batch checkpoint files
```

This directory persists after the run completes, so you can inspect
intermediate results or re-run later stages with different settings.

## Output Format

The final JSON file follows King Context's documentation schema:

```json
{
  "name": "stripe",
  "display_name": "Stripe",
  "version": "v1",
  "base_url": "https://docs.stripe.com",
  "sections": [
    {
      "title": "Authentication",
      "path": "/docs/api/authentication",
      "url": "https://docs.stripe.com/docs/api/authentication",
      "keywords": ["api-key", "bearer-token", "secret-key"],
      "use_cases": ["Configure API authentication", "Rotate API keys"],
      "tags": ["authentication", "api-reference"],
      "priority": 9,
      "content": "Markdown content..."
    }
  ]
}
```

This is the same format used by `.king-context/data/*.json` files. Once
indexed, sections are searchable through `kctx` CLI commands.
