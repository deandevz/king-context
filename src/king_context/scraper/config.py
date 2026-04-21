import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

from king_context import PROJECT_ROOT


def _load_env_files(project_root: Path | None = None) -> None:
    root = project_root if project_root is not None else PROJECT_ROOT
    installer_env = root / ".king-context" / ".env"
    if installer_env.exists():
        load_dotenv(installer_env)
    developer_env = root / ".env"
    if developer_env.exists():
        load_dotenv(developer_env, override=True)


_load_env_files()


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
