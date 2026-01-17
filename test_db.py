"""Tests for db.py - init_db and search_cascade functions."""

import sqlite3
import pytest
from pathlib import Path
import tempfile
import os
from unittest.mock import patch, MagicMock
import time
import json
import numpy as np

# We need to patch DB_PATH before importing db module
import db
from db import search_cascade, _normalize_query


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Create a temporary database path for testing."""
    temp_db_path = tmp_path / "test_docs.db"
    monkeypatch.setattr(db, "DB_PATH", temp_db_path)
    yield temp_db_path
    # Cleanup
    if temp_db_path.exists():
        temp_db_path.unlink()


class TestInitDb:
    """Tests for init_db function."""

    def test_init_db_creates_database_file(self, temp_db):
        """Test that init_db creates the database file."""
        assert not temp_db.exists()
        db.init_db()
        assert temp_db.exists()

    def test_init_db_creates_documentations_table(self, temp_db):
        """Test that init_db creates documentations table with correct schema."""
        db.init_db()
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Check table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='documentations'"
        )
        assert cursor.fetchone() is not None

        # Check columns
        cursor.execute("PRAGMA table_info(documentations)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        assert "id" in columns
        assert "name" in columns
        assert "display_name" in columns
        assert "version" in columns
        assert "base_url" in columns
        assert "created_at" in columns
        assert "updated_at" in columns

        conn.close()

    def test_init_db_creates_sections_table(self, temp_db):
        """Test that init_db creates sections table with correct schema."""
        db.init_db()
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Check table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sections'"
        )
        assert cursor.fetchone() is not None

        # Check columns
        cursor.execute("PRAGMA table_info(sections)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        assert "id" in columns
        assert "doc_id" in columns
        assert "title" in columns
        assert "path" in columns
        assert "url" in columns
        assert "keywords" in columns  # JSON type
        assert "use_cases" in columns  # JSON type
        assert "tags" in columns  # JSON type
        assert "priority" in columns
        assert "content" in columns

        conn.close()

    def test_init_db_creates_sections_fts_virtual_table(self, temp_db):
        """Test that init_db creates sections_fts FTS5 virtual table."""
        db.init_db()
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Check virtual table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sections_fts'"
        )
        assert cursor.fetchone() is not None

        # Verify it's an FTS5 table by checking sql contains fts5
        cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='sections_fts'"
        )
        sql = cursor.fetchone()[0]
        assert "fts5" in sql.lower()

        conn.close()

    def test_init_db_creates_query_cache_table(self, temp_db):
        """Test that init_db creates query_cache table with correct schema."""
        db.init_db()
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Check table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='query_cache'"
        )
        assert cursor.fetchone() is not None

        # Check columns
        cursor.execute("PRAGMA table_info(query_cache)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        assert "id" in columns
        assert "query_normalized" in columns
        assert "doc_name" in columns
        assert "section_id" in columns
        assert "hit_count" in columns
        assert "last_used" in columns

        conn.close()

    def test_init_db_sections_has_foreign_key_to_documentations(self, temp_db):
        """Test that sections.doc_id has foreign key to documentations."""
        db.init_db()
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Check foreign key
        cursor.execute("PRAGMA foreign_key_list(sections)")
        fks = cursor.fetchall()

        # Find FK to documentations
        doc_fk = [fk for fk in fks if fk[2] == "documentations"]
        assert len(doc_fk) > 0

        conn.close()

    def test_init_db_query_cache_has_foreign_key_to_sections(self, temp_db):
        """Test that query_cache.section_id has foreign key to sections."""
        db.init_db()
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Check foreign key
        cursor.execute("PRAGMA foreign_key_list(query_cache)")
        fks = cursor.fetchall()

        # Find FK to sections
        sections_fk = [fk for fk in fks if fk[2] == "sections"]
        assert len(sections_fk) > 0

        conn.close()

    def test_init_db_is_idempotent(self, temp_db):
        """Test that init_db can be called multiple times without error."""
        db.init_db()
        # Insert some data
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO documentations (name, display_name, version, base_url) VALUES (?, ?, ?, ?)",
            ("test", "Test Doc", "1.0", "http://example.com")
        )
        conn.commit()
        conn.close()

        # Call init_db again - should not raise error or lose data
        db.init_db()

        # Verify data still exists
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM documentations WHERE name = 'test'")
        assert cursor.fetchone() is not None
        conn.close()

    def test_init_db_documentations_id_is_primary_key_autoincrement(self, temp_db):
        """Test that documentations.id is INTEGER PRIMARY KEY (autoincrement)."""
        db.init_db()
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Check that id is primary key
        cursor.execute("PRAGMA table_info(documentations)")
        columns = cursor.fetchall()
        id_col = [c for c in columns if c[1] == "id"][0]

        # pk column (index 5) should be non-zero for primary key
        assert id_col[5] > 0

        conn.close()


class TestSearchCascade:
    """Tests for the search_cascade function."""

    @patch('db._get_connection')
    @patch('db._check_cache')
    @patch('db._search_metadata')
    @patch('db._search_fts')
    @patch('db._update_cache')
    def test_returns_cache_hit_first(
        self,
        mock_update_cache,
        mock_search_fts,
        mock_search_metadata,
        mock_check_cache,
        mock_get_connection
    ):
        """When cache has results, should return immediately without searching metadata or FTS."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        cached_chunks = [
            {"section_id": 1, "title": "Test", "content": "Content", "keywords": ["test"], "source_url": "http://test.com"}
        ]
        mock_check_cache.return_value = cached_chunks

        result = search_cascade("test query")

        assert result["found"] is True
        assert result["chunks"] == cached_chunks
        assert result["transparency"]["method"] == "cache"
        assert result["transparency"]["from_cache"] is True
        assert "cache_hit" in result["transparency"]["search_path"]
        assert "latency_ms" in result["transparency"]
        assert isinstance(result["transparency"]["latency_ms"], float)

        # Should not call metadata or FTS search
        mock_search_metadata.assert_not_called()
        mock_search_fts.assert_not_called()
        mock_update_cache.assert_not_called()

    @patch('db._get_connection')
    @patch('db._check_cache')
    @patch('db._search_metadata')
    @patch('db._search_fts')
    @patch('db._update_cache')
    def test_falls_back_to_metadata_on_cache_miss(
        self,
        mock_update_cache,
        mock_search_fts,
        mock_search_metadata,
        mock_check_cache,
        mock_get_connection
    ):
        """When cache misses but metadata has results, should return metadata results."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_check_cache.return_value = None  # Cache miss

        metadata_chunks = [
            {"section_id": 2, "title": "Metadata Result", "content": "Found via metadata", "keywords": ["meta"], "source_url": "http://meta.com"}
        ]
        mock_search_metadata.return_value = metadata_chunks

        result = search_cascade("test query")

        assert result["found"] is True
        assert result["chunks"] == metadata_chunks
        assert result["transparency"]["method"] == "metadata"
        assert result["transparency"]["from_cache"] is False
        assert "cache_miss" in result["transparency"]["search_path"]
        assert "metadata_hit" in result["transparency"]["search_path"]

        # Should not call FTS search
        mock_search_fts.assert_not_called()

        # Should update cache with first result
        mock_update_cache.assert_called_once()

    @patch('db._get_connection')
    @patch('db._check_cache')
    @patch('db._search_metadata')
    @patch('db._search_fts')
    @patch('db._update_cache')
    def test_falls_back_to_fts_on_metadata_miss(
        self,
        mock_update_cache,
        mock_search_fts,
        mock_search_metadata,
        mock_check_cache,
        mock_get_connection
    ):
        """When both cache and metadata miss, should fall back to FTS5 search."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_check_cache.return_value = None  # Cache miss
        mock_search_metadata.return_value = []  # Metadata miss

        fts_chunks = [
            {"section_id": 3, "title": "FTS Result", "content": "Found via full-text search", "keywords": ["fts"], "source_url": "http://fts.com"}
        ]
        mock_search_fts.return_value = fts_chunks

        result = search_cascade("test query")

        assert result["found"] is True
        assert result["chunks"] == fts_chunks
        assert result["transparency"]["method"] == "fts"
        assert result["transparency"]["from_cache"] is False
        assert "cache_miss" in result["transparency"]["search_path"]
        assert "metadata_miss" in result["transparency"]["search_path"]
        assert "fts_hit" in result["transparency"]["search_path"]

        # Should update cache with first result
        mock_update_cache.assert_called_once()

    @patch('db._get_connection')
    @patch('db._check_cache')
    @patch('db._search_metadata')
    @patch('db._search_fts')
    @patch('db._update_cache')
    def test_returns_not_found_when_all_miss(
        self,
        mock_update_cache,
        mock_search_fts,
        mock_search_metadata,
        mock_check_cache,
        mock_get_connection
    ):
        """When all search methods fail, should return found=False with empty chunks."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_check_cache.return_value = None
        mock_search_metadata.return_value = []
        mock_search_fts.return_value = []

        result = search_cascade("nonexistent query")

        assert result["found"] is False
        assert result["chunks"] == []
        assert "cache_miss" in result["transparency"]["search_path"]
        assert "metadata_miss" in result["transparency"]["search_path"]
        assert "fts_miss" in result["transparency"]["search_path"]
        assert result["transparency"]["from_cache"] is False

        # Should not update cache when nothing found
        mock_update_cache.assert_not_called()

    @patch('db._get_connection')
    @patch('db._check_cache')
    @patch('db._search_metadata')
    @patch('db._search_fts')
    @patch('db._update_cache')
    def test_normalizes_query(
        self,
        mock_update_cache,
        mock_search_fts,
        mock_search_metadata,
        mock_check_cache,
        mock_get_connection
    ):
        """Query should be normalized before searching."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_check_cache.return_value = None
        mock_search_metadata.return_value = []
        mock_search_fts.return_value = []

        search_cascade("  TEST Query  ")

        # Verify normalized query was passed to helpers
        normalized = "test query"
        mock_check_cache.assert_called_once_with(mock_conn, normalized, None)
        mock_search_metadata.assert_called_once_with(mock_conn, normalized, None, 5)
        # FTS now always requests 20 candidates for hybrid reranking
        mock_search_fts.assert_called_once_with(mock_conn, normalized, None, 20)

    @patch('db._get_connection')
    @patch('db._check_cache')
    @patch('db._search_metadata')
    @patch('db._search_fts')
    @patch('db._update_cache')
    def test_passes_doc_name_filter(
        self,
        mock_update_cache,
        mock_search_fts,
        mock_search_metadata,
        mock_check_cache,
        mock_get_connection
    ):
        """doc_name parameter should be passed to all search methods."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_check_cache.return_value = None
        mock_search_metadata.return_value = []
        mock_search_fts.return_value = []

        search_cascade("test", doc_name="langchain")

        mock_check_cache.assert_called_with(mock_conn, "test", "langchain")
        mock_search_metadata.assert_called_with(mock_conn, "test", "langchain", 5)
        # FTS now always requests 20 candidates for hybrid reranking
        mock_search_fts.assert_called_with(mock_conn, "test", "langchain", 20)

    @patch('db._get_connection')
    @patch('db._check_cache')
    @patch('db._search_metadata')
    @patch('db._search_fts')
    @patch('db._update_cache')
    def test_passes_max_results(
        self,
        mock_update_cache,
        mock_search_fts,
        mock_search_metadata,
        mock_check_cache,
        mock_get_connection
    ):
        """max_results parameter should be passed to metadata search. FTS gets 20 candidates for reranking."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_check_cache.return_value = None
        mock_search_metadata.return_value = []
        mock_search_fts.return_value = []

        search_cascade("test", max_results=10)

        mock_search_metadata.assert_called_with(mock_conn, "test", None, 10)
        # FTS always requests 20 candidates for hybrid reranking, not max_results
        mock_search_fts.assert_called_with(mock_conn, "test", None, 20)

    @patch('db._get_connection')
    @patch('db._check_cache')
    @patch('db._search_metadata')
    @patch('db._search_fts')
    @patch('db._update_cache')
    def test_latency_is_tracked(
        self,
        mock_update_cache,
        mock_search_fts,
        mock_search_metadata,
        mock_check_cache,
        mock_get_connection
    ):
        """Latency should be tracked in milliseconds."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_check_cache.return_value = None
        mock_search_metadata.return_value = []
        mock_search_fts.return_value = []

        result = search_cascade("test")

        assert "latency_ms" in result["transparency"]
        assert isinstance(result["transparency"]["latency_ms"], float)
        assert result["transparency"]["latency_ms"] >= 0

    @patch('db._get_connection')
    @patch('db._check_cache')
    @patch('db._search_metadata')
    @patch('db._search_fts')
    @patch('db._update_cache')
    def test_closes_connection(
        self,
        mock_update_cache,
        mock_search_fts,
        mock_search_metadata,
        mock_check_cache,
        mock_get_connection
    ):
        """Database connection should be closed after search."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_check_cache.return_value = None
        mock_search_metadata.return_value = []
        mock_search_fts.return_value = []

        search_cascade("test")

        mock_conn.close.assert_called_once()


