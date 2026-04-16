"""Tests for context_cli.store module."""

import json

from context_cli.store import doc_exists, get_store_dir, list_docs


def _make_doc(store_dir, name, display_name="Test Doc", version="v1",
              section_count=5, base_url="https://example.com"):
    """Helper to create a doc directory with index.json."""
    doc_dir = store_dir / name
    doc_dir.mkdir(parents=True)
    index = {
        "name": name,
        "display_name": display_name,
        "version": version,
        "section_count": section_count,
        "base_url": base_url,
    }
    (doc_dir / "index.json").write_text(json.dumps(index))
    return doc_dir


def test_get_store_dir_returns_path():
    result = get_store_dir()
    assert result.name == ".king-context"
    assert result.is_absolute()


def test_list_docs_empty_store(tmp_path):
    assert list_docs(tmp_path) == []


def test_list_docs_nonexistent_dir(tmp_path):
    assert list_docs(tmp_path / "nonexistent") == []


def test_list_docs_single_doc(tmp_path):
    _make_doc(tmp_path, "my-api", display_name="My API", section_count=10)
    docs = list_docs(tmp_path)
    assert len(docs) == 1
    assert docs[0].name == "my-api"
    assert docs[0].display_name == "My API"
    assert docs[0].section_count == 10


def test_list_docs_multiple_sorted(tmp_path):
    _make_doc(tmp_path, "zebra-api")
    _make_doc(tmp_path, "alpha-api")
    docs = list_docs(tmp_path)
    assert len(docs) == 2
    assert docs[0].name == "alpha-api"
    assert docs[1].name == "zebra-api"


def test_list_docs_skips_underscore_dirs(tmp_path):
    _make_doc(tmp_path, "real-doc")
    learned = tmp_path / "_learned"
    learned.mkdir()
    (learned / "index.json").write_text('{"name": "_learned"}')
    docs = list_docs(tmp_path)
    assert len(docs) == 1
    assert docs[0].name == "real-doc"


def test_list_docs_skips_dirs_without_index(tmp_path):
    _make_doc(tmp_path, "valid-doc")
    (tmp_path / "no-index").mkdir()
    docs = list_docs(tmp_path)
    assert len(docs) == 1


def test_list_docs_skips_malformed_json(tmp_path):
    _make_doc(tmp_path, "good-doc")
    bad_dir = tmp_path / "bad-doc"
    bad_dir.mkdir()
    (bad_dir / "index.json").write_text("not json")
    docs = list_docs(tmp_path)
    assert len(docs) == 1
    assert docs[0].name == "good-doc"


def test_doc_exists_true(tmp_path):
    _make_doc(tmp_path, "my-api")
    assert doc_exists("my-api", tmp_path) is True


def test_doc_exists_false_no_dir(tmp_path):
    assert doc_exists("nope", tmp_path) is False


def test_doc_exists_false_no_index(tmp_path):
    (tmp_path / "partial").mkdir()
    assert doc_exists("partial", tmp_path) is False
