"""OpenRouter chat completion provider."""
from __future__ import annotations

from typing import Any

import httpx

from llm_providers.base import LLMClient, ProviderError
from llm_providers.config import ResolvedConfig
from llm_providers.parser import parse_json_object


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
REQUEST_TIMEOUT = 30.0


def _http_error(provider: str, status_code: int, text: str) -> ProviderError:
    if status_code in (401, 403):
        return ProviderError(
            "auth_error",
            transient=False,
            provider=provider,
            message=f"{provider} authentication failed (status {status_code})",
        )
    if status_code == 400:
        return ProviderError(
            "bad_request",
            transient=False,
            provider=provider,
            message=f"{provider} rejected request (status 400): {text[:200]}",
        )
    if status_code == 404:
        return ProviderError(
            "model_not_found",
            transient=False,
            provider=provider,
            message=f"{provider} model or endpoint was not found (status 404)",
        )
    if status_code == 429:
        return ProviderError(
            "rate_limit",
            transient=True,
            provider=provider,
            message=f"{provider} rate limited the request",
        )
    if status_code >= 500:
        return ProviderError(
            "server_error",
            transient=True,
            provider=provider,
            message=f"{provider} server error (status {status_code})",
        )
    return ProviderError(
        "bad_request",
        transient=False,
        provider=provider,
        message=f"{provider} returned status {status_code}: {text[:200]}",
    )


def _content_from_openai_shape(data: dict[str, Any], provider: str) -> str | dict[str, Any]:
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError(
            "invalid_response",
            transient=False,
            provider=provider,
            message=f"Unexpected {provider} response shape: {exc}",
        ) from exc


class OpenRouterClient(LLMClient):
    name = "openrouter"

    def __init__(self, config: ResolvedConfig) -> None:
        self.model = config.model
        self.concurrency = config.concurrency
        self.api_key = config.openrouter_api_key or ""

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = True,
    ) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(
                    OPENROUTER_URL,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "timeout",
                transient=True,
                provider=self.name,
                message=f"{self.name} request timed out",
            ) from exc
        except httpx.ConnectError as exc:
            raise ProviderError(
                "connection_refused",
                transient=True,
                provider=self.name,
                message=f"{self.name} connection failed: {exc}",
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderError(
                "server_error",
                transient=True,
                provider=self.name,
                message=f"{self.name} request failed: {exc}",
            ) from exc

        if response.status_code >= 400:
            raise _http_error(self.name, response.status_code, response.text)

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(
                "invalid_response",
                transient=False,
                provider=self.name,
                message=f"{self.name} returned non-JSON response",
            ) from exc

        content = _content_from_openai_shape(data, self.name)
        try:
            return parse_json_object(content)
        except ProviderError as exc:
            exc.provider = self.name
            raise