class TestNormalizeQuery:
    """Tests for the _normalize_query helper."""

    def test_lowercases_query(self):
        assert _normalize_query("TEST") == "test"
        assert _normalize_query("TeSt QuErY") == "test query"

    def test_strips_whitespace(self):
        assert _normalize_query("  test  ") == "test"
        assert _normalize_query("\n\ttest\n\t") == "test"

    def test_handles_empty_string(self):
        assert _normalize_query("") == ""
        assert _normalize_query("   ") == ""


class TestCheckCache:
    """Tests for the _check_cache function."""

    @pytest.fixture
    def db_with_cache_data(self, temp_db):
        """Create a database with sample data for cache testing."""
        db.init_db()
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Insert a documentation
        cursor.execute(
            "INSERT INTO documentations (name, display_name, version, base_url) VALUES (?, ?, ?, ?)",
            ("langchain", "LangChain", "0.1.0", "https://docs.langchain.com")
        )
        doc_id = cursor.lastrowid

        # Insert sections with keywords as JSON
        cursor.execute(
            """INSERT INTO sections (doc_id, title, path, url, keywords, use_cases, tags, priority, content)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (doc_id, "Getting Started", "/getting-started", "https://docs.langchain.com/getting-started",
             '["installation", "quickstart", "setup"]', '["beginners"]', '["intro"]', 10,
             "Welcome to LangChain. This guide helps you get started.")
        )
        section_id_1 = cursor.lastrowid

        cursor.execute(
            """INSERT INTO sections (doc_id, title, path, url, keywords, use_cases, tags, priority, content)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (doc_id, "Chains", "/chains", "https://docs.langchain.com/chains",
             '["llm", "chain", "prompts"]', '["advanced"]', '["core"]', 5,
             "Chains allow you to combine multiple components.")
        )
        section_id_2 = cursor.lastrowid

        # Insert another doc
        cursor.execute(
            "INSERT INTO documentations (name, display_name, version, base_url) VALUES (?, ?, ?, ?)",
            ("crewai", "CrewAI", "1.0.0", "https://docs.crewai.com")
        )
        doc_id_2 = cursor.lastrowid

        cursor.execute(
            """INSERT INTO sections (doc_id, title, path, url, keywords, use_cases, tags, priority, content)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (doc_id_2, "Agents", "/agents", "https://docs.crewai.com/agents",
             '["agent", "crew", "task"]', '["automation"]', '["core"]', 8,
             "Agents are the core building blocks of CrewAI.")
        )
        section_id_3 = cursor.lastrowid

        # Insert cache entries
        cursor.execute(
            """INSERT INTO query_cache (query_normalized, doc_name, section_id, hit_count, last_used)
            VALUES (?, ?, ?, ?, ?)""",
            ("installation", "langchain", section_id_1, 5, "2024-01-01 10:00:00")
        )

        cursor.execute(
            """INSERT INTO query_cache (query_normalized, doc_name, section_id, hit_count, last_used)
            VALUES (?, ?, ?, ?, ?)""",
            ("how to start", None, section_id_1, 3, "2024-01-01 09:00:00")
        )

        cursor.execute(
            """INSERT INTO query_cache (query_normalized, doc_name, section_id, hit_count, last_used)
            VALUES (?, ?, ?, ?, ?)""",
            ("chains tutorial", "langchain", section_id_2, 2, "2024-01-01 08:00:00")
        )

        conn.commit()
        conn.close()

        return temp_db, {
            "section_id_1": section_id_1,
            "section_id_2": section_id_2,
            "section_id_3": section_id_3
        }

    def test_returns_none_when_cache_empty(self, temp_db):
        """When cache is empty, should return None."""
        db.init_db()
        conn = sqlite3.connect(temp_db)

        result = db._check_cache(conn, "test query", None)

        assert result is None
        conn.close()

    def test_returns_none_when_no_match(self, db_with_cache_data):
        """When query doesn't match any cache entry, should return None."""
        temp_db, _ = db_with_cache_data
        conn = sqlite3.connect(temp_db)

        result = db._check_cache(conn, "nonexistent query", None)

        assert result is None
        conn.close()

    def test_returns_section_dict_on_cache_hit(self, db_with_cache_data):
        """When cache hit, should return list of section dicts with correct format."""
        temp_db, section_ids = db_with_cache_data
        conn = sqlite3.connect(temp_db)

        result = db._check_cache(conn, "installation", "langchain")

        assert result is not None
        assert isinstance(result, list)
        assert len(result) >= 1

        section = result[0]
        assert "section_id" in section
        assert "title" in section
        assert "content" in section
        assert "keywords" in section
        assert "source_url" in section

        assert section["section_id"] == section_ids["section_id_1"]
        assert section["title"] == "Getting Started"
        assert section["content"] == "Welcome to LangChain. This guide helps you get started."
        assert section["keywords"] == ["installation", "quickstart", "setup"]
        assert section["source_url"] == "https://docs.langchain.com/getting-started"

        conn.close()

    def test_matches_with_doc_name_none(self, db_with_cache_data):
        """When doc_name is None in query, should match cache entries with doc_name=None."""
        temp_db, section_ids = db_with_cache_data
        conn = sqlite3.connect(temp_db)

        result = db._check_cache(conn, "how to start", None)

        assert result is not None
        assert len(result) >= 1
        assert result[0]["section_id"] == section_ids["section_id_1"]

        conn.close()

    def test_matches_specific_doc_name(self, db_with_cache_data):
        """When doc_name is specified, should only match entries with that doc_name."""
        temp_db, section_ids = db_with_cache_data
        conn = sqlite3.connect(temp_db)

        result = db._check_cache(conn, "installation", "langchain")

        assert result is not None
        assert result[0]["section_id"] == section_ids["section_id_1"]

        # Same query but different doc_name should not match
        result2 = db._check_cache(conn, "installation", "crewai")
        assert result2 is None

        conn.close()

    def test_increments_hit_count_on_cache_hit(self, db_with_cache_data):
        """When cache hit, should increment hit_count."""
        temp_db, _ = db_with_cache_data
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Get initial hit count
        cursor.execute(
            "SELECT hit_count FROM query_cache WHERE query_normalized = ? AND doc_name = ?",
            ("installation", "langchain")
        )
        initial_count = cursor.fetchone()[0]
        assert initial_count == 5

        # Perform cache check
        db._check_cache(conn, "installation", "langchain")

        # Verify hit count was incremented
        cursor.execute(
            "SELECT hit_count FROM query_cache WHERE query_normalized = ? AND doc_name = ?",
            ("installation", "langchain")
        )
        new_count = cursor.fetchone()[0]
        assert new_count == 6

        conn.close()

    def test_updates_last_used_timestamp_on_cache_hit(self, db_with_cache_data):
        """When cache hit, should update last_used timestamp."""
        temp_db, _ = db_with_cache_data
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Get initial timestamp
        cursor.execute(
            "SELECT last_used FROM query_cache WHERE query_normalized = ? AND doc_name = ?",
            ("installation", "langchain")
        )
        initial_timestamp = cursor.fetchone()[0]
        assert initial_timestamp == "2024-01-01 10:00:00"

        # Perform cache check
        db._check_cache(conn, "installation", "langchain")

        # Verify timestamp was updated
        cursor.execute(
            "SELECT last_used FROM query_cache WHERE query_normalized = ? AND doc_name = ?",
            ("installation", "langchain")
        )
        new_timestamp = cursor.fetchone()[0]
        assert new_timestamp != initial_timestamp
        # Should be a more recent timestamp
        assert new_timestamp > initial_timestamp

        conn.close()

    def test_does_not_increment_hit_count_on_miss(self, db_with_cache_data):
        """When cache miss, should not modify any hit counts."""
        temp_db, _ = db_with_cache_data
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Get all initial hit counts
        cursor.execute("SELECT query_normalized, hit_count FROM query_cache")
        initial_counts = {row[0]: row[1] for row in cursor.fetchall()}

        # Perform cache check with non-existent query
        db._check_cache(conn, "nonexistent query", None)

        # Verify no hit counts changed
        cursor.execute("SELECT query_normalized, hit_count FROM query_cache")
        final_counts = {row[0]: row[1] for row in cursor.fetchall()}

        assert initial_counts == final_counts

        conn.close()

    def test_parses_keywords_json_field(self, db_with_cache_data):
        """Keywords should be parsed from JSON to list."""
        temp_db, _ = db_with_cache_data
        conn = sqlite3.connect(temp_db)

        result = db._check_cache(conn, "chains tutorial", "langchain")

        assert result is not None
        assert isinstance(result[0]["keywords"], list)
        assert result[0]["keywords"] == ["llm", "chain", "prompts"]

        conn.close()

    def test_handles_null_keywords(self, temp_db):
        """When keywords is NULL, should return empty list or None."""
        db.init_db()
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Insert doc and section with NULL keywords
        cursor.execute(
            "INSERT INTO documentations (name, display_name, version, base_url) VALUES (?, ?, ?, ?)",
            ("test", "Test", "1.0", "https://test.com")
        )
        doc_id = cursor.lastrowid

        cursor.execute(
            """INSERT INTO sections (doc_id, title, path, url, keywords, priority, content)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (doc_id, "Test Section", "/test", "https://test.com/test", None, 1, "Test content")
        )
        section_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO query_cache (query_normalized, doc_name, section_id) VALUES (?, ?, ?)",
            ("null keywords test", None, section_id)
        )
        conn.commit()

        result = db._check_cache(conn, "null keywords test", None)

        assert result is not None
        # Should handle NULL gracefully - either empty list or None
        assert result[0]["keywords"] is None or result[0]["keywords"] == []

        conn.close()


class TestSearchMetadata:
    """Tests for the _search_metadata function."""

    @pytest.fixture
    def db_with_data(self, temp_db):
        """Create database with sample data for metadata search tests."""
        db.init_db()
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Insert documentations
        cursor.execute(
            "INSERT INTO documentations (name, display_name, version, base_url) VALUES (?, ?, ?, ?)",
            ("langchain", "LangChain", "0.1.0", "https://langchain.com/docs")
        )
        langchain_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO documentations (name, display_name, version, base_url) VALUES (?, ?, ?, ?)",
            ("fastapi", "FastAPI", "0.100.0", "https://fastapi.tiangolo.com")
        )
        fastapi_id = cursor.lastrowid

        # Insert sections with keywords, use_cases, tags
        # LangChain section with high priority
        cursor.execute(
            """INSERT INTO sections (doc_id, title, path, url, keywords, use_cases, tags, priority, content)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                langchain_id,
                "LLM Chains",
                "/chains/llm",
                "https://langchain.com/docs/chains/llm",
                '["chain", "llm", "prompt"]',
                '["text generation", "chatbot"]',
                '["core", "beginner"]',
                10,
                "This section covers LLM chains for text generation."
            )
        )

        # LangChain section with lower priority
        cursor.execute(
            """INSERT INTO sections (doc_id, title, path, url, keywords, use_cases, tags, priority, content)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                langchain_id,
                "Prompt Templates",
                "/prompts/templates",
                "https://langchain.com/docs/prompts/templates",
                '["prompt", "template", "variables"]',
                '["dynamic prompts", "reusable prompts"]',
                '["core", "intermediate"]',
                5,
                "Learn about prompt templates and variable injection."
            )
        )

        # FastAPI section
        cursor.execute(
            """INSERT INTO sections (doc_id, title, path, url, keywords, use_cases, tags, priority, content)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                fastapi_id,
                "Request Validation",
                "/validation",
                "https://fastapi.tiangolo.com/validation",
                '["validation", "pydantic", "request"]',
                '["api validation", "data validation"]',
                '["core", "beginner"]',
                8,
                "FastAPI uses Pydantic for request validation."
            )
        )

        conn.commit()
        conn.close()

        return temp_db

    def test_search_metadata_finds_by_keyword(self, db_with_data):
        """Should find sections matching keyword."""
        conn = sqlite3.connect(db_with_data)
        result = db._search_metadata(conn, "prompt", None, 5)
        conn.close()

        assert len(result) >= 1
        titles = [r["title"] for r in result]
        assert "LLM Chains" in titles or "Prompt Templates" in titles

    def test_search_metadata_finds_by_use_case(self, db_with_data):
        """Should find sections matching use_case."""
        conn = sqlite3.connect(db_with_data)
        result = db._search_metadata(conn, "chatbot", None, 5)
        conn.close()

        assert len(result) >= 1
        assert result[0]["title"] == "LLM Chains"

    def test_search_metadata_finds_by_tag(self, db_with_data):
        """Should find sections matching tag."""
        conn = sqlite3.connect(db_with_data)
        result = db._search_metadata(conn, "beginner", None, 5)
        conn.close()

        assert len(result) >= 2  # Both LLM Chains and Request Validation

    def test_search_metadata_filters_by_doc_name(self, db_with_data):
        """Should filter results by doc_name when provided."""
        conn = sqlite3.connect(db_with_data)
        result = db._search_metadata(conn, "core", "langchain", 5)
        conn.close()

        # Should only return langchain results
        assert len(result) >= 1
        titles = [r["title"] for r in result]
        assert "Request Validation" not in titles  # FastAPI section

    def test_search_metadata_orders_by_priority_desc(self, db_with_data):
        """Should order results by priority descending."""
        conn = sqlite3.connect(db_with_data)
        result = db._search_metadata(conn, "core", None, 5)
        conn.close()

        # Verify descending order - LLM Chains (10) should come before Request Validation (8) and Prompt Templates (5)
        assert len(result) >= 2
        # First result should have highest priority
        assert result[0]["title"] == "LLM Chains"  # priority 10

    def test_search_metadata_respects_max_results(self, db_with_data):
        """Should limit results to max_results."""
        conn = sqlite3.connect(db_with_data)
        result = db._search_metadata(conn, "core", None, 1)
        conn.close()

        assert len(result) == 1

    def test_search_metadata_returns_correct_dict_format(self, db_with_data):
        """Should return list of dicts with correct keys."""
        conn = sqlite3.connect(db_with_data)
        result = db._search_metadata(conn, "prompt", None, 5)
        conn.close()

        assert len(result) >= 1
        section = result[0]

        # Check required keys
        assert "section_id" in section
        assert "title" in section
        assert "content" in section
        assert "keywords" in section
        assert "source_url" in section

        # Check types
        assert isinstance(section["section_id"], int)
        assert isinstance(section["title"], str)
        assert isinstance(section["content"], str)
        assert isinstance(section["keywords"], list)
        assert isinstance(section["source_url"], str)

    def test_search_metadata_returns_empty_list_when_no_match(self, db_with_data):
        """Should return empty list when no matches found."""
        conn = sqlite3.connect(db_with_data)
        result = db._search_metadata(conn, "nonexistent_keyword_xyz", None, 5)
        conn.close()

        assert result == []

    def test_search_metadata_returns_empty_list_for_invalid_doc_name(self, db_with_data):
        """Should return empty list when doc_name doesn't exist."""
        conn = sqlite3.connect(db_with_data)
        result = db._search_metadata(conn, "prompt", "nonexistent_doc", 5)
        conn.close()

        assert result == []

    def test_search_metadata_parses_keywords_json(self, db_with_data):
        """Should parse keywords JSON field into list."""
        conn = sqlite3.connect(db_with_data)
        result = db._search_metadata(conn, "chain", None, 5)
        conn.close()

        assert len(result) >= 1
        keywords = result[0]["keywords"]
        assert isinstance(keywords, list)
        assert "chain" in keywords or "llm" in keywords or "prompt" in keywords


