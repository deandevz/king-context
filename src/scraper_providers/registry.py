"""Scraper provider registry and stage-aware resolution."""
from __future__ import annotations

import os
from typing import Callable, Literal

from .base import DiscoveryProvider, FetchProvider

Stage = Literal["discover", "fetch"]

_DISCOVERY_FACTORIES: dict[str, Callable[[], DiscoveryProvider]] = {}
_FETCH_FACTORIES: dict[str, Callable[[], FetchProvider]] = {}


def register_discovery_provider(
    name: str, factory: Callable[[], DiscoveryProvider]
) -> None:
    """Register a factory for a DiscoveryProvider. Built-ins win on conflict."""
    if name not in _DISCOVERY_FACTORIES:
        _DISCOVERY_FACTORIES[name] = factory


def register_fetch_provider(
    name: str, factory: Callable[[], FetchProvider]
) -> None:
    """Register a factory for a FetchProvider. Built-ins win on conflict."""
    if name not in _FETCH_FACTORIES:
        _FETCH_FACTORIES[name] = factory


def get_discovery_provider(name: str) -> DiscoveryProvider:
    if name not in _DISCOVERY_FACTORIES:
        registered = sorted(_DISCOVERY_FACTORIES.keys())
        raise ValueError(
            f"Unknown discovery provider '{name}'. Registered: {registered}"
        )
    return _DISCOVERY_FACTORIES[name]()


def get_fetch_provider(name: str) -> FetchProvider:
    if name not in _FETCH_FACTORIES:
        registered = sorted(_FETCH_FACTORIES.keys())
        raise ValueError(
            f"Unknown fetch provider '{name}'. Registered: {registered}"
        )
    return _FETCH_FACTORIES[name]()


def resolve_provider_name(stage: Stage) -> str:
    """Stage-aware env resolution.

    Precedence:
      SCRAPE_<STAGE>_PROVIDER  (e.g. SCRAPE_DISCOVER_PROVIDER)
        > SCRAPE_PROVIDER
        > 'firecrawl'  (hardcoded default)
    """
    stage_var = f"SCRAPE_{stage.upper()}_PROVIDER"
    return os.getenv(stage_var) or os.getenv("SCRAPE_PROVIDER") or "firecrawl"


def load_entry_point_providers() -> None:
    """Load any third-party providers registered via the
    'king_context.scraper_providers' entry_points group.

    Built-ins (registered eagerly in __init__) take precedence on conflict.
    Failure to load a third-party provider must NOT break the import — log and skip.
    """
    try:
        from importlib.metadata import entry_points
    except ImportError:
        return
    try:
        eps = entry_points(group="king_context.scraper_providers")
    except Exception:
        return
    for ep in eps:
        try:
            register_fn = ep.load()
            register_fn()
        except Exception:
            continue
