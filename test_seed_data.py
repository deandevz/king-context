"""Tests for seed_data module."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, call

import pytest

from seed_data import seed_all, seed_one, DATA_DIR


class TestSeedAll:
    """Tests for seed_all function."""

    def test_seed_all_reads_json_files_and_calls_insert_documentation(self, tmp_path):
        """seed_all should read all .json files from DATA_DIR and call insert_documentation."""
        # Create test data files
        doc1 = {
            "name": "test-doc-1",
            "display_name": "Test Doc 1",
            "version": "v1",
            "base_url": "https://example.com/1",
            "sections": [
                {"title": "Section 1", "path": "s1", "url": "https://example.com/1/s1"}
            ]
        }
        doc2 = {
            "name": "test-doc-2",
            "display_name": "Test Doc 2",
            "version": "v2",
            "base_url": "https://example.com/2",
            "sections": [
                {"title": "Section A", "path": "a", "url": "https://example.com/2/a"},
                {"title": "Section B", "path": "b", "url": "https://example.com/2/b"}
            ]
        }

        # Write test files
        (tmp_path / "doc1.json").write_text(json.dumps(doc1))
        (tmp_path / "doc2.json").write_text(json.dumps(doc2))

        with patch("seed_data.DATA_DIR", tmp_path), \
             patch("seed_data.insert_documentation") as mock_insert:
            mock_insert.return_value = 1  # Mock return value (number of sections)

            seed_all()

            # Verify insert_documentation was called for each file
            assert mock_insert.call_count == 2
            # Verify the data passed
            calls = mock_insert.call_args_list
            call_args = [c[0][0] for c in calls]
            assert doc1 in call_args
            assert doc2 in call_args

    def test_seed_all_prints_progress(self, tmp_path, capsys):
        """seed_all should print progress for each file."""
        doc = {
            "name": "progress-test",
            "display_name": "Progress Test",
            "version": "v1",
            "base_url": "https://example.com",
            "sections": [
                {"title": "S1", "path": "s1", "url": "https://example.com/s1"},
                {"title": "S2", "path": "s2", "url": "https://example.com/s2"},
                {"title": "S3", "path": "s3", "url": "https://example.com/s3"}
            ]
        }

        (tmp_path / "progress.json").write_text(json.dumps(doc))

        with patch("seed_data.DATA_DIR", tmp_path), \
             patch("seed_data.insert_documentation") as mock_insert:
            mock_insert.return_value = 3  # 3 sections

            seed_all()

            captured = capsys.readouterr()
            assert "Seeding progress.json... done (3 sections)" in captured.out

    def test_seed_all_handles_empty_directory(self, tmp_path, capsys):
        """seed_all should handle empty data directory gracefully."""
        with patch("seed_data.DATA_DIR", tmp_path), \
             patch("seed_data.insert_documentation") as mock_insert:

            # Should not raise any exception
            seed_all()

            # insert_documentation should not be called
            mock_insert.assert_not_called()

    def test_seed_all_ignores_non_json_files(self, tmp_path):
        """seed_all should only process .json files."""
        doc = {
            "name": "json-test",
            "display_name": "JSON Test",
            "version": "v1",
            "base_url": "https://example.com",
            "sections": []
        }

        # Create various files
        (tmp_path / "valid.json").write_text(json.dumps(doc))
        (tmp_path / "readme.md").write_text("# README")
        (tmp_path / "config.txt").write_text("some config")
        (tmp_path / "data.json.bak").write_text("{}")

        with patch("seed_data.DATA_DIR", tmp_path), \
             patch("seed_data.insert_documentation") as mock_insert:
            mock_insert.return_value = 0

            seed_all()

            # Only the .json file should be processed
            assert mock_insert.call_count == 1
            mock_insert.assert_called_once_with(doc)


class TestSeedOne:
    """Tests for seed_one function."""

    def test_seed_one_reads_json_file_and_calls_insert_documentation(self, tmp_path):
        """seed_one should read the specified JSON file and call insert_documentation."""
        doc = {
            "name": "single-doc",
            "display_name": "Single Doc",
            "version": "v1",
            "base_url": "https://example.com",
            "sections": [
                {"title": "Section 1", "path": "s1", "url": "https://example.com/s1"},
                {"title": "Section 2", "path": "s2", "url": "https://example.com/s2"}
            ]
        }

        json_file = tmp_path / "single.json"
        json_file.write_text(json.dumps(doc))

        with patch("seed_data.insert_documentation") as mock_insert:
            mock_insert.return_value = 2

            seed_one(json_file)

            mock_insert.assert_called_once_with(doc)

    def test_seed_one_prints_progress(self, tmp_path, capsys):
        """seed_one should print progress with filename and section count."""
        doc = {
            "name": "progress-test",
            "display_name": "Progress Test",
            "version": "v1",
            "base_url": "https://example.com",
            "sections": [
                {"title": "S1", "path": "s1", "url": "https://example.com/s1"},
                {"title": "S2", "path": "s2", "url": "https://example.com/s2"},
                {"title": "S3", "path": "s3", "url": "https://example.com/s3"},
                {"title": "S4", "path": "s4", "url": "https://example.com/s4"}
            ]
        }

        json_file = tmp_path / "test_progress.json"
        json_file.write_text(json.dumps(doc))

        with patch("seed_data.insert_documentation") as mock_insert:
            mock_insert.return_value = 4

            seed_one(json_file)

            captured = capsys.readouterr()
            assert "Seeding test_progress.json... done (4 sections)" in captured.out

    def test_seed_one_handles_doc_with_no_sections(self, tmp_path, capsys):
        """seed_one should handle documents with no sections."""
        doc = {
            "name": "empty-sections",
            "display_name": "Empty Sections Doc",
            "version": "v1",
            "base_url": "https://example.com",
            "sections": []
        }

        json_file = tmp_path / "empty.json"
        json_file.write_text(json.dumps(doc))

        with patch("seed_data.insert_documentation") as mock_insert:
            mock_insert.return_value = 0

            seed_one(json_file)

            captured = capsys.readouterr()
            assert "Seeding empty.json... done (0 sections)" in captured.out
            mock_insert.assert_called_once_with(doc)

    def test_seed_one_handles_doc_without_sections_key(self, tmp_path, capsys):
        """seed_one should handle documents missing the sections key."""
        doc = {
            "name": "no-sections-key",
            "display_name": "No Sections Key Doc",
            "version": "v1",
            "base_url": "https://example.com"
        }

        json_file = tmp_path / "nosections.json"
        json_file.write_text(json.dumps(doc))

        with patch("seed_data.insert_documentation") as mock_insert:
            mock_insert.return_value = 0

            seed_one(json_file)

            captured = capsys.readouterr()
            assert "Seeding nosections.json... done (0 sections)" in captured.out
            mock_insert.assert_called_once_with(doc)
