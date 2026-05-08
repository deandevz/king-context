"""Content addressed cache for enrichment results.

Stores LLM enrichment output keyed by sha256 of (chunk content + model id + prompt
version). File-per-hash JSON layout (`<cache_dir>/<sha>.json`) so each entry is
independently inspectable, debuggable, and trivially invalidated by deleting one
file or the whole directory.

Atomic writes via ``tempfile.NamedTemporaryFile`` + ``os.replace`` so a crash mid-write
never leaves half-written JSON. Reads return ``None`` on miss, JSON decode error, or
any IO error callers treat every failure as a cache miss and re-enrich.

The cache key intentionally bakes in the model identifier and prompt version so that
a prompt edit or model swap silently invalidates prior entries. Forgetting that is
the most likely correctness footgun in this layer, so it is enforced by signature.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from king_context import PROJECT_ROOT


DEFAULT_CACHE_DIR = PROJECT_ROOT / ".king-context" / "cache" / "enrichment"


def make_key(content: str, model: str, prompt_version: str) -> str:
    """Return the cache key for a ``(content, model, prompt_version)`` triple.

    Each component is hashed to a fixed-length digest before concatenation, then
    the concatenation is hashed. A character delimiter would in principle allow
    collisions when ``content`` contains the delimiter (markdown tables use ``|``);
    fixed-length digests make boundary ambiguity impossible.
    """
    digests = b"".join(
        hashlib.sha256(part.encode("utf-8")).digest()
        for part in (content, model, prompt_version)
    )
    return hashlib.sha256(digests).hexdigest()


def get(key: str, cache_dir: Path | None = None) -> dict[str, Any] | None:
    """Return the cached enrichment dict for ``key``, or ``None`` on any failure."""
    cache_dir = cache_dir if cache_dir is not None else DEFAULT_CACHE_DIR
    path = cache_dir / f"{key}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


def put(key: str, value: dict[str, Any], cache_dir: Path | None = None) -> None:
    """Atomically write ``value`` to the cache under ``key``. Best-effort, never raises."""
    cache_dir = cache_dir if cache_dir is not None else DEFAULT_CACHE_DIR
    tmp_name: str | None = None
    try:
        # Serialize before any IO so a TypeError on a non-JSON value short-circuits
        # before we create a tempfile that could leak.
        payload = json.dumps(value, ensure_ascii=False)
        cache_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=cache_dir, prefix=f".{key}.", suffix=".tmp"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_name, cache_dir / f"{key}.json")
        tmp_name = None
    except (OSError, TypeError, ValueError):
        return
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
