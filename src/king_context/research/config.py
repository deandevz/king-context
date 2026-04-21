import os
from dataclasses import dataclass
from enum import Enum

from king_context.scraper.config import ConfigError, ScraperConfig, load_config


@dataclass
class ResearchConfig:
    scraper: ScraperConfig
    exa_api_key: str = ""
    jina_api_key: str = ""
    research_model: str = ""
    basic_queries: int = 3
    medium_queries: int = 5
    medium_iterations: int = 1
    medium_followups: int = 3
    high_queries: int = 8
    high_iterations: int = 2
    high_followups: int = 5
    extrahigh_queries: int = 12
    extrahigh_iterations: int = 3
    extrahigh_followups: int = 8
    exa_results_per_query: int = 10
    exa_max_chars: int = 15000
    relevance_threshold: float = 0.5


class EffortLevel(str, Enum):
    BASIC = "basic"
    MEDIUM = "medium"
    HIGH = "high"
    EXTRAHIGH = "extrahigh"


@dataclass(frozen=True)
class EffortProfile:
    initial_queries: int
    iterations: int
    followups_per_iteration: int


def effort_profile(level: EffortLevel, config: ResearchConfig) -> EffortProfile:
    if level == EffortLevel.BASIC:
        return EffortProfile(
            initial_queries=config.basic_queries,
            iterations=0,
            followups_per_iteration=0,
        )
    if level == EffortLevel.MEDIUM:
        return EffortProfile(
            initial_queries=config.medium_queries,
            iterations=config.medium_iterations,
            followups_per_iteration=config.medium_followups,
        )
    if level == EffortLevel.HIGH:
        return EffortProfile(
            initial_queries=config.high_queries,
            iterations=config.high_iterations,
            followups_per_iteration=config.high_followups,
        )
    return EffortProfile(
        initial_queries=config.extrahigh_queries,
        iterations=config.extrahigh_iterations,
        followups_per_iteration=config.extrahigh_followups,
    )


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def load_research_config(**overrides) -> ResearchConfig:
    scraper_cfg = load_config()

    exa_api_key = os.environ.get("EXA_API_KEY", "").strip()
    if not exa_api_key:
        raise ConfigError("EXA_API_KEY is not set")

    jina_api_key = os.environ.get("JINA_API_KEY", "").strip()
    research_model = os.environ.get("OPENROUTER_MODEL_RESEARCH", "").strip()

    config = ResearchConfig(
        scraper=scraper_cfg,
        exa_api_key=exa_api_key,
        jina_api_key=jina_api_key,
        research_model=research_model,
        basic_queries=_env_int("RESEARCH_BASIC_QUERIES", 3),
        medium_queries=_env_int("RESEARCH_MEDIUM_QUERIES", 5),
        medium_iterations=_env_int("RESEARCH_MEDIUM_ITERATIONS", 1),
        medium_followups=_env_int("RESEARCH_MEDIUM_FOLLOWUPS", 3),
        high_queries=_env_int("RESEARCH_HIGH_QUERIES", 8),
        high_iterations=_env_int("RESEARCH_HIGH_ITERATIONS", 2),
        high_followups=_env_int("RESEARCH_HIGH_FOLLOWUPS", 5),
        extrahigh_queries=_env_int("RESEARCH_EXTRAHIGH_QUERIES", 12),
        extrahigh_iterations=_env_int("RESEARCH_EXTRAHIGH_ITERATIONS", 3),
        extrahigh_followups=_env_int("RESEARCH_EXTRAHIGH_FOLLOWUPS", 8),
        exa_results_per_query=_env_int("EXA_RESULTS_PER_QUERY", 10),
        exa_max_chars=_env_int("EXA_MAX_CHARS", 15000),
    )

    for key, value in overrides.items():
        setattr(config, key, value)

    return config
