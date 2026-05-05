import httpx

from context_cli.llm_doctor import probe_ollama


def _clear(monkeypatch):
    for name in [
        "ENRICH_PROVIDER",
        "ENRICH_MODEL",
        "FILTER_PROVIDER",
        "FILTER_MODEL",
        "RESEARCH_PROVIDER",
        "RESEARCH_MODEL",
        "OPENROUTER_MODEL_RESEARCH",
        "OPENROUTER_API_KEY",
        "OLLAMA_API_MODE",
        "OLLAMA_BASE_URL",
        "OLLAMA_API_KEY",
        "ENABLE_FALLBACK",
    ]:
        monkeypatch.delenv(name, raising=False)


def _patch_get(monkeypatch, handler):
    monkeypatch.setattr(httpx, "get", handler)


def test_llm_doctor_returns_null_when_no_ollama(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")

    assert probe_ollama() == {"ollama": None}


def test_llm_doctor_openai_probe(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ENRICH_PROVIDER", "ollama")
    monkeypatch.setenv("ENRICH_MODEL", "embeddinggemma")
    monkeypatch.setenv("OLLAMA_API_MODE", "openai")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")

    captured = {}

    def handler(url, **kwargs):
        captured["url"] = url
        return httpx.Response(
            200,
            json={"data": [{"id": "embeddinggemma"}]},
            request=httpx.Request("GET", url),
        )

    _patch_get(monkeypatch, handler)

    result = probe_ollama()["ollama"]

    assert captured["url"] == "http://localhost:11434/v1/models"
    assert result["reachable"] is True
    assert result["models_present"] == ["embeddinggemma"]
    assert result["models_missing"] == []


def test_llm_doctor_loads_project_env(monkeypatch, tmp_path):
    _clear(monkeypatch)
    monkeypatch.delenv("KING_CONTEXT_DISABLE_DOTENV", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "ENRICH_PROVIDER=ollama",
                "ENRICH_MODEL=qwen2.5:7b",
                "OLLAMA_API_MODE=openai",
                "OLLAMA_BASE_URL=http://localhost:11434/v1",
            ]
        )
    )

    def handler(url, **kwargs):
        return httpx.Response(
            200,
            json={"data": [{"id": "qwen2.5:7b"}]},
            request=httpx.Request("GET", url),
        )

    _patch_get(monkeypatch, handler)

    result = probe_ollama()["ollama"]

    assert result["reachable"] is True
    assert result["models_present"] == ["qwen2.5:7b"]


def test_llm_doctor_native_probe_missing_model(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("RESEARCH_PROVIDER", "ollama")
    monkeypatch.setenv("RESEARCH_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("OLLAMA_API_MODE", "native")
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://ollama.com")

    def handler(url, **kwargs):
        return httpx.Response(
            200,
            json={"models": [{"name": "other"}]},
            request=httpx.Request("GET", url),
        )

    _patch_get(monkeypatch, handler)

    result = probe_ollama()["ollama"]

    assert result["mode"] == "native"
    assert result["models_missing"] == ["qwen2.5:7b"]