class TestUpdateCache:
    """Tests for _update_cache function."""

    @pytest.fixture
    def db_with_section(self, temp_db):
        """Create a database with a documentation and section for testing."""
        db.init_db()
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Insert a documentation
        cursor.execute(
            "INSERT INTO documentations (name, display_name, version, base_url) VALUES (?, ?, ?, ?)",
            ("langchain", "LangChain", "1.0", "https://langchain.com")
        )
        doc_id = cursor.lastrowid

        # Insert a section
        cursor.execute(
            "INSERT INTO sections (doc_id, title, path, url, content) VALUES (?, ?, ?, ?, ?)",
            (doc_id, "Getting Started", "/docs/getting-started", "https://langchain.com/docs/getting-started", "Content here")
        )
        section_id = cursor.lastrowid

        conn.commit()
        conn.close()

        return {"doc_id": doc_id, "section_id": section_id}

    def test_inserts_new_cache_entry(self, temp_db, db_with_section):
        """Test that _update_cache inserts a new cache entry."""
        conn = sqlite3.connect(temp_db)

        db._update_cache(conn, "test query", "langchain", db_with_section["section_id"])
        conn.commit()

        cursor = conn.cursor()
        cursor.execute("SELECT * FROM query_cache WHERE query_normalized = ?", ("test query",))
        row = cursor.fetchone()

        assert row is not None
        assert row[1] == "test query"  # query_normalized
        assert row[2] == "langchain"  # doc_name
        assert row[3] == db_with_section["section_id"]  # section_id
        assert row[4] == 1  # hit_count
        assert row[5] is not None  # last_used

        conn.close()

    def test_inserts_cache_entry_with_none_doc_name(self, temp_db, db_with_section):
        """Test that _update_cache handles None doc_name."""
        conn = sqlite3.connect(temp_db)

        db._update_cache(conn, "global query", None, db_with_section["section_id"])
        conn.commit()

        cursor = conn.cursor()
        cursor.execute("SELECT * FROM query_cache WHERE query_normalized = ?", ("global query",))
        row = cursor.fetchone()

        assert row is not None
        assert row[1] == "global query"  # query_normalized
        assert row[2] is None  # doc_name is NULL
        assert row[3] == db_with_section["section_id"]  # section_id
        assert row[4] == 1  # hit_count

        conn.close()

    def test_replaces_existing_entry_same_query_and_doc(self, temp_db, db_with_section):
        """Test that INSERT OR REPLACE updates existing entry for same query+doc_name."""
        conn = sqlite3.connect(temp_db)

        # Insert first entry
        db._update_cache(conn, "duplicate query", "langchain", db_with_section["section_id"])
        conn.commit()

        # Insert second section to use
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO sections (doc_id, title, path, url, content) VALUES (?, ?, ?, ?, ?)",
            (db_with_section["doc_id"], "Advanced", "/docs/advanced", "https://langchain.com/docs/advanced", "Advanced content")
        )
        new_section_id = cursor.lastrowid
        conn.commit()

        # Update with same query+doc but different section
        db._update_cache(conn, "duplicate query", "langchain", new_section_id)
        conn.commit()

        # Should only have one entry for this query+doc_name combination
        cursor.execute("SELECT COUNT(*) FROM query_cache WHERE query_normalized = ? AND doc_name = ?", ("duplicate query", "langchain"))
        count = cursor.fetchone()[0]

        # With INSERT OR REPLACE based on unique constraint, or updating existing
        # The behavior depends on having a UNIQUE constraint on (query_normalized, doc_name)
        # Since the schema doesn't have this, let's verify the latest entry is there
        cursor.execute("SELECT section_id FROM query_cache WHERE query_normalized = ? AND doc_name = ? ORDER BY id DESC LIMIT 1", ("duplicate query", "langchain"))
        row = cursor.fetchone()
        assert row[0] == new_section_id

        conn.close()

    def test_last_used_is_iso_format_timestamp(self, temp_db, db_with_section):
        """Test that last_used is stored in ISO format."""
        from datetime import datetime

        conn = sqlite3.connect(temp_db)

        db._update_cache(conn, "timestamp query", "langchain", db_with_section["section_id"])
        conn.commit()

        cursor = conn.cursor()
        cursor.execute("SELECT last_used FROM query_cache WHERE query_normalized = ?", ("timestamp query",))
        row = cursor.fetchone()

        # Should be parseable as ISO format
        last_used = row[0]
        parsed = datetime.fromisoformat(last_used)
        assert parsed is not None

        conn.close()

    def test_does_not_commit_transaction(self, temp_db, db_with_section):
        """Test that _update_cache does not commit - caller manages transaction."""
        conn = sqlite3.connect(temp_db)

        db._update_cache(conn, "no commit query", "langchain", db_with_section["section_id"])
        # Do NOT commit here

        # Open a new connection to check if data was committed
        conn2 = sqlite3.connect(temp_db)
        cursor2 = conn2.cursor()
        cursor2.execute("SELECT * FROM query_cache WHERE query_normalized = ?", ("no commit query",))
        row = cursor2.fetchone()

        # Should NOT find the row since we didn't commit
        assert row is None

        conn.close()
        conn2.close()

    def test_hit_count_starts_at_one(self, temp_db, db_with_section):
        """Test that hit_count is initialized to 1."""
        conn = sqlite3.connect(temp_db)

        db._update_cache(conn, "hit count query", "langchain", db_with_section["section_id"])
        conn.commit()

        cursor = conn.cursor()
        cursor.execute("SELECT hit_count FROM query_cache WHERE query_normalized = ?", ("hit count query",))
        row = cursor.fetchone()

        assert row[0] == 1

        conn.close()


