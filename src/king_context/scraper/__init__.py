from importlib import import_module

from king_context.scraper.config import ConfigError, ScraperConfig, load_config

__all__ = [
    "ScraperConfig", "load_config", "ConfigError",
    "discover_urls", "DiscoveryResult",
    "filter_urls", "FilterResult",
    "fetch_pages", "FetchResult", "PageResult",
    "chunk_page", "chunk_pages", "Chunk",
    "enrich_chunks", "EnrichedChunk", "validate_enrichment", "estimate_cost",
    "export_to_json", "save_and_index",
]


_EXPORT_MAP = {
    "discover_urls": ("king_context.scraper.discover", "discover_urls"),
    "DiscoveryResult": ("king_context.scraper.discover", "DiscoveryResult"),
    "filter_urls": ("king_context.scraper.filter", "filter_urls"),
    "FilterResult": ("king_context.scraper.filter", "FilterResult"),
    "fetch_pages": ("king_context.scraper.fetch", "fetch_pages"),
    "FetchResult": ("king_context.scraper.fetch", "FetchResult"),
    "PageResult": ("king_context.scraper.fetch", "PageResult"),
    "chunk_page": ("king_context.scraper.chunk", "chunk_page"),
    "chunk_pages": ("king_context.scraper.chunk", "chunk_pages"),
    "Chunk": ("king_context.scraper.chunk", "Chunk"),
    "enrich_chunks": ("king_context.scraper.enrich", "enrich_chunks"),
    "EnrichedChunk": ("king_context.scraper.enrich", "EnrichedChunk"),
    "validate_enrichment": ("king_context.scraper.enrich", "validate_enrichment"),
    "estimate_cost": ("king_context.scraper.enrich", "estimate_cost"),
    "export_to_json": ("king_context.scraper.export", "export_to_json"),
    "save_and_index": ("king_context.scraper.export", "save_and_index"),
}


def __getattr__(name: str):
    if name not in _EXPORT_MAP:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORT_MAP[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
