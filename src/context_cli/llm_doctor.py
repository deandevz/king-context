"""LLM provider diagnostics for kctx and installer doctor."""
from __future__ import annotations

import json
from typing import Any

import httpx

from llm_providers.config import ResolvedConfig, resolve


def _url(config: ResolvedConfig) -> str:
    if config.ollama_api_mode == "openai":
        return f"{config.ollama_base_url.rstrip('/')}/models"
    return f"{config.ollama_base_url.rstrip('/')}/api/tags"


def _headers(config: ResolvedConfig) -> dict[str, str]:
    if config.ollama_api_key:
        return {"Authorization": f"Bearer {config.ollama_api_key}"}
    return {}


def _model_names(data: dict[str, Any], mode: str) -> list[str]:
    if mode == "openai":
        items = data.get("data", [])
        return sorted(
            str(item["id"])
            for item in items
            if isinstance(item, dict) and item.get("id")
        )

    items = data.get("models", [])
    names: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("model")
        if name:
            names.add(str(name))
    return sorted(names)


def probe_ollama() -> dict[str, Any]:
    configs = [resolve(stage, validate=False) for stage in ("enrich", "filter", "research")]
    ollama_configs = [config for config in configs if config.provider == "ollama"]
    if not ollama_configs:
        return {"ollama": None}

    config = ollama_configs[0]
    configured_models = sorted({item.model for item in ollama_configs})
    base_payload: dict[str, Any] = {
        "mode": config.ollama_api_mode,
        "base_url": config.ollama_base_url,
        "reachable": False,
        "models_present": [],
        "models_missing": configured_models,
        "version": None,
    }

    try:
        response = httpx.get(
            _url(config),
            headers=_headers(config),
            timeout=5.0,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        base_payload["warning"] = str(exc)
        return {"ollama": base_payload}

    available = _model_names(data, config.ollama_api_mode)
    present = [model for model in configured_models if model in available]
    missing = [model for model in configured_models if model not in available]
    version = response.headers.get("ollama-version") or response.headers.get("x-ollama-version")

    base_payload.update(
        {
            "reachable": True,
            "models_present": present,
            "models_missing": missing,
            "version": version,
        }
    )
    return {"ollama": base_payload}


def print_probe(*, as_json: bool) -> None:
    payload = probe_ollama()
    if as_json:
        print(json.dumps(payload, indent=2))
        return

    ollama = payload["ollama"]
    if ollama is None:
        print("Ollama: not configured")
        return

    status = "reachable" if ollama["reachable"] else "unreachable"
    print(f"Ollama: {status} ({ollama['mode']}, {ollama['base_url']})")
    print(
        "Ollama provider support is beta. Report bugs and model-quality "
        "validation results in GitHub issues: "
        "https://github.com/deandevz/king-context/issues"
    )
    if ollama.get("version"):
        print(f"Version: {ollama['version']}")
    if ollama["models_present"]:
        print("Models present: " + ", ".join(ollama["models_present"]))
    if ollama["models_missing"]:
        print("Models missing: " + ", ".join(ollama["models_missing"]))
    if ollama.get("warning"):
        print("Warning: " + ollama["warning"])
