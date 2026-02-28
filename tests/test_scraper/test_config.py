import pytest
from king_context.scraper.config import ScraperConfig, load_config, ConfigError, get_firecrawl_key, get_openrouter_key


def test_load_config_with_env_vars(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")

    config = load_config()

    assert isinstance(config, ScraperConfig)
    assert config.firecrawl_api_key == "fc-test-key"
    assert config.openrouter_api_key == "or-test-key"


def test_get_firecrawl_key_missing(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)

    with pytest.raises(ConfigError):
        get_firecrawl_key()


def test_get_openrouter_key_missing(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(ConfigError):
        get_openrouter_key()


def test_load_config_overrides(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")

    config = load_config(chunk_max_tokens=500)

    assert config.chunk_max_tokens == 500


def test_config_defaults():
    config = ScraperConfig()

    assert config.enrichment_model == "openai/gpt-4o-mini"
    assert config.enrichment_batch_size == 10
    assert config.chunk_max_tokens == 1000
    assert config.chunk_min_tokens == 100
    assert config.concurrency == 5
    assert config.filter_llm_fallback is True
