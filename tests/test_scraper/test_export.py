import json
from pathlib import Path
from unittest.mock import patch

from king_context.scraper.enrich import EnrichedChunk
from king_context.scraper.export import export_to_json, save_and_index


def make_enriched_chunk(**kwargs) -> EnrichedChunk:
    defaults = dict(
        title="Test Section",
        path="/docs/test-section",
        url="https://docs.example.com/test",
        content="Test content here.",
        keywords=["kw1", "kw2", "kw3", "kw4", "kw5"],
        use_cases=["Use when testing", "Configure when needed"],
        tags=["testing"],
        priority=5,
    )
    defaults.update(kwargs)
    return EnrichedChunk(**defaults)


def test_export_to_json_schema():
    chunks = [make_enriched_chunk()]
    result = export_to_json(chunks, "example", "Example Docs", "https://docs.example.com")

    assert result["name"] == "example"
    assert result["display_name"] == "Example Docs"
    assert result["version"] == "v1"
    assert result["base_url"] == "https://docs.example.com"
    assert "sections" in result
    assert isinstance(result["sections"], list)


def test_export_to_json_custom_version():
    chunks = [make_enriched_chunk()]
    result = export_to_json(chunks, "example", "Example", "https://example.com", version="v2")
    assert result["version"] == "v2"


def test_export_section_fields():
    chunk = make_enriched_chunk()
    result = export_to_json([chunk], "example", "Example", "https://example.com")

    assert len(result["sections"]) == 1
    section = result["sections"][0]

    for field in ["title", "path", "url", "keywords", "use_cases", "tags", "priority", "content"]:
        assert field in section, f"Missing field: {field}"

    assert section["title"] == chunk.title
    assert section["path"] == "docs-test-section"  # sanitized: /docs/test-section → docs-test-section
    assert section["url"] == chunk.url
    assert section["keywords"] == chunk.keywords
    assert section["use_cases"] == chunk.use_cases
    assert section["tags"] == chunk.tags
    assert section["priority"] == chunk.priority
    assert section["content"] == chunk.content


def test_export_multiple_chunks():
    chunks = [make_enriched_chunk(title=f"Section {i}") for i in range(5)]
    result = export_to_json(chunks, "example", "Example", "https://example.com")
    assert len(result["sections"]) == 5


def test_export_empty_chunks():
    result = export_to_json([], "example", "Example", "https://example.com")
    assert result["sections"] == []


def test_save_and_index_calls_seed_one(tmp_path):
    doc_data = {"name": "test", "display_name": "Test", "version": "v1", "sections": []}
    output_path = tmp_path / "test.json"

    with patch("king_context.seed_data.seed_one") as mock_seed:
        save_and_index(doc_data, output_path, auto_seed=True)
        mock_seed.assert_called_once_with(output_path)

    assert output_path.exists()
    saved = json.loads(output_path.read_text())
    assert saved["name"] == "test"


def test_save_and_index_no_auto_seed(tmp_path):
    doc_data = {"name": "test", "sections": []}
    output_path = tmp_path / "test.json"

    with patch("king_context.seed_data.seed_one") as mock_seed:
        save_and_index(doc_data, output_path, auto_seed=False)

    mock_seed.assert_not_called()
    assert output_path.exists()


def test_save_and_index_creates_parent_dirs(tmp_path):
    doc_data = {"name": "test", "sections": []}
    output_path = tmp_path / "nested" / "dir" / "test.json"

    with patch("king_context.seed_data.seed_one"):
        save_and_index(doc_data, output_path, auto_seed=True)

    assert output_path.exists()


def test_export_section_carries_content_hash():
    chunk = make_enriched_chunk()
    result = export_to_json([chunk], "example", "Example", "https://example.com")
    section = result["sections"][0]
    assert "_meta" in section
    assert section["_meta"]["content_hash"] == chunk.content_hash
    assert len(section["_meta"]["content_hash"]) == 64


def test_export_top_level_meta():
    result = export_to_json(
        [make_enriched_chunk()],
        "example",
        "Example",
        "https://docs.example.com",
    )
    meta = result["_meta"]
    assert meta["schema_version"] == 1
    assert meta["source_url"] == "https://docs.example.com"
    assert meta["section_count"] == 1
    assert "scraped_at" in meta
    assert "scraper_version" in meta
