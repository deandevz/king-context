
## King Context

Documentation search and scraping tools are available in this project.

### Commands

~~~bash
# Search indexed documentation
.king-context/bin/kctx list                              # list all indexed docs
.king-context/bin/kctx search "query"                    # search by keywords/use_cases
.king-context/bin/kctx search "query" --doc <name>       # search within one doc
.king-context/bin/kctx read <doc> <section> --preview    # preview a section
.king-context/bin/kctx read <doc> <section>              # read full section
.king-context/bin/kctx topics <doc>                      # browse by tags
.king-context/bin/kctx grep "pattern"                    # regex search across docs

# Index documentation
.king-context/bin/kctx index .king-context/data/<file>.json   # index one doc
.king-context/bin/kctx index --all                            # index all docs
.king-context/bin/kctx ingest ./notes --name my-bank          # ingest local Markdown notes

# Scrape new documentation
.king-context/bin/king-scrape <url>                      # full pipeline
.king-context/bin/king-scrape <url> --name <name>        # with custom name
.king-context/bin/king-scrape <url> --yes                # skip confirmation
~~~

### Configuration

- API keys: copy `.king-context/.env.example` to `.env` and fill in your keys
- `FIRECRAWL_API_KEY` (required for scraping)
- `OPENROUTER_API_KEY` (required for scraping enrichment and kctx ingest)

### Directory Structure

- `.king-context/docs/` — indexed documentation (searched by kctx)
- `.king-context/data/` — raw JSON files
- `.king-context/_temp/` — scraper work directories
- `.king-context/_learned/` — agent self-learning shortcuts
