import pytest

from king_context.scraper.config import ConfigError
from llm_providers.config import DEFAULT_MODEL, resolve


def _clear(monkeypatch):
    for name in [
        "ENRICH_PROVIDER",
        "ENRICH_MODEL",
        "FILTER_PROVIDER",
        "FILTER_MODEL",
        "RESEARCH_PROVIDER",
        "RESEARCH_MODEL",
        "OPENROUTER_MODEL_RESEARCH",
        "OPENROUTER_API_KEY",
        "OLLAMA_API_MODE",
        "OLLAMA_BASE_URL",
        "OLLAMA_API_KEY",
        "ENABLE_FALLBACK",
        "FALLBACK_MODEL",
        "CONCURRENCY_OPENROUTER",
        "CONCURRENCY_OLLAMA",
    ]:
        monkeypatch.delenv(name, raising=False)


def test_default_openrouter_requires_key_when_validating(monkeypatch):
    _clear(monkeypatch)

    with pytest.raises(ConfigError, match="OPENROUTER_API_KEY"):
        resolve("enrich")


def test_default_openrouter_without_validation(monkeypatch):
    _clear(monkeypatch)

    config = resolve("enrich", validate=False)

    assert config.provider == "openrouter"
    assert config.model == DEFAULT_MODEL


def test_resolve_loads_project_env_file(monkeypatch, tmp_path):
    _clear(monkeypatch)
    monkeypatch.delenv("KING_CONTEXT_DISABLE_DOTENV", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "ENRICH_PROVIDER=ollama",
                "ENRICH_MODEL=qwen2.5:7b",
                "CONCURRENCY_OLLAMA=1",
            ]
        )
    )

    config = resolve("enrich")

    assert config.provider == "ollama"
    assert config.model == "qwen2.5:7b"
    assert config.concurrency == 1


def test_stage_model_and_concurrency(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ENRICH_PROVIDER", "ollama")
    monkeypatch.setenv("ENRICH_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("CONCURRENCY_OLLAMA", "3")

    config = resolve("enrich")

    assert config.provider == "ollama"
    assert config.model == "qwen2.5:7b"
    assert config.concurrency == 3


def test_research_legacy_model_alias(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("RESEARCH_PROVIDER", "ollama")
    monkeypatch.setenv("OPENROUTER_MODEL_RESEARCH", "legacy-model")

    config = resolve("research")

    assert config.model == "legacy-model"


def test_invalid_ollama_mode_only_fails_for_ollama(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "key")
    monkeypatch.setenv("OLLAMA_API_MODE", "bad")

    assert resolve("enrich").provider == "openrouter"

    monkeypatch.setenv("ENRICH_PROVIDER", "ollama")
    with pytest.raises(ConfigError, match="OLLAMA_API_MODE"):
        resolve("enrich")


def test_fallback_requires_openrouter_key_for_ollama(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ENRICH_PROVIDER", "ollama")
    monkeypatch.setenv("ENABLE_FALLBACK", "true")

    with pytest.raises(ConfigError, match="OPENROUTER_API_KEY"):
        resolve("enrich")