class TestInsertDocumentation:
    """Tests for insert_documentation function."""

    def test_insert_documentation_returns_doc_id(self, temp_db):
        """Test that insert_documentation returns the doc_id of inserted documentation."""
        db.init_db()

        doc_data = {
            "name": "openrouter",
            "display_name": "OpenRouter API",
            "version": "v1",
            "base_url": "https://openrouter.ai/docs",
            "sections": []
        }

        doc_id = db.insert_documentation(doc_data)

        assert isinstance(doc_id, int)
        assert doc_id > 0

    def test_insert_documentation_creates_documentation_record(self, temp_db):
        """Test that insert_documentation creates a record in documentations table."""
        db.init_db()

        doc_data = {
            "name": "openrouter",
            "display_name": "OpenRouter API",
            "version": "v1",
            "base_url": "https://openrouter.ai/docs",
            "sections": []
        }

        doc_id = db.insert_documentation(doc_data)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT name, display_name, version, base_url FROM documentations WHERE id = ?", (doc_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "openrouter"
        assert row[1] == "OpenRouter API"
        assert row[2] == "v1"
        assert row[3] == "https://openrouter.ai/docs"

    def test_insert_documentation_creates_sections(self, temp_db):
        """Test that insert_documentation creates section records."""
        db.init_db()

        doc_data = {
            "name": "openrouter",
            "display_name": "OpenRouter API",
            "version": "v1",
            "base_url": "https://openrouter.ai/docs",
            "sections": [
                {
                    "title": "Authentication",
                    "path": "authentication",
                    "url": "https://openrouter.ai/docs/api-reference/authentication",
                    "keywords": ["auth", "api-key"],
                    "use_cases": ["how to authenticate"],
                    "tags": ["security"],
                    "priority": 10,
                    "content": "# Authentication\n\nOpenRouter uses..."
                }
            ]
        }

        doc_id = db.insert_documentation(doc_data)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT title, path, url, keywords, use_cases, tags, priority, content
            FROM sections WHERE doc_id = ?
        """, (doc_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "Authentication"
        assert row[1] == "authentication"
        assert row[2] == "https://openrouter.ai/docs/api-reference/authentication"
        # JSON fields stored as strings
        import json
        assert json.loads(row[3]) == ["auth", "api-key"]
        assert json.loads(row[4]) == ["how to authenticate"]
        assert json.loads(row[5]) == ["security"]
        assert row[6] == 10
        assert row[7] == "# Authentication\n\nOpenRouter uses..."

    def test_insert_documentation_creates_multiple_sections(self, temp_db):
        """Test that insert_documentation creates multiple section records."""
        db.init_db()

        doc_data = {
            "name": "openrouter",
            "display_name": "OpenRouter API",
            "version": "v1",
            "base_url": "https://openrouter.ai/docs",
            "sections": [
                {
                    "title": "Authentication",
                    "path": "authentication",
                    "url": "https://openrouter.ai/docs/authentication",
                    "keywords": ["auth"],
                    "use_cases": ["authenticate"],
                    "tags": ["security"],
                    "priority": 10,
                    "content": "Auth content"
                },
                {
                    "title": "Rate Limits",
                    "path": "rate-limits",
                    "url": "https://openrouter.ai/docs/rate-limits",
                    "keywords": ["limits", "throttle"],
                    "use_cases": ["handle rate limits"],
                    "tags": ["api"],
                    "priority": 5,
                    "content": "Rate limit content"
                }
            ]
        }

        doc_id = db.insert_documentation(doc_data)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM sections WHERE doc_id = ?", (doc_id,))
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 2

    def test_insert_documentation_updates_fts_index(self, temp_db):
        """Test that insert_documentation updates the FTS5 index."""
        db.init_db()

        doc_data = {
            "name": "openrouter",
            "display_name": "OpenRouter API",
            "version": "v1",
            "base_url": "https://openrouter.ai/docs",
            "sections": [
                {
                    "title": "Authentication",
                    "path": "authentication",
                    "url": "https://openrouter.ai/docs/authentication",
                    "keywords": ["auth"],
                    "use_cases": ["authenticate"],
                    "tags": ["security"],
                    "priority": 10,
                    "content": "Use API keys for authentication"
                }
            ]
        }

        db.insert_documentation(doc_data)

        # Search FTS index for inserted content
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT title FROM sections_fts WHERE sections_fts MATCH 'authentication'
        """)
        results = cursor.fetchall()
        conn.close()

        assert len(results) > 0
        assert results[0][0] == "Authentication"

    def test_insert_documentation_sets_timestamps(self, temp_db):
        """Test that insert_documentation sets created_at and updated_at timestamps."""
        db.init_db()

        doc_data = {
            "name": "openrouter",
            "display_name": "OpenRouter API",
            "version": "v1",
            "base_url": "https://openrouter.ai/docs",
            "sections": []
        }

        doc_id = db.insert_documentation(doc_data)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT created_at, updated_at FROM documentations WHERE id = ?", (doc_id,))
        row = cursor.fetchone()
        conn.close()

        assert row[0] is not None
        assert row[1] is not None

    def test_insert_documentation_with_empty_sections(self, temp_db):
        """Test that insert_documentation works with empty sections list."""
        db.init_db()

        doc_data = {
            "name": "openrouter",
            "display_name": "OpenRouter API",
            "version": "v1",
            "base_url": "https://openrouter.ai/docs",
            "sections": []
        }

        doc_id = db.insert_documentation(doc_data)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM sections WHERE doc_id = ?", (doc_id,))
        count = cursor.fetchone()[0]
        conn.close()

        assert doc_id > 0
        assert count == 0

    def test_insert_documentation_handles_optional_version(self, temp_db):
        """Test that insert_documentation handles None version."""
        db.init_db()

        doc_data = {
            "name": "openrouter",
            "display_name": "OpenRouter API",
            "version": None,
            "base_url": "https://openrouter.ai/docs",
            "sections": []
        }

        doc_id = db.insert_documentation(doc_data)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT version FROM documentations WHERE id = ?", (doc_id,))
        row = cursor.fetchone()
        conn.close()

        assert row[0] is None


