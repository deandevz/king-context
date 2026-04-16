
## King Context

Documentation search and scraping tools are available in this project.

### Commands

~~~bash
# Search indexed documentation
kctx list                              # list all indexed docs
kctx search "query"                    # search by keywords/use_cases
kctx search "query" --doc <name>       # search within one doc
kctx read <doc> <section> --preview    # preview a section
kctx read <doc> <section>              # read full section
kctx topics <doc>                      # browse by tags
kctx grep "pattern"                    # regex search across docs

# Index documentation
kctx index .king-context/data/<file>.json   # index one doc
kctx index --all                            # index all docs

# Scrape new documentation
king-scrape <url>                      # full pipeline
king-scrape <url> --name <name>        # with custom name
king-scrape <url> --yes                # skip confirmation
~~~

### Configuration

- API keys: copy `.king-context/.env.example` to `.env` and fill in your keys
- `FIRECRAWL_API_KEY` (required for scraping)
- `OPENROUTER_API_KEY` (optional, for automated enrichment)

### Directory Structure

- `.king-context/docs/` — indexed documentation (searched by kctx)
- `.king-context/data/` — raw JSON files
- `.king-context/_temp/` — scraper work directories
- `.king-context/_learned/` — agent self-learning shortcuts
