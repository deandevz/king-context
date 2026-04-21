import pytest

from king_context.research.config import (
    EffortLevel,
    EffortProfile,
    ResearchConfig,
    effort_profile,
    load_research_config,
)
from king_context.scraper.config import ConfigError


def _set_base_env(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("EXA_API_KEY", "exa-test-key")


def _clear_research_env(monkeypatch):
    for name in [
        "JINA_API_KEY",
        "OPENROUTER_MODEL_RESEARCH",
        "RESEARCH_BASIC_QUERIES",
        "RESEARCH_MEDIUM_QUERIES",
        "RESEARCH_MEDIUM_ITERATIONS",
        "RESEARCH_MEDIUM_FOLLOWUPS",
        "RESEARCH_HIGH_QUERIES",
        "RESEARCH_HIGH_ITERATIONS",
        "RESEARCH_HIGH_FOLLOWUPS",
        "RESEARCH_EXTRAHIGH_QUERIES",
        "RESEARCH_EXTRAHIGH_ITERATIONS",
        "RESEARCH_EXTRAHIGH_FOLLOWUPS",
        "EXA_RESULTS_PER_QUERY",
        "EXA_MAX_CHARS",
    ]:
        monkeypatch.delenv(name, raising=False)


def test_load_defaults(monkeypatch):
    _clear_research_env(monkeypatch)
    _set_base_env(monkeypatch)

    config = load_research_config()

    assert isinstance(config, ResearchConfig)
    assert config.exa_api_key == "exa-test-key"
    assert config.jina_api_key == ""
    assert config.research_model == ""
    assert config.basic_queries == 3
    assert config.medium_queries == 5
    assert config.medium_iterations == 1
    assert config.medium_followups == 3
    assert config.high_queries == 8
    assert config.high_iterations == 2
    assert config.high_followups == 5
    assert config.extrahigh_queries == 12
    assert config.extrahigh_iterations == 3
    assert config.extrahigh_followups == 8
    assert config.exa_results_per_query == 10
    assert config.exa_max_chars == 15000
    assert config.relevance_threshold == 0.5
    assert config.scraper.firecrawl_api_key == "fc-test-key"
    assert config.scraper.openrouter_api_key == "or-test-key"


def test_env_override_applies(monkeypatch):
    _clear_research_env(monkeypatch)
    _set_base_env(monkeypatch)
    monkeypatch.setenv("RESEARCH_HIGH_QUERIES", "20")

    config = load_research_config()

    assert config.high_queries == 20


def test_missing_exa_key_raises(monkeypatch):
    _clear_research_env(monkeypatch)
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.delenv("EXA_API_KEY", raising=False)

    with pytest.raises(ConfigError):
        load_research_config()


def test_missing_jina_key_ok(monkeypatch):
    _clear_research_env(monkeypatch)
    _set_base_env(monkeypatch)
    monkeypatch.delenv("JINA_API_KEY", raising=False)

    config = load_research_config()

    assert config.jina_api_key == ""


def test_effort_profile_medium(monkeypatch):
    _clear_research_env(monkeypatch)
    _set_base_env(monkeypatch)

    config = load_research_config()
    profile = effort_profile(EffortLevel.MEDIUM, config)

    assert isinstance(profile, EffortProfile)
    assert profile.initial_queries == config.medium_queries
    assert profile.iterations == config.medium_iterations
    assert profile.followups_per_iteration == config.medium_followups


def test_effort_profile_basic(monkeypatch):
    _clear_research_env(monkeypatch)
    _set_base_env(monkeypatch)

    config = load_research_config()
    profile = effort_profile(EffortLevel.BASIC, config)

    assert profile.initial_queries == config.basic_queries
    assert profile.iterations == 0
    assert profile.followups_per_iteration == 0
