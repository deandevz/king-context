"""Tests for context_cli.indexer module."""

import json

from context_cli.indexer import IndexResult, index_all, index_doc


def _make_source_json(path, name="test-api", sections=None):
    """Create a monolithic source JSON file."""
    if sections is None:
        sections = [
            {
                "title": "Getting Started",
                "path": "getting-started",
                "url": "https://example.com/getting-started",
                "keywords": ["setup", "install"],
                "use_cases": ["How to install the SDK"],
                "tags": ["guide"],
                "priority": 10,
                "content": "Install with pip install test-api",
            },
            {
                "title": "Authentication",
                "path": "authentication",
                "url": "https://example.com/auth",
                "keywords": ["auth", "api-key"],
                "use_cases": ["How to authenticate requests"],
                "tags": ["guide", "security"],
                "priority": 8,
                "content": "Use your API key in the header",
            },
        ]
    data = {
        "name": name,
        "display_name": "Test API",
        "version": "v1",
        "base_url": "https://example.com",
        "sections": sections,
    }
    path.write_text(json.dumps(data))
    return path


def test_index_doc_creates_structure(tmp_path):
    src = _make_source_json(tmp_path / "test-api.json")
    store = tmp_path / "store"
    store.mkdir()

    result = index_doc(src, store)

    assert result.doc_name == "test-api"
    assert result.section_count == 2
    assert (store / "test-api" / "index.json").exists()
    assert (store / "test-api" / "sections" / "getting-started.json").exists()
    assert (store / "test-api" / "sections" / "authentication.json").exists()


def test_index_doc_creates_index_json(tmp_path):
    src = _make_source_json(tmp_path / "test-api.json")
    store = tmp_path / "store"
    store.mkdir()

    index_doc(src, store)
    index_data = json.loads((store / "test-api" / "index.json").read_text())

    assert index_data["name"] == "test-api"
    assert index_data["display_name"] == "Test API"
    assert index_data["section_count"] == 2
    assert "indexed_at" in index_data
    # index.json should not contain content
    assert "sections" not in index_data
    assert "content" not in index_data


def test_index_doc_section_files_have_token_estimate(tmp_path):
    src = _make_source_json(tmp_path / "test-api.json")
    store = tmp_path / "store"
    store.mkdir()

    index_doc(src, store)
    section = json.loads(
        (store / "test-api" / "sections" / "getting-started.json").read_text()
    )

    assert "token_estimate" in section
    assert section["token_estimate"] > 0
    assert section["content"] == "Install with pip install test-api"


def test_index_doc_keywords_reverse_index(tmp_path):
    src = _make_source_json(tmp_path / "test-api.json")
    store = tmp_path / "store"
    store.mkdir()

    index_doc(src, store)
    keywords = json.loads((store / "test-api" / "keywords.json").read_text())

    assert "setup" in keywords
    assert "getting-started" in keywords["setup"]
    assert "auth" in keywords
    assert "authentication" in keywords["auth"]


def test_index_doc_use_cases_reverse_index(tmp_path):
    src = _make_source_json(tmp_path / "test-api.json")
    store = tmp_path / "store"
    store.mkdir()

    index_doc(src, store)
    use_cases = json.loads((store / "test-api" / "use_cases.json").read_text())

    assert "How to install the SDK" in use_cases
    assert "getting-started" in use_cases["How to install the SDK"]


def test_index_doc_tags_reverse_index(tmp_path):
    src = _make_source_json(tmp_path / "test-api.json")
    store = tmp_path / "store"
    store.mkdir()

    index_doc(src, store)
    tags = json.loads((store / "test-api" / "tags.json").read_text())

    assert "guide" in tags
    assert "getting-started" in tags["guide"]
    assert "authentication" in tags["guide"]
    assert "security" in tags
    assert "authentication" in tags["security"]


def test_index_doc_reindex_overwrites(tmp_path):
    src = _make_source_json(tmp_path / "test-api.json")
    store = tmp_path / "store"
    store.mkdir()

    # First index
    index_doc(src, store)
    # Create a stale file that should be removed on re-index
    (store / "test-api" / "sections" / "stale-section.json").write_text("{}")

    # Re-index
    index_doc(src, store)
    assert not (store / "test-api" / "sections" / "stale-section.json").exists()
    assert (store / "test-api" / "sections" / "getting-started.json").exists()


def test_index_doc_empty_sections(tmp_path):
    src = _make_source_json(tmp_path / "test-api.json", sections=[])
    store = tmp_path / "store"
    store.mkdir()

    result = index_doc(src, store)

    assert result.section_count == 0
    assert (store / "test-api" / "index.json").exists()
    keywords = json.loads((store / "test-api" / "keywords.json").read_text())
    assert keywords == {}


def test_index_all(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _make_source_json(data_dir / "api-one.json", name="api-one")
    _make_source_json(data_dir / "api-two.json", name="api-two")

    store = tmp_path / "store"
    store.mkdir()

    results = index_all(data_dir, store)

    assert len(results) == 2
    assert results[0].doc_name == "api-one"
    assert results[1].doc_name == "api-two"
    assert (store / "api-one" / "index.json").exists()
    assert (store / "api-two" / "index.json").exists()


def test_index_all_empty_dir(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    store = tmp_path / "store"
    store.mkdir()

    results = index_all(data_dir, store)
    assert results == []
