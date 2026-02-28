import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


class ConfigError(Exception):
    pass


@dataclass
class ScraperConfig:
    firecrawl_api_key: str = ""
    openrouter_api_key: str = ""
    enrichment_model: str = "google/gemini-3-flash-preview" ## Cheap and Fast Model for enrichment.
    enrichment_batch_size: int = 10
    chunk_max_tokens: int = 1000
    chunk_min_tokens: int = 100
    concurrency: int = 5
    filter_llm_fallback: bool = True


def get_firecrawl_key() -> str:
    key = os.environ.get("FIRECRAWL_API_KEY", "")
    if not key:
        raise ConfigError("FIRECRAWL_API_KEY is not set")
    return key


def get_openrouter_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise ConfigError("OPENROUTER_API_KEY is not set")
    return key


def load_config(**overrides) -> ScraperConfig:
    firecrawl_api_key = os.environ.get("FIRECRAWL_API_KEY", "")
    openrouter_api_key = os.environ.get("OPENROUTER_API_KEY", "")

    config = ScraperConfig(
        firecrawl_api_key=firecrawl_api_key,
        openrouter_api_key=openrouter_api_key,
    )

    for key, value in overrides.items():
        setattr(config, key, value)

    return config