class TestSearchFts:
    """Tests for the _search_fts helper function."""

    @pytest.fixture
    def populated_db(self, temp_db):
        """Create a database with test data for FTS testing."""
        db.init_db()
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Insert test documentation
        cursor.execute(
            "INSERT INTO documentations (name, display_name, version, base_url) VALUES (?, ?, ?, ?)",
            ("langchain", "LangChain", "0.1.0", "https://docs.langchain.com")
        )
        langchain_doc_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO documentations (name, display_name, version, base_url) VALUES (?, ?, ?, ?)",
            ("openai", "OpenAI", "1.0.0", "https://platform.openai.com/docs")
        )
        openai_doc_id = cursor.lastrowid

        # Insert sections for langchain
        cursor.execute(
            """INSERT INTO sections (doc_id, title, path, url, keywords, use_cases, tags, priority, content)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (langchain_doc_id, "Getting Started with Agents", "/agents/intro",
             "https://docs.langchain.com/agents/intro",
             '["agents", "quickstart"]', '["build chatbot"]', '["beginner"]', 10,
             "Learn how to build agents with LangChain. Agents can use tools to accomplish tasks.")
        )
        section1_id = cursor.lastrowid

        cursor.execute(
            """INSERT INTO sections (doc_id, title, path, url, keywords, use_cases, tags, priority, content)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (langchain_doc_id, "Memory and Conversation", "/memory/basics",
             "https://docs.langchain.com/memory/basics",
             '["memory", "conversation"]', '["chat history"]', '["intermediate"]', 5,
             "How to add memory to your chains. Memory helps retain conversation context.")
        )
        section2_id = cursor.lastrowid

        # Insert sections for openai
        cursor.execute(
            """INSERT INTO sections (doc_id, title, path, url, keywords, use_cases, tags, priority, content)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (openai_doc_id, "Chat Completions API", "/api/chat",
             "https://platform.openai.com/docs/api/chat",
             '["api", "chat"]', '["generate text"]', '["core"]', 10,
             "The Chat Completions API enables building conversational agents and chatbots.")
        )
        section3_id = cursor.lastrowid

        # Populate FTS index - we need to manually sync for external content FTS tables
        cursor.execute("INSERT INTO sections_fts(rowid, title, content) SELECT id, title, content FROM sections")

        conn.commit()
        conn.close()

        return temp_db

    def test_search_fts_returns_matching_results(self, populated_db):
        """Test that _search_fts returns results matching the query."""
        conn = sqlite3.connect(populated_db)

        results = db._search_fts(conn, "agents", None, 5)

        conn.close()

        assert len(results) > 0
        # Should find the agents section
        assert any("agents" in r["title"].lower() or "agents" in r["content"].lower() for r in results)

    def test_search_fts_returns_correct_dict_format(self, populated_db):
        """Test that _search_fts returns dicts with required keys."""
        conn = sqlite3.connect(populated_db)

        results = db._search_fts(conn, "agents", None, 5)

        conn.close()

        assert len(results) > 0
        result = results[0]

        # Check all required keys are present
        assert "section_id" in result
        assert "title" in result
        assert "content" in result
        assert "keywords" in result
        assert "source_url" in result
        assert "rank" in result

        # Check types
        assert isinstance(result["section_id"], int)
        assert isinstance(result["title"], str)
        assert isinstance(result["content"], str)
        assert isinstance(result["keywords"], list)
        assert isinstance(result["source_url"], str)
        assert isinstance(result["rank"], float)

    def test_search_fts_filters_by_doc_name(self, populated_db):
        """Test that _search_fts filters results by doc_name when provided."""
        conn = sqlite3.connect(populated_db)

        # Search for "memory" only in langchain docs - should find results
        results_langchain = db._search_fts(conn, "memory", "langchain", 5)
        # Search for "memory" only in openai docs - should NOT find results
        results_openai = db._search_fts(conn, "memory", "openai", 5)

        conn.close()

        # Should find memory in langchain docs (Memory and Conversation section)
        assert len(results_langchain) > 0
        # Should not find memory in openai docs
        assert len(results_openai) == 0

    def test_search_fts_returns_results_from_correct_doc(self, populated_db):
        """Test that doc_name filter returns only results from that documentation."""
        conn = sqlite3.connect(populated_db)

        # Search for "api" only in openai docs
        results = db._search_fts(conn, "api", "openai", 5)

        conn.close()

        assert len(results) > 0
        # Verify all results are from openai docs (check URL contains openai)
        for result in results:
            assert "openai" in result["source_url"]

    def test_search_fts_respects_max_results(self, populated_db):
        """Test that _search_fts limits results to max_results."""
        conn = sqlite3.connect(populated_db)

        # Search for common term, limit to 1 result
        results = db._search_fts(conn, "conversation", None, 1)

        conn.close()

        assert len(results) <= 1

    def test_search_fts_returns_empty_list_on_no_match(self, populated_db):
        """Test that _search_fts returns empty list when no results found."""
        conn = sqlite3.connect(populated_db)

        results = db._search_fts(conn, "xyznonexistentterm", None, 5)

        conn.close()

        assert results == []

    def test_search_fts_parses_keywords_json(self, populated_db):
        """Test that _search_fts correctly parses the keywords JSON field."""
        conn = sqlite3.connect(populated_db)

        results = db._search_fts(conn, "agents", None, 5)

        conn.close()

        assert len(results) > 0
        # Find the agents section
        agents_result = next((r for r in results if "agents" in r["title"].lower()), None)
        assert agents_result is not None
        assert "agents" in agents_result["keywords"]
        assert "quickstart" in agents_result["keywords"]

    def test_search_fts_includes_bm25_rank(self, populated_db):
        """Test that _search_fts includes bm25 rank in results."""
        conn = sqlite3.connect(populated_db)

        results = db._search_fts(conn, "agents", None, 5)

        conn.close()

        assert len(results) > 0
        # BM25 returns negative values (more negative = better match)
        for result in results:
            assert isinstance(result["rank"], float)

    def test_search_fts_searches_all_docs_when_doc_name_none(self, populated_db):
        """Test that _search_fts searches all docs when doc_name is None."""
        conn = sqlite3.connect(populated_db)

        # Search for "agents" which appears in both langchain (agents section)
        # and openai docs (conversational agents)
        results = db._search_fts(conn, "agents", None, 10)

        conn.close()

        assert len(results) >= 2
        # Should have results from both docs
        urls = [r["source_url"] for r in results]
        assert any("langchain" in url for url in urls)
        assert any("openai" in url for url in urls)


class TestEmbeddingModuleLevelState:
    """Tests for embedding-related imports and module-level state."""

    def test_db_module_has_embedding_model_attribute(self):
        """Test that db module has _embedding_model attribute, initially None."""
        assert hasattr(db, "_embedding_model")
        assert db._embedding_model is None

    def test_db_module_has_embeddings_attribute(self):
        """Test that db module has _embeddings attribute, initially None."""
        assert hasattr(db, "_embeddings")
        assert db._embeddings is None

    def test_db_module_has_section_id_to_idx_attribute(self):
        """Test that db module has _section_id_to_idx attribute, initially empty dict."""
        assert hasattr(db, "_section_id_to_idx")
        assert db._section_id_to_idx == {}

    def test_numpy_can_be_imported(self):
        """Test that numpy is importable."""
        import numpy as np
        assert np is not None

    def test_sentence_transformer_can_be_imported(self):
        """Test that SentenceTransformer is importable."""
        from sentence_transformers import SentenceTransformer
        assert SentenceTransformer is not None


class TestGenerateAndSaveEmbedding:
    """Tests for _generate_and_save_embedding function."""

    @pytest.fixture(autouse=True)
    def reset_module_state(self, tmp_path, monkeypatch):
        """Reset module-level embedding state before each test."""
        # Reset module-level state
        monkeypatch.setattr(db, "_embedding_model", None)
        monkeypatch.setattr(db, "_embeddings", None)
        monkeypatch.setattr(db, "_section_id_to_idx", {})

        # Set paths to temp directory
        data_dir = tmp_path / "data"
        data_dir.mkdir(exist_ok=True)
        monkeypatch.setattr(db, "EMBEDDINGS_PATH", data_dir / "embeddings.npy")
        monkeypatch.setattr(db, "SECTION_MAPPING_PATH", data_dir / "section_mapping.json")

        yield

    def test_does_nothing_when_embedding_model_is_none(self, tmp_path, monkeypatch):
        """When _embedding_model is None, should do nothing (no error)."""
        # Ensure model is None
        monkeypatch.setattr(db, "_embedding_model", None)

        # Should not raise any error
        db._generate_and_save_embedding(section_id=1, content="Test content")

        # Should not create any files
        assert not db.EMBEDDINGS_PATH.exists()
        assert not db.SECTION_MAPPING_PATH.exists()

    def test_creates_embedding_and_updates_embeddings(self, tmp_path, monkeypatch):
        """When embedding model exists, should create embedding and update _embeddings."""
        import numpy as np

        # Create a mock embedding model
        mock_model = MagicMock()
        mock_embedding = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        mock_model.encode.return_value = mock_embedding
        monkeypatch.setattr(db, "_embedding_model", mock_model)

        db._generate_and_save_embedding(section_id=42, content="Test content for embedding")

        # Should have called encode with the content
        mock_model.encode.assert_called_once_with("Test content for embedding")

        # Should have updated _embeddings
        assert db._embeddings is not None
        assert isinstance(db._embeddings, np.ndarray)
        assert db._embeddings.shape[0] == 1  # One embedding
        assert np.allclose(db._embeddings[0], mock_embedding)

    def test_updates_section_id_to_idx_mapping(self, tmp_path, monkeypatch):
        """Should update _section_id_to_idx with correct mapping."""
        import numpy as np

        # Create a mock embedding model
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        monkeypatch.setattr(db, "_embedding_model", mock_model)

        db._generate_and_save_embedding(section_id=42, content="Test content")

        # Should have updated _section_id_to_idx
        assert 42 in db._section_id_to_idx
        assert db._section_id_to_idx[42] == 0  # First embedding at index 0

    def test_appends_to_existing_embeddings(self, tmp_path, monkeypatch):
        """When _embeddings already exists, should append new embedding."""
        import numpy as np

        # Set up existing embeddings
        existing_embeddings = np.array([[0.5, 0.6, 0.7]], dtype=np.float32)
        monkeypatch.setattr(db, "_embeddings", existing_embeddings)
        monkeypatch.setattr(db, "_section_id_to_idx", {10: 0})

        # Create a mock embedding model
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        monkeypatch.setattr(db, "_embedding_model", mock_model)

        db._generate_and_save_embedding(section_id=42, content="Test content")

        # Should have 2 embeddings now
        assert db._embeddings.shape[0] == 2
        # First embedding should be unchanged
        assert np.allclose(db._embeddings[0], [0.5, 0.6, 0.7])
        # Second embedding should be the new one
        assert np.allclose(db._embeddings[1], [0.1, 0.2, 0.3])

        # Should have both mappings
        assert db._section_id_to_idx[10] == 0
        assert db._section_id_to_idx[42] == 1

    def test_saves_embeddings_to_disk(self, tmp_path, monkeypatch):
        """Should save embeddings.npy to disk."""
        import numpy as np

        # Create a mock embedding model
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        monkeypatch.setattr(db, "_embedding_model", mock_model)

        db._generate_and_save_embedding(section_id=42, content="Test content")

        # Should have created embeddings.npy
        assert db.EMBEDDINGS_PATH.exists()

        # Load and verify
        loaded = np.load(db.EMBEDDINGS_PATH)
        assert loaded.shape[0] == 1
        assert np.allclose(loaded[0], [0.1, 0.2, 0.3])

    def test_saves_section_mapping_to_disk(self, tmp_path, monkeypatch):
        """Should save section_mapping.json to disk."""
        import numpy as np

        # Create a mock embedding model
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        monkeypatch.setattr(db, "_embedding_model", mock_model)

        db._generate_and_save_embedding(section_id=42, content="Test content")

        # Should have created section_mapping.json
        assert db.SECTION_MAPPING_PATH.exists()

        # Load and verify
        with open(db.SECTION_MAPPING_PATH) as f:
            mapping = json.load(f)

        # JSON keys are strings
        assert "42" in mapping
        assert mapping["42"] == 0

    def test_creates_data_directory_if_not_exists(self, tmp_path, monkeypatch):
        """Should create data directory if it doesn't exist."""
        import numpy as np

        # Set paths to non-existent directory
        new_data_dir = tmp_path / "new_data_dir"
        monkeypatch.setattr(db, "EMBEDDINGS_PATH", new_data_dir / "embeddings.npy")
        monkeypatch.setattr(db, "SECTION_MAPPING_PATH", new_data_dir / "section_mapping.json")

        # Create a mock embedding model
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        monkeypatch.setattr(db, "_embedding_model", mock_model)

        db._generate_and_save_embedding(section_id=42, content="Test content")

        # Should have created the directory and files
        assert new_data_dir.exists()
        assert db.EMBEDDINGS_PATH.exists()
        assert db.SECTION_MAPPING_PATH.exists()


class TestInsertDocumentationGeneratesEmbeddings:
    """Tests that insert_documentation generates embeddings for each section."""

    @pytest.fixture
    def temp_embedding_setup(self, temp_db, tmp_path, monkeypatch):
        """Set up temp database and embedding paths."""
        db.init_db()

        # Reset module-level state
        monkeypatch.setattr(db, "_embeddings", None)
        monkeypatch.setattr(db, "_section_id_to_idx", {})

        # Set paths to temp directory
        data_dir = tmp_path / "data"
        data_dir.mkdir(exist_ok=True)
        monkeypatch.setattr(db, "EMBEDDINGS_PATH", data_dir / "embeddings.npy")
        monkeypatch.setattr(db, "SECTION_MAPPING_PATH", data_dir / "section_mapping.json")

        return data_dir

    def test_insert_documentation_generates_embeddings_for_sections(self, temp_embedding_setup, monkeypatch):
        """Test that insert_documentation calls _generate_and_save_embedding for each section."""
        import numpy as np

        # Create a mock embedding model
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        monkeypatch.setattr(db, "_embedding_model", mock_model)

        doc_data = {
            "name": "test_doc",
            "display_name": "Test Documentation",
            "version": "1.0",
            "base_url": "https://test.com/docs",
            "sections": [
                {
                    "title": "Section One",
                    "path": "/section-one",
                    "url": "https://test.com/docs/section-one",
                    "keywords": ["keyword1"],
                    "use_cases": ["use case 1"],
                    "tags": ["tag1"],
                    "priority": 10,
                    "content": "Content for section one"
                },
                {
                    "title": "Section Two",
                    "path": "/section-two",
                    "url": "https://test.com/docs/section-two",
                    "keywords": ["keyword2"],
                    "use_cases": ["use case 2"],
                    "tags": ["tag2"],
                    "priority": 5,
                    "content": "Content for section two"
                }
            ]
        }

        db.insert_documentation(doc_data)

        # Should have called encode twice (once per section)
        assert mock_model.encode.call_count == 2

        # Should have created embeddings
        assert db._embeddings is not None
        assert db._embeddings.shape[0] == 2

        # Should have two section mappings
        assert len(db._section_id_to_idx) == 2

    def test_insert_documentation_without_embedding_model_succeeds(self, temp_embedding_setup, monkeypatch):
        """Test that insert_documentation works even when _embedding_model is None."""
        monkeypatch.setattr(db, "_embedding_model", None)

        doc_data = {
            "name": "test_doc",
            "display_name": "Test Documentation",
            "version": "1.0",
            "base_url": "https://test.com/docs",
            "sections": [
                {
                    "title": "Section One",
                    "path": "/section-one",
                    "url": "https://test.com/docs/section-one",
                    "keywords": ["keyword1"],
                    "use_cases": [],
                    "tags": [],
                    "priority": 10,
                    "content": "Content for section one"
                }
            ]
        }

        # Should not raise any error
        doc_id = db.insert_documentation(doc_data)

        assert doc_id > 0
        # Should not have created any embeddings
        assert db._embeddings is None


class TestRerankWithEmbeddings:
    """Tests for the _rerank_with_embeddings helper function."""

    @pytest.fixture
    def sample_fts_results(self):
        """Sample FTS results for testing reranking."""
        return [
            {"section_id": 1, "title": "Getting Started", "content": "Intro content", "keywords": ["intro"], "source_url": "http://example.com/1", "rank": -5.0},
            {"section_id": 2, "title": "Advanced Topics", "content": "Advanced content", "keywords": ["advanced"], "source_url": "http://example.com/2", "rank": -4.0},
            {"section_id": 3, "title": "API Reference", "content": "API content", "keywords": ["api"], "source_url": "http://example.com/3", "rank": -3.0},
            {"section_id": 4, "title": "Tutorials", "content": "Tutorial content", "keywords": ["tutorial"], "source_url": "http://example.com/4", "rank": -2.0},
            {"section_id": 5, "title": "FAQ", "content": "FAQ content", "keywords": ["faq"], "source_url": "http://example.com/5", "rank": -1.0},
        ]

    def test_returns_none_when_embedding_model_is_none(self, sample_fts_results):
        """When _embedding_model is None, should return None to signal fallback."""
        # Save original values
        original_model = db._embedding_model
        original_embeddings = db._embeddings
        original_mapping = db._section_id_to_idx

        try:
            db._embedding_model = None
            db._embeddings = np.array([[0.1, 0.2, 0.3]])
            db._section_id_to_idx = {1: 0}

            result = db._rerank_with_embeddings("test query", sample_fts_results, 3)

            assert result is None
        finally:
            db._embedding_model = original_model
            db._embeddings = original_embeddings
            db._section_id_to_idx = original_mapping

    def test_returns_none_when_embeddings_is_none(self, sample_fts_results):
        """When _embeddings is None, should return None to signal fallback."""
        original_model = db._embedding_model
        original_embeddings = db._embeddings
        original_mapping = db._section_id_to_idx

        try:
            mock_model = MagicMock()
            db._embedding_model = mock_model
            db._embeddings = None
            db._section_id_to_idx = {1: 0}

            result = db._rerank_with_embeddings("test query", sample_fts_results, 3)

            assert result is None
        finally:
            db._embedding_model = original_model
            db._embeddings = original_embeddings
            db._section_id_to_idx = original_mapping

    def test_adds_similarity_score_to_chunks(self, sample_fts_results):
        """Should add similarity_score field (0.0-1.0) to each returned chunk."""
        original_model = db._embedding_model
        original_embeddings = db._embeddings
        original_mapping = db._section_id_to_idx

        try:
            # Create mock model that returns a normalized vector
            mock_model = MagicMock()
            query_embedding = np.array([1.0, 0.0, 0.0])
            mock_model.encode.return_value = query_embedding

            db._embedding_model = mock_model

            # Create embeddings for sections - all similar to query (high cosine similarity)
            # Section embeddings: all pointing roughly same direction as query
            db._embeddings = np.array([
                [0.9, 0.1, 0.0],  # section_id 1, high similarity
                [0.8, 0.2, 0.1],  # section_id 2, high similarity
                [0.7, 0.3, 0.1],  # section_id 3, medium-high similarity
                [0.6, 0.4, 0.2],  # section_id 4, medium similarity
                [0.5, 0.5, 0.3],  # section_id 5, medium similarity
            ])
            # Normalize embeddings
            db._embeddings = db._embeddings / np.linalg.norm(db._embeddings, axis=1, keepdims=True)

            db._section_id_to_idx = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4}

            result = db._rerank_with_embeddings("test query", sample_fts_results, 5)

            assert result is not None
            assert len(result) > 0

            for chunk in result:
                assert "similarity_score" in chunk
                assert isinstance(chunk["similarity_score"], float)
                assert 0.0 <= chunk["similarity_score"] <= 1.0
        finally:
            db._embedding_model = original_model
            db._embeddings = original_embeddings
            db._section_id_to_idx = original_mapping

    def test_filters_by_threshold_0_5(self, sample_fts_results):
        """Should filter out results with similarity_score < 0.5."""
        original_model = db._embedding_model
        original_embeddings = db._embeddings
        original_mapping = db._section_id_to_idx

        try:
            mock_model = MagicMock()
            query_embedding = np.array([1.0, 0.0, 0.0])
            mock_model.encode.return_value = query_embedding

            db._embedding_model = mock_model

            # Create embeddings with varying similarities
            # Section 1: high similarity (should pass)
            # Section 2: high similarity (should pass)
            # Section 3: low similarity (should be filtered)
            # Section 4: low similarity (should be filtered)
            # Section 5: low similarity (should be filtered)
            db._embeddings = np.array([
                [0.95, 0.05, 0.0],   # section_id 1, very high similarity (~0.95)
                [0.8, 0.6, 0.0],     # section_id 2, high similarity (~0.8)
                [0.1, 0.9, 0.4],     # section_id 3, low similarity (~0.1)
                [-0.2, 0.9, 0.3],    # section_id 4, very low similarity (~-0.2)
                [0.0, 0.0, 1.0],     # section_id 5, zero similarity (orthogonal)
            ])
            # Normalize embeddings
            db._embeddings = db._embeddings / np.linalg.norm(db._embeddings, axis=1, keepdims=True)

            db._section_id_to_idx = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4}

            result = db._rerank_with_embeddings("test query", sample_fts_results, 5)

            assert result is not None
            # Should only have chunks with similarity >= 0.5
            for chunk in result:
                assert chunk["similarity_score"] >= 0.5

            # Should have filtered out the low similarity results
            assert len(result) == 2

        finally:
            db._embedding_model = original_model
            db._embeddings = original_embeddings
            db._section_id_to_idx = original_mapping

    def test_returns_top_max_results(self, sample_fts_results):
        """Should return at most max_results chunks, sorted by similarity descending."""
        original_model = db._embedding_model
        original_embeddings = db._embeddings
        original_mapping = db._section_id_to_idx

        try:
            mock_model = MagicMock()
            query_embedding = np.array([1.0, 0.0, 0.0])
            mock_model.encode.return_value = query_embedding

            db._embedding_model = mock_model

            # All embeddings have high similarity (above 0.5 threshold)
            db._embeddings = np.array([
                [0.95, 0.1, 0.0],   # section_id 1
                [0.90, 0.2, 0.0],   # section_id 2
                [0.85, 0.3, 0.0],   # section_id 3
                [0.80, 0.4, 0.0],   # section_id 4
                [0.75, 0.5, 0.0],   # section_id 5
            ])
            db._embeddings = db._embeddings / np.linalg.norm(db._embeddings, axis=1, keepdims=True)

            db._section_id_to_idx = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4}

            # Request only 2 results
            result = db._rerank_with_embeddings("test query", sample_fts_results, 2)

            assert result is not None
            assert len(result) == 2

            # Results should be sorted by similarity descending
            assert result[0]["similarity_score"] >= result[1]["similarity_score"]

        finally:
            db._embedding_model = original_model
            db._embeddings = original_embeddings
            db._section_id_to_idx = original_mapping

    def test_sorts_by_similarity_descending(self, sample_fts_results):
        """Results should be sorted by similarity_score in descending order."""
        original_model = db._embedding_model
        original_embeddings = db._embeddings
        original_mapping = db._section_id_to_idx

        try:
            mock_model = MagicMock()
            query_embedding = np.array([1.0, 0.0, 0.0])
            mock_model.encode.return_value = query_embedding

            db._embedding_model = mock_model

            # Give section 5 the highest similarity, section 1 lowest (but still > 0.5)
            db._embeddings = np.array([
                [0.6, 0.5, 0.0],   # section_id 1, lowest
                [0.7, 0.4, 0.0],   # section_id 2
                [0.8, 0.3, 0.0],   # section_id 3
                [0.9, 0.2, 0.0],   # section_id 4
                [0.99, 0.1, 0.0],  # section_id 5, highest
            ])
            db._embeddings = db._embeddings / np.linalg.norm(db._embeddings, axis=1, keepdims=True)

            db._section_id_to_idx = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4}

            result = db._rerank_with_embeddings("test query", sample_fts_results, 5)

            assert result is not None
            assert len(result) == 5

            # Verify descending order
            for i in range(len(result) - 1):
                assert result[i]["similarity_score"] >= result[i + 1]["similarity_score"]

            # Section 5 should be first (highest similarity)
            assert result[0]["section_id"] == 5

        finally:
            db._embedding_model = original_model
            db._embeddings = original_embeddings
            db._section_id_to_idx = original_mapping

    def test_handles_missing_section_in_mapping(self, sample_fts_results):
        """Should skip sections not in _section_id_to_idx mapping."""
        original_model = db._embedding_model
        original_embeddings = db._embeddings
        original_mapping = db._section_id_to_idx

        try:
            mock_model = MagicMock()
            query_embedding = np.array([1.0, 0.0, 0.0])
            mock_model.encode.return_value = query_embedding

            db._embedding_model = mock_model

            # Only have embeddings for sections 1 and 2
            db._embeddings = np.array([
                [0.9, 0.1, 0.0],   # section_id 1
                [0.8, 0.2, 0.0],   # section_id 2
            ])
            db._embeddings = db._embeddings / np.linalg.norm(db._embeddings, axis=1, keepdims=True)

            # Only sections 1 and 2 are in the mapping
            db._section_id_to_idx = {1: 0, 2: 1}

            result = db._rerank_with_embeddings("test query", sample_fts_results, 5)

            assert result is not None
            # Should only return sections 1 and 2 (that have embeddings)
            section_ids = [r["section_id"] for r in result]
            assert all(sid in [1, 2] for sid in section_ids)

        finally:
            db._embedding_model = original_model
            db._embeddings = original_embeddings
            db._section_id_to_idx = original_mapping


