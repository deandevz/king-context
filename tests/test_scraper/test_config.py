import pytest
from king_context.scraper.config import (
    ScraperConfig,
    load_config,
    ConfigError,
    get_firecrawl_key,
    get_openrouter_key,
    _load_env_files,
)


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

    assert config.enrichment_model == "google/gemini-3-flash-preview"
    assert config.enrichment_batch_size == 10
    assert config.chunk_max_tokens == 1000
    assert config.chunk_min_tokens == 100
    assert config.concurrency == 5
    assert config.filter_llm_fallback is True


def test_load_env_files_only_root_env(tmp_path, monkeypatch):
    monkeypatch.delenv("KING_TEST_ROOT_ONLY", raising=False)
    monkeypatch.delenv("KING_TEST_INSTALLER_ONLY", raising=False)

    (tmp_path / ".env").write_text("KING_TEST_ROOT_ONLY=root-value\n")

    _load_env_files(project_root=tmp_path)

    import os
    assert os.environ.get("KING_TEST_ROOT_ONLY") == "root-value"


def test_load_env_files_only_installer_env(tmp_path, monkeypatch):
    monkeypatch.delenv("KING_TEST_INSTALLER_VAR", raising=False)

    installer_dir = tmp_path / ".king-context"
    installer_dir.mkdir()
    (installer_dir / ".env").write_text("KING_TEST_INSTALLER_VAR=installer-value\n")

    _load_env_files(project_root=tmp_path)

    import os
    assert os.environ.get("KING_TEST_INSTALLER_VAR") == "installer-value"


def test_load_env_files_root_overrides_installer(tmp_path, monkeypatch):
    monkeypatch.delenv("KING_TEST_SHARED_VAR", raising=False)

    installer_dir = tmp_path / ".king-context"
    installer_dir.mkdir()
    (installer_dir / ".env").write_text("KING_TEST_SHARED_VAR=installer-value\n")
    (tmp_path / ".env").write_text("KING_TEST_SHARED_VAR=root-value\n")

    _load_env_files(project_root=tmp_path)

    import os
    assert os.environ.get("KING_TEST_SHARED_VAR") == "root-value"


def test_load_env_files_neither_exists(tmp_path, monkeypatch):
    monkeypatch.delenv("KING_TEST_NEITHER_VAR", raising=False)

    _load_env_files(project_root=tmp_path)

    import os
    assert os.environ.get("KING_TEST_NEITHER_VAR") is None
