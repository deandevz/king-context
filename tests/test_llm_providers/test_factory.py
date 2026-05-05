from llm_providers import get_stage_clients
from llm_providers.fallback import FallbackClient


def test_factory_returns_ollama_with_schema_fallback(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_MODE", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("ENRICH_PROVIDER", "ollama")
    monkeypatch.setenv("ENRICH_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("ENABLE_FALLBACK", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")

    clients = get_stage_clients("enrich")

    assert isinstance(clients.primary, FallbackClient)
    assert clients.primary.name == "ollama"
    assert clients.schema_fallback is not None
    assert clients.schema_fallback.name == "openrouter"
