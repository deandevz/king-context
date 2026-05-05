"""Ollama provider supporting OpenAI-compatible and native APIs."""
from __future__ import annotations

from typing import Any

import httpx

from llm_providers.base import LLMClient, ProviderError
from llm_providers.config import ResolvedConfig
from llm_providers.openrouter import _content_from_openai_shape, _http_error
from llm_providers.parser import parse_json_object


REQUEST_TIMEOUT = 60.0


def _join(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


class OllamaClient(LLMClient):
    name = "ollama"

    def __init__(self, config: ResolvedConfig) -> None:
        self.model = config.model
        self.concurrency = config.concurrency
        self.mode = config.ollama_api_mode
        self.base_url = config.ollama_base_url
        self.api_key = config.ollama_api_key

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _payload(
        self,
        prompt: str,
        *,
        system: str | None,
        json_mode: bool,
    ) -> tuple[str, dict[str, Any]]:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        if self.mode == "openai":
            payload: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            return _join(self.base_url, "chat/completions"), payload

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if json_mode:
            payload["format"] = "json"
        return _join(self.base_url, "api/chat"), payload

    def _content(self, data: dict[str, Any]) -> str | dict[str, Any]:
        if self.mode == "openai":
            return _content_from_openai_shape(data, self.name)
        try:
            return data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise ProviderError(
                "invalid_response",
                transient=False,
                provider=self.name,
                message=f"Unexpected {self.name} native response shape: {exc}",
            ) from exc

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = True,
    ) -> dict[str, Any]:
        url, payload = self._payload(prompt, system=system, json_mode=json_mode)

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(
                    url,
                    headers=self._headers(),
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

        content = self._content(data)
        try:
            return parse_json_object(content)
        except ProviderError as exc:
            exc.provider = self.name
            raise
