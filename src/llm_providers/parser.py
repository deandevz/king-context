"""Robust JSON object parsing for model responses."""
from __future__ import annotations

import json
import re
from typing import Any

from llm_providers.base import ProviderError


_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.IGNORECASE | re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _invalid(message: str) -> ProviderError:
    return ProviderError(
        "invalid_response",
        transient=False,
        message=message,
    )


def _ensure_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _invalid("LLM response JSON was not an object")
    return value


def _strip_fence(content: str) -> str:
    stripped = content.strip()
    match = _FENCE_RE.match(stripped)
    if match:
        return match.group(1).strip()
    return stripped


def _extract_first_object(content: str) -> str | None:
    start = content.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(content)):
        char = content[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return content[start : index + 1]

    return None


def _loads_object(content: str) -> dict[str, Any]:
    parsed = json.loads(content)
    return _ensure_object(parsed)


def _repair_trailing_commas(content: str) -> str:
    previous = None
    repaired = content
    while previous != repaired:
        previous = repaired
        repaired = _TRAILING_COMMA_RE.sub(r"\1", repaired)
    return repaired


def parse_json_object(content: str | dict[str, Any]) -> dict[str, Any]:
    """Parse a JSON object from model content.

    Accepts clean objects, fenced objects, prose-wrapped objects, and otherwise
    valid JSON with trailing commas. Malformed content fails explicitly.
    """
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        raise _invalid("LLM response content was not a string or object")

    stripped = _strip_fence(content)
    candidates = [stripped]
    extracted = _extract_first_object(stripped)
    if extracted is not None and extracted != stripped:
        candidates.append(extracted)

    for candidate in candidates:
        try:
            return _loads_object(candidate)
        except (json.JSONDecodeError, ProviderError):
            repaired = _repair_trailing_commas(candidate)
            if repaired != candidate:
                try:
                    return _loads_object(repaired)
                except (json.JSONDecodeError, ProviderError):
                    pass

    raise _invalid("LLM response was not parseable JSON")
