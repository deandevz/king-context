"""Tests for the shared URL canonicalisation helper."""
from king_context.scraper.url_utils import canonicalize_url


def test_canonicalize_strips_fragment():
    assert canonicalize_url("https://x/A?q=1#frag") == "https://x/A?q=1"


def test_canonicalize_strips_trailing_slash():
    assert canonicalize_url("https://x/a/") == "https://x/a"


def test_canonicalize_keeps_root_slash():
    assert canonicalize_url("https://x.com/") == "https://x.com/"


def test_canonicalize_lowercases_scheme_and_host():
    assert canonicalize_url("HTTPS://X.COM/A") == "https://x.com/A"


def test_canonicalize_keeps_path_case():
    """Path case is preserved — only scheme/host are normalised."""
    assert canonicalize_url("https://x.com/CaseSensitive") == "https://x.com/CaseSensitive"


def test_canonicalize_preserves_query_string():
    assert canonicalize_url("https://x/a?b=1&c=2") == "https://x/a?b=1&c=2"


def test_canonicalize_idempotent():
    once = canonicalize_url("HTTPS://X.com/a/?q=1#frag")
    twice = canonicalize_url(once)
    assert once == twice
