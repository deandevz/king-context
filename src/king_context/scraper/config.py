import os
from dataclasses import dataclass

from king_context.env import load_project_env
from king_context.errors import ConfigError

DEFAULT_ENRICHMENT_MODEL = "google/gemini-3-flash-preview"


@dataclass
class ScraperConfig:
    firecrawl_api_key: str = ""
    openrouter_api_key: str = ""
    enrichment_model: str = DEFAULT_ENRICHMENT_MODEL
    enrichment_batch_size: int = 10
    chunk_max_tokens: int = 1000
    chunk_min_tokens: int = 100
    concurrency: int = 5
    filter_llm_fallback: bool = True


def get_firecrawl_key() -> str:
    load_project_env()
    key = os.environ.get("FIRECRAWL_API_KEY", "")
    if not key:
        raise ConfigError("FIRECRAWL_API_KEY is not set")
    return key


def get_openrouter_key() -> str:
    load_project_env()
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise ConfigError("OPENROUTER_API_KEY is not set")
    return key


def load_config(**overrides) -> ScraperConfig:
    load_project_env()
    firecrawl_api_key = os.environ.get("FIRECRAWL_API_KEY", "")
    openrouter_api_key = os.environ.get("OPENROUTER_API_KEY", "")
    enrichment_model = os.environ.get("ENRICH_MODEL", "").strip() or DEFAULT_ENRICHMENT_MODEL

    config = ScraperConfig(
        firecrawl_api_key=firecrawl_api_key,
        openrouter_api_key=openrouter_api_key,
        enrichment_model=enrichment_model,
    )

    for key, value in overrides.items():
        if value is not None:
            setattr(config, key, value)

    return config
