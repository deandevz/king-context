"""Scraper package for King Context."""

from __future__ import annotations

from importlib import import_module


__all__ = [
    "ScraperConfig",
    "load_config",
    "ConfigError",
    "discover_urls",
    "DiscoveryResult",
    "filter_urls",
    "FilterResult",
    "fetch_pages",
    "FetchResult",
    "PageResult",
    "chunk_page",
    "chunk_pages",
    "Chunk",
    "enrich_chunks",
    "EnrichedChunk",
    "validate_enrichment",
    "estimate_cost",
    "export_to_json",
    "save_and_index",
]


_ATTR_TO_MODULE = {
    "ScraperConfig": "king_context.scraper.config",
    "load_config": "king_context.scraper.config",
    "ConfigError": "king_context.scraper.config",
    "discover_urls": "king_context.scraper.discover",
    "DiscoveryResult": "king_context.scraper.discover",
    "filter_urls": "king_context.scraper.filter",
    "FilterResult": "king_context.scraper.filter",
    "fetch_pages": "king_context.scraper.fetch",
    "FetchResult": "king_context.scraper.fetch",
    "PageResult": "king_context.scraper.fetch",
    "chunk_page": "king_context.scraper.chunk",
    "chunk_pages": "king_context.scraper.chunk",
    "Chunk": "king_context.scraper.chunk",
    "enrich_chunks": "king_context.scraper.enrich",
    "EnrichedChunk": "king_context.scraper.enrich",
    "validate_enrichment": "king_context.scraper.enrich",
    "estimate_cost": "king_context.scraper.enrich",
    "export_to_json": "king_context.scraper.export",
    "save_and_index": "king_context.scraper.export",
}


def __getattr__(name: str):
    if name not in _ATTR_TO_MODULE:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(_ATTR_TO_MODULE[name])
    return getattr(module, name)
