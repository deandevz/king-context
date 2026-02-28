"""Shared test fixtures for King Context tests."""

import pytest
import king_context.db as db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Create a temporary database path for testing."""
    temp_db_path = tmp_path / "test_docs.db"
    monkeypatch.setattr(db, "DB_PATH", temp_db_path)
    yield temp_db_path
    if temp_db_path.exists():
        temp_db_path.unlink()
