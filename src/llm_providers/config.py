"""Environment configuration for LLM providers."""
from __future__ import annotations

import os
from dataclasses import dataclass

from king_context.env import load_project_env
from king_context.errors import ConfigError


DEFAULT_MODEL = "google/gemini-3-flash-preview"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"
VALID_STAGES = {"enrich", "filter", "research"}
VALID_OLLAMA_MODES = {"openai", "native"}
VALID_PROVIDERS = {"openrouter", "ollama"}


@dataclass(frozen=True)
class ResolvedConfig:
    stage: str
    provider: str
    model: str
    concurrency: int
    openrouter_api_key: str | None
    ollama_api_mode: str
    ollama_base_url: str
    ollama_api_key: str | None
    fallback_enabled: bool
    fallback_model: str


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def provider_concurrency(provider: str) -> int:
    """Resolve concurrency for a provider name."""
    provider_key = provider.upper()
    return _env_int(
        f"CONCURRENCY_{provider_key}",
        5 if provider.lower() == "openrouter" else 2,
    )


def _stage_prefix(stage: str) -> str:
    if stage not in VALID_STAGES:
        raise ConfigError(f"Unknown LLM stage: {stage}")
    return stage.upper()


def _stage_model(stage: str, model_override: str | None) -> str:
    if model_override:
        return model_override
    prefix = _stage_prefix(stage)
    model = _env(f"{prefix}_MODEL")
    if model:
        return model
    if stage == "research":
        legacy = _env("OPENROUTER_MODEL_RESEARCH")
        if legacy:
            return legacy
    return DEFAULT_MODEL


def _provider_for(stage: str) -> str:
    prefix = _stage_prefix(stage)
    return _env(f"{prefix}_PROVIDER", "openrouter").lower()


def register_provider_name(name: str) -> None:
    key = name.strip().lower()
    if key:
        VALID_PROVIDERS.add(key)


def resolve(
    stage: str,
    *,
    validate: bool = True,
    model_override: str | None = None,
    openrouter_api_key_override: str | None = None,
) -> ResolvedConfig:
    """Resolve provider configuration for one active stage."""
    load_project_env()
    provider = _provider_for(stage)
    if provider not in VALID_PROVIDERS:
        raise ConfigError(
            f"{_stage_prefix(stage)}_PROVIDER must be one of: "
            f"{', '.join(sorted(VALID_PROVIDERS))}"
        )
    ollama_mode = _env("OLLAMA_API_MODE", "openai").lower()
    openrouter_key = openrouter_api_key_override or _env("OPENROUTER_API_KEY") or None
    config = ResolvedConfig(
        stage=stage,
        provider=provider,
        model=_stage_model(stage, model_override),
        concurrency=provider_concurrency(provider),
        openrouter_api_key=openrouter_key,
        ollama_api_mode=ollama_mode,
        ollama_base_url=_env("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).rstrip("/"),
        ollama_api_key=_env("OLLAMA_API_KEY") or None,
        fallback_enabled=_env_bool("ENABLE_FALLBACK", False),
        fallback_model=_env("FALLBACK_MODEL", DEFAULT_MODEL),
    )

    if validate:
        validate_config(config)
    return config


def validate_config(config: ResolvedConfig) -> None:
    if config.provider == "openrouter" and not config.openrouter_api_key:
        raise ConfigError("OPENROUTER_API_KEY is required for OpenRouter provider")

    if config.provider == "ollama" and config.ollama_api_mode not in VALID_OLLAMA_MODES:
        raise ConfigError("OLLAMA_API_MODE must be one of: openai, native")

    if (
        config.provider == "ollama"
        and config.fallback_enabled
        and not config.openrouter_api_key
    ):
        raise ConfigError(
            "OPENROUTER_API_KEY is required when ENABLE_FALLBACK=true for an Ollama stage"
        )
