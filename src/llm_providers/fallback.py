"""One-way Ollama to OpenRouter fallback wrapper."""
from __future__ import annotations

from typing import Any

from king_context.errors import ConfigError

from llm_providers.base import LLMClient, ProviderError
from llm_providers.logging import log_fallback


FALLBACK_REASONS = {
    "connection_refused",
    "model_not_found",
    "invalid_response",
    "rate_limit",
    "server_error",
    "timeout",
}


class FallbackClient(LLMClient):
    """Wrap an Ollama primary with a single OpenRouter fallback call."""

    def __init__(
        self,
        *,
        primary: LLMClient,
        fallback: LLMClient,
        stage: str,
    ) -> None:
        if primary.name != "ollama" or fallback.name != "openrouter":
            raise ConfigError("FallbackClient only supports ollama -> openrouter")
        self.primary = primary
        self.fallback = fallback
        self.stage = stage
        self.name = primary.name
        self.model = primary.model
        self.concurrency = primary.concurrency

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = True,
    ) -> dict[str, Any]:
        try:
            return await self.primary.complete(
                prompt,
                system=system,
                json_mode=json_mode,
            )
        except ProviderError as primary_error:
            reason = primary_error.reason
            if reason not in FALLBACK_REASONS:
                raise
            log_fallback(
                stage=self.stage,
                primary=self.primary,
                fallback=self.fallback,
                reason=reason,
            )
            try:
                return await self.fallback.complete(
                    prompt,
                    system=system,
                    json_mode=json_mode,
                )
            except ProviderError as fallback_error:
                raise ProviderError(
                    reason,
                    transient=fallback_error.transient,
                    provider=self.name,
                    message=(
                        f"Primary {self.primary.name} failed with {primary_error.reason}; "
                        f"fallback {self.fallback.name} failed with {fallback_error.reason}"
                    ),
                    primary_error=primary_error,
                    fallback_error=fallback_error,
                ) from fallback_error
