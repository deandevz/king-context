"""
Tests for King Context server.
"""

import pytest
from unittest.mock import patch, MagicMock
from server import search_docs, list_docs, show_context, add_doc


# Access the underlying functions from the FunctionTool wrappers
_search_docs = search_docs.fn
_list_docs = list_docs.fn
_show_context = show_context.fn
_add_doc = add_doc.fn


class TestSearchDocs:
    """Tests for search_docs tool."""

    def test_search_docs_delegates_to_search_cascade(self):
        """search_docs should delegate to search_cascade and return its result."""
        expected_result = {
            "found": True,
            "chunks": [
                {"section_id": 1, "title": "Getting Started", "content": "..."}
            ],
            "transparency": {
                "method": "cache",
                "latency_ms": 1.5,
                "search_path": ["cache"],
                "from_cache": True
            }
        }

        with patch("server.search_cascade", return_value=expected_result) as mock_cascade:
            result = _search_docs(query="authentication", doc_name="openrouter", max_results=3)

            mock_cascade.assert_called_once_with(
                query="authentication",
                doc_name="openrouter",
                max_results=3
            )
            assert result == expected_result

    def test_search_docs_with_defaults(self):
        """search_docs should use default values for optional parameters."""
        expected_result = {
            "found": False,
            "chunks": [],
            "transparency": {
                "method": "fts5",
                "latency_ms": 5.2,
                "search_path": ["cache", "metadata", "fts5"],
                "from_cache": False
            }
        }

        with patch("server.search_cascade", return_value=expected_result) as mock_cascade:
            result = _search_docs(query="unknown query")

            mock_cascade.assert_called_once_with(
                query="unknown query",
                doc_name=None,
                max_results=5
            )
            assert result == expected_result

    def test_search_docs_returns_transparency_object(self):
        """search_docs result must include transparency object with required fields."""
        expected_result = {
            "found": True,
            "chunks": [{"section_id": 2, "title": "Auth", "content": "OAuth flow..."}],
            "transparency": {
                "method": "metadata",
                "latency_ms": 2.1,
                "search_path": ["cache", "metadata"],
                "from_cache": False
            }
        }

        with patch("server.search_cascade", return_value=expected_result) as mock_cascade:
            result = _search_docs(query="oauth")

            assert "transparency" in result
            transparency = result["transparency"]
            assert "method" in transparency
            assert "latency_ms" in transparency
            assert "search_path" in transparency
            assert "from_cache" in transparency


class TestListDocs:
    """Tests for list_docs tool."""

    def test_list_docs_delegates_to_list_documentations(self):
        """list_docs should delegate to list_documentations from db module."""
        mock_docs = [
            {"name": "openrouter", "display_name": "OpenRouter API", "version": "1.0", "section_count": 15},
            {"name": "fastmcp", "display_name": "FastMCP", "version": "2.1", "section_count": 8}
        ]

        with patch("server.list_documentations", return_value=mock_docs) as mock_list:
            result = _list_docs()

            mock_list.assert_called_once()

    def test_list_docs_returns_correct_format(self):
        """list_docs should return docs list with count."""
        mock_docs = [
            {"name": "openrouter", "display_name": "OpenRouter API", "version": "1.0", "section_count": 15},
            {"name": "fastmcp", "display_name": "FastMCP", "version": "2.1", "section_count": 8}
        ]

        with patch("server.list_documentations", return_value=mock_docs):
            result = _list_docs()

            assert "docs" in result
            assert "count" in result
            assert result["docs"] == mock_docs
            assert result["count"] == 2

    def test_list_docs_with_empty_list(self):
        """list_docs should handle empty documentation list."""
        with patch("server.list_documentations", return_value=[]):
            result = _list_docs()

            assert result["docs"] == []
            assert result["count"] == 0

    def test_list_docs_preserves_doc_structure(self):
        """list_docs should preserve all fields from list_documentations."""
        mock_docs = [
            {"name": "test-doc", "display_name": "Test Doc", "version": "0.1", "section_count": 3}
        ]

        with patch("server.list_documentations", return_value=mock_docs):
            result = _list_docs()

            doc = result["docs"][0]
            assert doc["name"] == "test-doc"
            assert doc["display_name"] == "Test Doc"
            assert doc["version"] == "0.1"
            assert doc["section_count"] == 3


