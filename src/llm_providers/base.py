"""Common LLM provider interfaces."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ProviderError(Exception):
    """Provider failure with a stable machine-readable reason."""

    def __init__(
        self,
        reason: str,
        *,
        transient: bool,
        message: str,
        provider: str | None = None,
        primary_error: "ProviderError | None" = None,
        fallback_error: "ProviderError | None" = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.transient = transient
        self.message = message
        self.provider = provider
        self.primary_error = primary_error
        self.fallback_error = fallback_error


class LLMClient(ABC):
    """Single-call JSON completion client."""

    name: str
    model: str
    concurrency: int

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = True,
    ) -> dict[str, Any]:
        """Call the configured model and return a parsed JSON object."""
