"""LLM provider factory exports."""
from __future__ import annotations

from dataclasses import dataclass

from llm_providers.base import LLMClient, ProviderError
from llm_providers.config import ResolvedConfig, resolve
from llm_providers.fallback import FallbackClient
from llm_providers.ollama import OllamaClient
from llm_providers.openrouter import OpenRouterClient
from llm_providers.registry import create_client, register_provider


register_provider("openrouter", OpenRouterClient)
register_provider("ollama", OllamaClient)


@dataclass(frozen=True)
class StageClients:
    primary: LLMClient
    schema_fallback: LLMClient | None = None


def _openrouter_fallback_config(config: ResolvedConfig) -> ResolvedConfig:
    return ResolvedConfig(
        stage=config.stage,
        provider="openrouter",
        model=config.fallback_model,
        concurrency=5,
        openrouter_api_key=config.openrouter_api_key,
        ollama_api_mode=config.ollama_api_mode,
        ollama_base_url=config.ollama_base_url,
        ollama_api_key=config.ollama_api_key,
        fallback_enabled=False,
        fallback_model=config.fallback_model,
    )


def get_stage_clients(
    stage: str,
    *,
    model_override: str | None = None,
    openrouter_api_key_override: str | None = None,
) -> StageClients:
    config = resolve(
        stage,
        model_override=model_override,
        openrouter_api_key_override=openrouter_api_key_override,
    )
    primary = create_client(config)
    schema_fallback = None

    if config.provider == "ollama" and config.fallback_enabled:
        fallback_config = _openrouter_fallback_config(config)
        fallback = OpenRouterClient(fallback_config)
        primary = FallbackClient(primary=primary, fallback=fallback, stage=stage)
        schema_fallback = fallback

    return StageClients(primary=primary, schema_fallback=schema_fallback)


def get_client(
    stage: str,
    *,
    model_override: str | None = None,
    openrouter_api_key_override: str | None = None,
) -> LLMClient:
    return get_stage_clients(
        stage,
        model_override=model_override,
        openrouter_api_key_override=openrouter_api_key_override,
    ).primary


__all__ = [
    "LLMClient",
    "ProviderError",
    "ResolvedConfig",
    "StageClients",
    "get_client",
    "get_stage_clients",
    "register_provider",
    "resolve",
]