class TestShowContext:
    """Tests for show_context tool."""

    def test_show_context_calls_search_cascade(self):
        """show_context should call search_cascade internally."""
        mock_cascade_result = {
            "found": True,
            "chunks": [
                {"section_id": 1, "title": "Getting Started", "content": "Welcome to the API."}
            ],
            "transparency": {
                "method": "cache",
                "latency_ms": 1.5,
                "search_path": ["cache"],
                "from_cache": True
            }
        }

        with patch("server.search_cascade", return_value=mock_cascade_result) as mock_cascade:
            result = _show_context(query="authentication", doc_name="openrouter")

            mock_cascade.assert_called_once_with(
                query="authentication",
                doc_name="openrouter",
                max_results=5
            )

    def test_show_context_returns_required_fields(self):
        """show_context should return all required fields."""
        mock_cascade_result = {
            "found": True,
            "chunks": [
                {"section_id": 1, "title": "Auth", "content": "Authentication guide."}
            ],
            "transparency": {
                "method": "fts5",
                "latency_ms": 2.0,
                "search_path": ["cache", "fts5"],
                "from_cache": False
            }
        }

        with patch("server.search_cascade", return_value=mock_cascade_result):
            result = _show_context(query="auth")

            assert "query" in result
            assert "doc_name" in result
            assert "context_preview" in result
            assert "token_estimate" in result
            assert "chunks_count" in result
            assert "transparency" in result

    def test_show_context_query_and_doc_name(self):
        """show_context should include query and doc_name in result."""
        mock_cascade_result = {
            "found": True,
            "chunks": [],
            "transparency": {
                "method": "fts5",
                "latency_ms": 1.0,
                "search_path": ["cache", "fts5"],
                "from_cache": False
            }
        }

        with patch("server.search_cascade", return_value=mock_cascade_result):
            result = _show_context(query="test query", doc_name="my-docs")

            assert result["query"] == "test query"
            assert result["doc_name"] == "my-docs"

    def test_show_context_doc_name_none_by_default(self):
        """show_context should handle None doc_name."""
        mock_cascade_result = {
            "found": False,
            "chunks": [],
            "transparency": {
                "method": "fts5",
                "latency_ms": 1.0,
                "search_path": ["cache", "fts5"],
                "from_cache": False
            }
        }

        with patch("server.search_cascade", return_value=mock_cascade_result):
            result = _show_context(query="anything")

            assert result["doc_name"] is None

    def test_show_context_token_estimate(self):
        """show_context should estimate tokens as len(content) / 4."""
        # Content is 40 chars, so token estimate should be 10
        mock_cascade_result = {
            "found": True,
            "chunks": [
                {"section_id": 1, "title": "Title", "content": "This is exactly forty characters long!!"}
            ],
            "transparency": {
                "method": "cache",
                "latency_ms": 1.0,
                "search_path": ["cache"],
                "from_cache": True
            }
        }

        with patch("server.search_cascade", return_value=mock_cascade_result):
            result = _show_context(query="test")

            # Token estimate based on the full context_preview string length / 4
            assert "token_estimate" in result
            assert isinstance(result["token_estimate"], int)
            assert result["token_estimate"] > 0

    def test_show_context_chunks_count(self):
        """show_context should return correct chunks_count."""
        mock_cascade_result = {
            "found": True,
            "chunks": [
                {"section_id": 1, "title": "First", "content": "Content 1"},
                {"section_id": 2, "title": "Second", "content": "Content 2"},
                {"section_id": 3, "title": "Third", "content": "Content 3"}
            ],
            "transparency": {
                "method": "fts5",
                "latency_ms": 2.5,
                "search_path": ["cache", "fts5"],
                "from_cache": False
            }
        }

        with patch("server.search_cascade", return_value=mock_cascade_result):
            result = _show_context(query="test")

            assert result["chunks_count"] == 3

    def test_show_context_empty_chunks(self):
        """show_context should handle empty chunks gracefully."""
        mock_cascade_result = {
            "found": False,
            "chunks": [],
            "transparency": {
                "method": "fts5",
                "latency_ms": 1.0,
                "search_path": ["cache", "metadata", "fts5"],
                "from_cache": False
            }
        }

        with patch("server.search_cascade", return_value=mock_cascade_result):
            result = _show_context(query="nonexistent")

            assert result["chunks_count"] == 0
            assert result["token_estimate"] == 0
            assert result["context_preview"] == ""

    def test_show_context_transparency_passthrough(self):
        """show_context should include transparency from search_cascade."""
        expected_transparency = {
            "method": "metadata",
            "latency_ms": 3.2,
            "search_path": ["cache", "metadata"],
            "from_cache": False
        }
        mock_cascade_result = {
            "found": True,
            "chunks": [{"section_id": 1, "title": "Test", "content": "Content"}],
            "transparency": expected_transparency
        }

        with patch("server.search_cascade", return_value=mock_cascade_result):
            result = _show_context(query="test")

            assert result["transparency"] == expected_transparency

    def test_show_context_formats_markdown_with_section_titles(self):
        """show_context should format context_preview as markdown with section titles."""
        mock_cascade_result = {
            "found": True,
            "chunks": [
                {"section_id": 1, "title": "Getting Started", "content": "Welcome to the API."},
                {"section_id": 2, "title": "Authentication", "content": "Use OAuth2 for auth."}
            ],
            "transparency": {
                "method": "cache",
                "latency_ms": 1.0,
                "search_path": ["cache"],
                "from_cache": True
            }
        }

        with patch("server.search_cascade", return_value=mock_cascade_result):
            result = _show_context(query="auth")

            context = result["context_preview"]
            # Should contain markdown headers for section titles
            assert "## Getting Started" in context
            assert "## Authentication" in context
            # Should contain content
            assert "Welcome to the API." in context
            assert "Use OAuth2 for auth." in context


