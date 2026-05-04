# Roadmap

## Short term

- Community registry with versioned doc and research packages
- Distribution via `pip install king-context`
- Agent-generated skills built from scraped docs and research corpora
- Better sub-agent reliability during enrichment
- Richer research pipeline: domain filters, source deduplication across topics
- GitHub Actions CI for tests and lint

## Further out

- Per-project version pinning, with notifications when upstream docs change
- Workflow hooks that surface relevant sections during active coding
- Smarter scraping: URL discovery, chunk limits, JavaScript-rendered content
- Cross-corpus search (query multiple indices in one call)
- More validation cases covering varied API styles and agent tasks

## How priorities are set

Priorities follow contributor leverage:

1. **Corpus packages.** A community library of pre-enriched corpora is the project's single biggest lever. Anything that lowers the cost of producing or sharing a corpus jumps the queue.
2. **Pipeline reliability.** Edge cases in scraping and research that produce empty or low-quality corpora block everything else.
3. **Agent ergonomics.** Skills, MCP, CLI ergonomics — the surface agents touch. Improvements here compound across every corpus.
4. **Distribution.** Easy install and update paths grow the user base, which feeds back into corpus and reliability work.

If you have an idea that fits the leverage model but isn't on this list, open an issue or a discussion. The roadmap is not a ceiling.
