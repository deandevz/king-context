"""URL helpers shared across scraper subcommands.

``canonicalize_url`` normalises a URL down to a form that lets two URLs
pointing at the same resource compare equal: drops the fragment, lowercases
scheme and host, and strips the trailing slash from the path. Used by the
audit command's dedupe + discovery diff and by the update command's
``corpus_urls`` vs ``fresh_urls`` set arithmetic.
"""
from __future__ import annotations

from urllib.parse import urldefrag, urlsplit, urlunsplit


def canonicalize_url(url: str) -> str:
    """Drop fragment, lowercase scheme/host, strip trailing slash from path."""
    url, _ = urldefrag(url)
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, parts.query, "")
    )
