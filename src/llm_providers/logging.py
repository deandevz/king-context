"""Small provider logging helpers."""
from __future__ import annotations

from llm_providers.base import LLMClient


def log_fallback(
    *,
    stage: str,
    primary: LLMClient,
    fallback: LLMClient,
    reason: str,
) -> None:
    print(
        f"[fallback] {stage}: {primary.name} ({primary.model}) -> "
        f"{fallback.name} ({fallback.model}) -- reason: {reason}"
    )