class TestAddDoc:
    """Tests for add_doc tool."""

    def _valid_doc_json(self):
        """Return a valid doc_json fixture."""
        return {
            "name": "openrouter",
            "display_name": "OpenRouter API",
            "version": "v1",
            "base_url": "https://openrouter.ai/docs",
            "sections": [
                {
                    "title": "Getting Started",
                    "path": "/getting-started",
                    "url": "https://openrouter.ai/docs/getting-started",
                    "keywords": ["setup", "quickstart"],
                    "use_cases": ["initial setup"],
                    "tags": ["beginner"],
                    "priority": 10,
                    "content": "Welcome to OpenRouter..."
                }
            ]
        }

    def _valid_section(self):
        """Return a valid section fixture."""
        return {
            "title": "Auth",
            "path": "/auth",
            "url": "https://openrouter.ai/docs/auth",
            "keywords": ["auth", "api-key"],
            "use_cases": ["authentication"],
            "tags": ["security"],
            "priority": 5,
            "content": "Authentication docs..."
        }

    def test_add_doc_validates_required_doc_fields(self):
        """add_doc should return error if required doc fields are missing."""
        required_fields = ["name", "display_name", "version", "base_url", "sections"]

        for field in required_fields:
            doc_json = self._valid_doc_json()
            del doc_json[field]

            result = _add_doc(doc_json=doc_json)

            assert result["success"] is False
            assert result["doc_id"] is None
            assert result["sections_indexed"] == 0
            assert field in result["message"]

    def test_add_doc_validates_required_section_fields(self):
        """add_doc should return error if required section fields are missing."""
        required_section_fields = [
            "title", "path", "url", "keywords", "use_cases", "tags", "priority", "content"
        ]

        for field in required_section_fields:
            doc_json = self._valid_doc_json()
            del doc_json["sections"][0][field]

            result = _add_doc(doc_json=doc_json)

            assert result["success"] is False
            assert result["doc_id"] is None
            assert result["sections_indexed"] == 0
            assert field in result["message"]

    def test_add_doc_validates_multiple_sections(self):
        """add_doc should validate all sections, not just the first."""
        doc_json = self._valid_doc_json()
        invalid_section = self._valid_section()
        del invalid_section["content"]
        doc_json["sections"].append(invalid_section)

        result = _add_doc(doc_json=doc_json)

        assert result["success"] is False
        assert "content" in result["message"]

    def test_add_doc_calls_insert_documentation_on_valid_input(self):
        """add_doc should call insert_documentation from db module with valid input."""
        doc_json = self._valid_doc_json()

        with patch("server.insert_documentation", return_value=42) as mock_insert:
            result = _add_doc(doc_json=doc_json)

            mock_insert.assert_called_once_with(doc_json)

    def test_add_doc_returns_success_format(self):
        """add_doc should return correct format on success."""
        doc_json = self._valid_doc_json()

        with patch("server.insert_documentation", return_value=42):
            result = _add_doc(doc_json=doc_json)

            assert result["success"] is True
            assert result["doc_id"] == 42
            assert result["sections_indexed"] == 1
            assert "message" in result

    def test_add_doc_counts_multiple_sections(self):
        """add_doc should report correct number of sections indexed."""
        doc_json = self._valid_doc_json()
        doc_json["sections"].append(self._valid_section())
        doc_json["sections"].append(self._valid_section())

        with patch("server.insert_documentation", return_value=1):
            result = _add_doc(doc_json=doc_json)

            assert result["sections_indexed"] == 3

    def test_add_doc_handles_empty_sections_list(self):
        """add_doc should handle empty sections list."""
        doc_json = self._valid_doc_json()
        doc_json["sections"] = []

        with patch("server.insert_documentation", return_value=1):
            result = _add_doc(doc_json=doc_json)

            assert result["success"] is True
            assert result["sections_indexed"] == 0

    def test_add_doc_handles_insert_exception(self):
        """add_doc should handle exceptions from insert_documentation."""
        doc_json = self._valid_doc_json()

        with patch("server.insert_documentation", side_effect=Exception("DB error")):
            result = _add_doc(doc_json=doc_json)

            assert result["success"] is False
            assert result["doc_id"] is None
            assert "DB error" in result["message"]
