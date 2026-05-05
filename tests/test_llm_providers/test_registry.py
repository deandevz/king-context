import pytest

from king_context.scraper.config import ConfigError
from llm_providers.base import LLMClient
from llm_providers.config import resolve
from llm_providers.registry import create_client, get_provider_class, register_provider


class StubClient(LLMClient):
    name = "stub"
    model = "stub-model"
    concurrency = 1

    def __init__(self, config):
        self.config = config

    async def complete(self, prompt, *, system=None, json_mode=True):
        return {"ok": True}


def test_register_and_create_stub_provider(monkeypatch):
    register_provider("stub", StubClient)
    monkeypatch.setenv("ENRICH_PROVIDER", "stub")

    config = resolve("enrich", validate=False)
    client = create_client(config)

    assert isinstance(client, StubClient)


def test_unknown_provider_class_raises():
    with pytest.raises(ConfigError):
        get_provider_class("missing")
