"""Shared CLI helper for the ``--no-fetch-cache`` flag.

Each scrape entry point (``king-scrape``, ``king-scrape audit``,
``king-scrape update``) declares ``--no-fetch-cache`` on its own argparser
and threads the resulting boolean into the runtime by setting
``SCRAPE_CACHE_MODE=bypass`` in the process environment. ``setdefault``
semantics mirror ``--provider``: an explicit pre-existing env value wins,
so a contributor who set ``SCRAPE_CACHE_MODE=read_only`` and ALSO passes
``--no-fetch-cache`` keeps the explicit value instead of being silently
downgraded.

The helpers below keep that pattern in one place so the three entry points
behave identically and the env mutation is always restored on exit
(``finally`` block) — important because tests call ``*_main()`` directly
and embedding applications may reuse the same Python process.
"""
from __future__ import annotations

import os
from typing import Optional, Tuple


_ENV_KEY = "SCRAPE_CACHE_MODE"


def apply_cache_mode_flag(args) -> Tuple[bool, Optional[str]]:
    """Apply ``--no-fetch-cache`` to the process env. Return prior state.

    Caller should pass the returned tuple to :func:`restore_cache_mode` in
    a ``finally`` block so the env mutation never leaks past the CLI run.
    """
    was_set = _ENV_KEY in os.environ
    prior = os.environ.get(_ENV_KEY)
    if getattr(args, "no_fetch_cache", False):
        os.environ.setdefault(_ENV_KEY, "bypass")
    return was_set, prior


def restore_cache_mode(was_set: bool, prior: Optional[str]) -> None:
    """Undo :func:`apply_cache_mode_flag`. Pops the key if it was unset
    on entry; restores the original value if it was set."""
    if was_set:
        # Was-set guarantees the prior was a real ``str`` (or empty string).
        # Use an explicit check instead of ``assert`` so the invariant still
        # holds under ``python -O`` (which strips assertions).
        if prior is None:
            raise RuntimeError(
                "restore_cache_mode called with was_set=True but prior=None; "
                "the (was_set, prior) tuple must come from apply_cache_mode_flag"
            )
        os.environ[_ENV_KEY] = prior
    else:
        os.environ.pop(_ENV_KEY, None)


def add_cache_mode_argument(parser) -> None:
    """Declare ``--no-fetch-cache`` on a scrape-family argparser."""
    parser.add_argument(
        "--no-fetch-cache",
        dest="no_fetch_cache",
        action="store_true",
        help=(
            "Bypass the scraper provider's local cache for this run. "
            "Sets SCRAPE_CACHE_MODE=bypass (setdefault — an explicit "
            "pre-existing env value wins). Honoured by the crawl4ai "
            "provider; other providers may ignore it."
        ),
    )
