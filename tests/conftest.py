"""Shared test fixtures for King Context tests."""

import pytest
import king_context.db as db
from king_context.scraper import enrich_cache
from types import SimpleNamespace


@pytest.fixture(autouse=True)
def _isolate_enrich_cache(tmp_path, monkeypatch):
    """Redirect the enrichment cache to a fresh tmp dir per test.

    Tests routinely reuse identical chunk content; without isolation, the
    persistent on-disk cache short-circuits the LLM call paths the tests
    are exercising.
    """
    monkeypatch.setattr(enrich_cache, "DEFAULT_CACHE_DIR", tmp_path / "_enrich_cache")


class FakeLLMClient:
    name = "openrouter"
    model = "test-model"
    concurrency = 100

    def __init__(
        self,
        responses=None,
        *,
        name: str = "openrouter",
        model: str = "test-model",
        concurrency: int = 100,
        side_effect=None,
    ):
        self.name = name
        self.model = model
        self.concurrency = concurrency
        self.responses = list(responses or [])
        self.side_effect = side_effect
        self.calls = []

    async def complete(self, prompt, *, system=None, json_mode=True):
        self.calls.append(
            {"prompt": prompt, "system": system, "json_mode": json_mode}
        )
        if self.side_effect is not None:
            result = self.side_effect(prompt, system=system, json_mode=json_mode)
            if hasattr(result, "__await__"):
                return await result
            return result
        if not self.responses:
            raise AssertionError("FakeLLMClient has no response left")
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def fake_stage_clients(primary, schema_fallback=None):
    return SimpleNamespace(primary=primary, schema_fallback=schema_fallback)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Create a temporary database path for testing.

    Also redirects the embedding sidecar files (``embeddings.npy``,
    ``section_mapping.json``) and resets the in-process embedding state so a
    test that triggers ``_generate_and_save_embedding`` cannot write to the
    real repo's ``data/`` directory.
    """
    temp_db_path = tmp_path / "test_docs.db"
    monkeypatch.setattr(db, "DB_PATH", temp_db_path)
    monkeypatch.setattr(db, "EMBEDDINGS_PATH", tmp_path / "embeddings.npy")
    monkeypatch.setattr(
        db, "SECTION_MAPPING_PATH", tmp_path / "section_mapping.json"
    )
    monkeypatch.setattr(db, "_embeddings", None)
    monkeypatch.setattr(db, "_section_id_to_idx", {})
    yield temp_db_path
    if temp_db_path.exists():
        temp_db_path.unlink()


@pytest.fixture(autouse=True)
def disable_project_dotenv(monkeypatch):
    """Keep developer .env files from influencing tests by default."""
    monkeypatch.setenv("KING_CONTEXT_DISABLE_DOTENV", "1")
