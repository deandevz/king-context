"""
Tests for _load_embeddings function in server.py.
"""

import pytest
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import numpy as np

import db


class TestLoadEmbeddings:
    """Tests for the _load_embeddings startup function."""

    def setup_method(self):
        """Reset db module state before each test."""
        db._embedding_model = None
        db._embeddings = None
        db._section_id_to_idx = {}

    def teardown_method(self):
        """Reset db module state after each test to avoid test pollution."""
        db._embedding_model = None
        db._embeddings = None
        db._section_id_to_idx = {}

    def test_load_embeddings_sets_embedding_model(self):
        """_load_embeddings should set db._embedding_model when model loads successfully."""
        from server import _load_embeddings

        # Mock SentenceTransformer to avoid slow loading
        mock_model = MagicMock()
        with patch("server.SentenceTransformer", return_value=mock_model):
            with patch("server.EMBEDDINGS_PATH") as mock_emb_path:
                with patch("server.SECTION_MAPPING_PATH") as mock_map_path:
                    # Make files appear to exist
                    mock_emb_path.exists.return_value = False
                    mock_map_path.exists.return_value = False

                    _load_embeddings()

        # Model should be set in db module
        assert db._embedding_model is mock_model

    def test_load_embeddings_loads_embeddings_when_file_exists(self):
        """_load_embeddings should load embeddings.npy into db._embeddings when file exists."""
        from server import _load_embeddings

        mock_model = MagicMock()
        test_embeddings = np.array([[0.1, 0.2], [0.3, 0.4]])

        with patch("server.SentenceTransformer", return_value=mock_model):
            with patch("server.EMBEDDINGS_PATH") as mock_emb_path:
                with patch("server.SECTION_MAPPING_PATH") as mock_map_path:
                    mock_emb_path.exists.return_value = True
                    mock_map_path.exists.return_value = False

                    with patch("numpy.load", return_value=test_embeddings):
                        _load_embeddings()

        # Embeddings should be loaded into db module
        assert db._embeddings is not None
        np.testing.assert_array_equal(db._embeddings, test_embeddings)

    def test_load_embeddings_loads_section_mapping_when_file_exists(self):
        """_load_embeddings should load section_mapping.json into db._section_id_to_idx."""
        from server import _load_embeddings

        mock_model = MagicMock()
        test_mapping = {"1": 0, "2": 1, "3": 2}

        with patch("server.SentenceTransformer", return_value=mock_model):
            with patch("server.EMBEDDINGS_PATH") as mock_emb_path:
                with patch("server.SECTION_MAPPING_PATH") as mock_map_path:
                    mock_emb_path.exists.return_value = False
                    mock_map_path.exists.return_value = True

                    mock_file = MagicMock()
                    mock_file.__enter__ = MagicMock(return_value=mock_file)
                    mock_file.__exit__ = MagicMock(return_value=False)

                    with patch("builtins.open", return_value=mock_file):
                        with patch("json.load", return_value=test_mapping):
                            _load_embeddings()

        # Section mapping should be loaded with int keys
        assert db._section_id_to_idx == {1: 0, 2: 1, 3: 2}

    def test_load_embeddings_handles_missing_files_gracefully(self):
        """_load_embeddings should not crash when embedding files are missing."""
        from server import _load_embeddings

        mock_model = MagicMock()

        with patch("server.SentenceTransformer", return_value=mock_model):
            with patch("server.EMBEDDINGS_PATH") as mock_emb_path:
                with patch("server.SECTION_MAPPING_PATH") as mock_map_path:
                    # Files do not exist
                    mock_emb_path.exists.return_value = False
                    mock_map_path.exists.return_value = False

                    # Should not raise
                    _load_embeddings()

        # Model should still be set even without files
        assert db._embedding_model is mock_model
        # Embeddings should remain None
        assert db._embeddings is None
        # Mapping should remain empty
        assert db._section_id_to_idx == {}

    def test_load_embeddings_handles_corrupt_files_gracefully(self):
        """_load_embeddings should handle corrupt files without crashing."""
        from server import _load_embeddings

        mock_model = MagicMock()

        with patch("server.SentenceTransformer", return_value=mock_model):
            with patch("server.EMBEDDINGS_PATH") as mock_emb_path:
                with patch("server.SECTION_MAPPING_PATH") as mock_map_path:
                    mock_emb_path.exists.return_value = True
                    mock_map_path.exists.return_value = True

                    # Simulate corrupt file by raising exception
                    with patch("numpy.load", side_effect=Exception("Corrupt file")):
                        with patch("builtins.open", side_effect=Exception("Corrupt JSON")):
                            # Should not raise
                            _load_embeddings()

        # Model should still be set
        assert db._embedding_model is mock_model

    def test_load_embeddings_startup_time_reasonable(self):
        """_load_embeddings should complete within reasonable time when mocked."""
        from server import _load_embeddings

        mock_model = MagicMock()

        with patch("server.SentenceTransformer", return_value=mock_model):
            with patch("server.EMBEDDINGS_PATH") as mock_emb_path:
                with patch("server.SECTION_MAPPING_PATH") as mock_map_path:
                    mock_emb_path.exists.return_value = False
                    mock_map_path.exists.return_value = False

                    start = time.perf_counter()
                    _load_embeddings()
                    elapsed = time.perf_counter() - start

        # With mocks, should be very fast (under 100ms)
        assert elapsed < 0.1, f"_load_embeddings took {elapsed:.3f}s (expected <0.1s)"