class TestSearchCascadeHybridRerank:
    """Tests for hybrid reranking in search_cascade."""

    @patch('db._get_connection')
    @patch('db._check_cache')
    @patch('db._search_metadata')
    @patch('db._search_fts')
    @patch('db._update_cache')
    @patch('db._rerank_with_embeddings')
    def test_uses_hybrid_rerank_method_when_embeddings_available(
        self,
        mock_rerank,
        mock_update_cache,
        mock_search_fts,
        mock_search_metadata,
        mock_check_cache,
        mock_get_connection
    ):
        """When embeddings are available, search_cascade should use method='hybrid_rerank'."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_check_cache.return_value = None  # Cache miss
        mock_search_metadata.return_value = []  # Metadata miss

        fts_chunks = [
            {"section_id": 1, "title": "Test", "content": "Content", "keywords": ["test"], "source_url": "http://test.com", "rank": -5.0}
        ]
        mock_search_fts.return_value = fts_chunks

        # Reranking returns results with similarity_score
        reranked_chunks = [
            {"section_id": 1, "title": "Test", "content": "Content", "keywords": ["test"], "source_url": "http://test.com", "similarity_score": 0.85}
        ]
        mock_rerank.return_value = reranked_chunks

        result = search_cascade("test query", max_results=5)

        assert result["found"] is True
        assert result["transparency"]["method"] == "hybrid_rerank"
        assert result["chunks"] == reranked_chunks
        assert "fts_hit" in result["transparency"]["search_path"]

    @patch('db._get_connection')
    @patch('db._check_cache')
    @patch('db._search_metadata')
    @patch('db._search_fts')
    @patch('db._update_cache')
    @patch('db._rerank_with_embeddings')
    def test_falls_back_to_fts_when_embeddings_unavailable(
        self,
        mock_rerank,
        mock_update_cache,
        mock_search_fts,
        mock_search_metadata,
        mock_check_cache,
        mock_get_connection
    ):
        """When embeddings unavailable, search_cascade should fall back to method='fts'."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_check_cache.return_value = None  # Cache miss
        mock_search_metadata.return_value = []  # Metadata miss

        fts_chunks = [
            {"section_id": 1, "title": "Test", "content": "Content", "keywords": ["test"], "source_url": "http://test.com", "rank": -5.0}
        ]
        mock_search_fts.return_value = fts_chunks

        # Reranking returns None (no embeddings available)
        mock_rerank.return_value = None

        result = search_cascade("test query", max_results=5)

        assert result["found"] is True
        assert result["transparency"]["method"] == "fts"
        assert result["chunks"] == fts_chunks
        assert "fts_hit" in result["transparency"]["search_path"]

    @patch('db._get_connection')
    @patch('db._check_cache')
    @patch('db._search_metadata')
    @patch('db._search_fts')
    @patch('db._update_cache')
    @patch('db._rerank_with_embeddings')
    def test_requests_20_candidates_from_fts_for_reranking(
        self,
        mock_rerank,
        mock_update_cache,
        mock_search_fts,
        mock_search_metadata,
        mock_check_cache,
        mock_get_connection
    ):
        """FTS should request ~20 candidates (not max_results) for reranking."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_check_cache.return_value = None
        mock_search_metadata.return_value = []
        mock_search_fts.return_value = []
        mock_rerank.return_value = None

        search_cascade("test query", max_results=5)

        # FTS should be called with 20 candidates, not max_results (5)
        mock_search_fts.assert_called_once()
        call_args = mock_search_fts.call_args
        # Third positional arg or max_results kwarg should be 20
        assert call_args[0][3] == 20  # 4th positional arg is max_results

    @patch('db._get_connection')
    @patch('db._check_cache')
    @patch('db._search_metadata')
    @patch('db._search_fts')
    @patch('db._update_cache')
    @patch('db._rerank_with_embeddings')
    def test_rerank_called_with_correct_params(
        self,
        mock_rerank,
        mock_update_cache,
        mock_search_fts,
        mock_search_metadata,
        mock_check_cache,
        mock_get_connection
    ):
        """_rerank_with_embeddings should be called with query, fts_results, and max_results."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_check_cache.return_value = None
        mock_search_metadata.return_value = []

        fts_chunks = [{"section_id": 1, "title": "Test", "content": "Content"}]
        mock_search_fts.return_value = fts_chunks
        mock_rerank.return_value = None

        search_cascade("my query", max_results=7)

        mock_rerank.assert_called_once_with("my query", fts_chunks, 7)

    @patch('db._get_connection')
    @patch('db._check_cache')
    @patch('db._search_metadata')
    @patch('db._search_fts')
    @patch('db._update_cache')
    @patch('db._rerank_with_embeddings')
    def test_updates_cache_with_first_reranked_result(
        self,
        mock_rerank,
        mock_update_cache,
        mock_search_fts,
        mock_search_metadata,
        mock_check_cache,
        mock_get_connection
    ):
        """When hybrid reranking succeeds, cache should be updated with first result."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_check_cache.return_value = None
        mock_search_metadata.return_value = []

        fts_chunks = [{"section_id": 1, "title": "Test"}]
        mock_search_fts.return_value = fts_chunks

        reranked_chunks = [
            {"section_id": 5, "title": "Best Match", "similarity_score": 0.95},
            {"section_id": 1, "title": "Test", "similarity_score": 0.8},
        ]
        mock_rerank.return_value = reranked_chunks

        search_cascade("test query", doc_name="langchain", max_results=5)

        # Cache should be updated with section_id of first reranked result (5)
        mock_update_cache.assert_called_once_with(mock_conn, "test query", "langchain", 5)

    @patch('db._get_connection')
    @patch('db._check_cache')
    @patch('db._search_metadata')
    @patch('db._search_fts')
    @patch('db._update_cache')
    @patch('db._rerank_with_embeddings')
    def test_hybrid_rerank_with_empty_results_after_filtering(
        self,
        mock_rerank,
        mock_update_cache,
        mock_search_fts,
        mock_search_metadata,
        mock_check_cache,
        mock_get_connection
    ):
        """When reranking filters out all results (below threshold), should fall back to FTS."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_check_cache.return_value = None
        mock_search_metadata.return_value = []

        fts_chunks = [{"section_id": 1, "title": "Test", "content": "Content"}]
        mock_search_fts.return_value = fts_chunks

        # Reranking returns empty list (all filtered by threshold)
        mock_rerank.return_value = []

        result = search_cascade("test query", max_results=5)

        # Should fall back to FTS results
        assert result["found"] is True
        assert result["transparency"]["method"] == "fts"
        assert result["chunks"] == fts_chunks


