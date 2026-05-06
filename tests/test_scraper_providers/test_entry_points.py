"""Tests for scraper_providers.registry.load_entry_point_providers."""
from __future__ import annotations

from scraper_providers import registry


class _FakeEntryPoint:
    def __init__(self, register_fn):
        self._register_fn = register_fn
        self.load_calls = 0

    def load(self):
        self.load_calls += 1
        return self._register_fn


class _RaisingLoadEntryPoint:
    def load(self):
        raise RuntimeError("plugin import boom")


class _RaisingRegisterEntryPoint:
    def load(self):
        def _bad():
            raise RuntimeError("register boom")

        return _bad


def test_entry_points_loaded(monkeypatch):
    called = {"n": 0}

    def _register():
        called["n"] += 1

    fake_ep = _FakeEntryPoint(_register)

    def fake_entry_points(group=None):
        assert group == "king_context.scraper_providers"
        return [fake_ep]

    monkeypatch.setattr(
        "importlib.metadata.entry_points", fake_entry_points
    )
    registry.load_entry_point_providers()
    assert fake_ep.load_calls == 1
    assert called["n"] == 1


def test_entry_point_load_failure_silently_skipped(monkeypatch):
    def fake_entry_points(group=None):
        return [_RaisingLoadEntryPoint()]

    monkeypatch.setattr(
        "importlib.metadata.entry_points", fake_entry_points
    )
    # Must not raise.
    registry.load_entry_point_providers()


def test_entry_point_register_failure_silently_skipped(monkeypatch):
    def fake_entry_points(group=None):
        return [_RaisingRegisterEntryPoint()]

    monkeypatch.setattr(
        "importlib.metadata.entry_points", fake_entry_points
    )
    registry.load_entry_point_providers()


def test_entry_points_api_broken_returns_silently(monkeypatch):
    def fake_entry_points(group=None):
        raise RuntimeError("metadata api unavailable")

    monkeypatch.setattr(
        "importlib.metadata.entry_points", fake_entry_points
    )
    registry.load_entry_point_providers()
