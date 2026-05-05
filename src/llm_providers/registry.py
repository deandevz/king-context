"""Provider registry."""
from __future__ import annotations

from king_context.errors import ConfigError

from llm_providers.base import LLMClient
from llm_providers.config import ResolvedConfig, register_provider_name


ProviderClass = type[LLMClient]
_PROVIDERS: dict[str, ProviderClass] = {}


def register_provider(name: str, provider_cls: ProviderClass) -> None:
    key = name.strip().lower()
    if not key:
        raise ConfigError("Provider name cannot be empty")
    _PROVIDERS[key] = provider_cls
    register_provider_name(key)


def get_provider_class(name: str) -> ProviderClass:
    key = name.strip().lower()
    try:
        return _PROVIDERS[key]
    except KeyError as exc:
        raise ConfigError(f"Unknown LLM provider: {name}") from exc


def create_client(config: ResolvedConfig) -> LLMClient:
    provider_cls = get_provider_class(config.provider)
    return provider_cls(config)  # type: ignore[call-arg]