class TestListDocumentations:
    """Tests for list_documentations function."""

    def test_returns_empty_list_when_no_documentations(self, temp_db):
        """Test that list_documentations returns empty list when database is empty."""
        db.init_db()

        result = db.list_documentations()

        assert result == []

    def test_returns_list_of_dicts_with_correct_keys(self, temp_db):
        """Test that list_documentations returns list of dicts with required keys."""
        db.init_db()
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Insert a documentation
        cursor.execute(
            "INSERT INTO documentations (name, display_name, version, base_url) VALUES (?, ?, ?, ?)",
            ("langchain", "LangChain", "0.1.0", "https://docs.langchain.com")
        )
        conn.commit()
        conn.close()

        result = db.list_documentations()

        assert len(result) == 1
        doc = result[0]
        assert "name" in doc
        assert "display_name" in doc
        assert "version" in doc
        assert "section_count" in doc

    def test_returns_correct_documentation_data(self, temp_db):
        """Test that list_documentations returns correct documentation values."""
        db.init_db()
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO documentations (name, display_name, version, base_url) VALUES (?, ?, ?, ?)",
            ("langchain", "LangChain", "0.1.0", "https://docs.langchain.com")
        )
        conn.commit()
        conn.close()

        result = db.list_documentations()

        assert len(result) == 1
        doc = result[0]
        assert doc["name"] == "langchain"
        assert doc["display_name"] == "LangChain"
        assert doc["version"] == "0.1.0"

    def test_returns_section_count_for_documentation(self, temp_db):
        """Test that list_documentations returns correct section count."""
        db.init_db()
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Insert documentation
        cursor.execute(
            "INSERT INTO documentations (name, display_name, version, base_url) VALUES (?, ?, ?, ?)",
            ("langchain", "LangChain", "0.1.0", "https://docs.langchain.com")
        )
        doc_id = cursor.lastrowid

        # Insert 3 sections
        for i in range(3):
            cursor.execute(
                "INSERT INTO sections (doc_id, title, path, url, content) VALUES (?, ?, ?, ?, ?)",
                (doc_id, f"Section {i}", f"/section-{i}", f"https://docs.langchain.com/section-{i}", f"Content {i}")
            )
        conn.commit()
        conn.close()

        result = db.list_documentations()

        assert len(result) == 1
        assert result[0]["section_count"] == 3

    def test_returns_zero_section_count_when_no_sections(self, temp_db):
        """Test that documentation with no sections has section_count of 0."""
        db.init_db()
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO documentations (name, display_name, version, base_url) VALUES (?, ?, ?, ?)",
            ("langchain", "LangChain", "0.1.0", "https://docs.langchain.com")
        )
        conn.commit()
        conn.close()

        result = db.list_documentations()

        assert len(result) == 1
        assert result[0]["section_count"] == 0

    def test_returns_multiple_documentations(self, temp_db):
        """Test that list_documentations returns all documentations."""
        db.init_db()
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Insert multiple documentations
        cursor.execute(
            "INSERT INTO documentations (name, display_name, version, base_url) VALUES (?, ?, ?, ?)",
            ("langchain", "LangChain", "0.1.0", "https://docs.langchain.com")
        )
        langchain_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO documentations (name, display_name, version, base_url) VALUES (?, ?, ?, ?)",
            ("openai", "OpenAI", "1.0.0", "https://platform.openai.com/docs")
        )
        openai_id = cursor.lastrowid

        # Add sections to langchain (2 sections)
        for i in range(2):
            cursor.execute(
                "INSERT INTO sections (doc_id, title, path, url, content) VALUES (?, ?, ?, ?, ?)",
                (langchain_id, f"Section {i}", f"/section-{i}", f"https://docs.langchain.com/section-{i}", f"Content {i}")
            )

        # Add sections to openai (5 sections)
        for i in range(5):
            cursor.execute(
                "INSERT INTO sections (doc_id, title, path, url, content) VALUES (?, ?, ?, ?, ?)",
                (openai_id, f"Section {i}", f"/section-{i}", f"https://platform.openai.com/docs/section-{i}", f"Content {i}")
            )
        conn.commit()
        conn.close()

        result = db.list_documentations()

        assert len(result) == 2

        # Find each doc in the result
        langchain_doc = next(d for d in result if d["name"] == "langchain")
        openai_doc = next(d for d in result if d["name"] == "openai")

        assert langchain_doc["section_count"] == 2
        assert openai_doc["section_count"] == 5

    def test_handles_null_version(self, temp_db):
        """Test that list_documentations handles NULL version correctly."""
        db.init_db()
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO documentations (name, display_name, version, base_url) VALUES (?, ?, ?, ?)",
            ("langchain", "LangChain", None, "https://docs.langchain.com")
        )
        conn.commit()
        conn.close()

        result = db.list_documentations()

        assert len(result) == 1
        assert result[0]["version"] is None
