import json
import logging

import pytest

from king_context.research import export as research_export
from king_context.research.fetch import SourceDoc
from king_context.scraper.enrich import EnrichedChunk


def mk_enriched(url="https://ex.com/a", title="T", path="sec/a"):
    return EnrichedChunk(
        title=title,
        path=path,
        url=url,
        content="hello",
        keywords=["k"] * 5,
        use_cases=["u1", "u2"],
        tags=["t"],
        priority=7,
    )


def mk_source(
    url="https://ex.com/a",
    author=None,
    published_date=None,
    domain="ex.com",
    discovery_iteration=0,
):
    return SourceDoc(
        url=url,
        title="T",
        content="c",
        author=author,
        published_date=published_date,
        domain=domain,
        query="q",
        discovery_iteration=discovery_iteration,
        score=None,
        fetch_path="exa",
    )


@pytest.fixture
def patched_data_dir(tmp_path, monkeypatch):
    target = tmp_path / "research"
    monkeypatch.setattr(research_export, "RESEARCH_DATA_DIR", target)
    return target


def _load_output(path):
    return json.loads(path.read_text())


def test_single_source_single_section(patched_data_dir):
    enriched = [mk_enriched()]
    sources = {"https://ex.com/a": mk_source(author="Alice", domain="ex.com")}

    out = research_export.export_research_to_json(
        enriched, sources, topic_slug="my-topic", topic="My Topic"
    )

    assert out.exists()
    doc = _load_output(out)
    assert doc["name"] == "my-topic"
    assert doc["display_name"] == "My Topic"
    assert len(doc["sections"]) == 1

    section = doc["sections"][0]
    assert section["source_type"] == "research"
    assert section["domain"] == "ex.com"
    assert section["discovery_iteration"] == 0
    assert section["authors"] == ["Alice"]


def test_multiple_chunks_same_url_share_metadata(patched_data_dir):
    url = "https://ex.com/shared"
    enriched = [
        mk_enriched(url=url, title=f"T{i}", path=f"sec/{i}") for i in range(3)
    ]
    sources = {
        url: mk_source(
            url=url,
            author="Alice, Bob",
            published_date="2024-01-01",
            domain="ex.com",
            discovery_iteration=2,
        )
    }

    out = research_export.export_research_to_json(
        enriched, sources, topic_slug="topic", topic="Topic"
    )

    doc = _load_output(out)
    assert len(doc["sections"]) == 3
    for section in doc["sections"]:
        assert section["source_type"] == "research"
        assert section["authors"] == ["Alice", "Bob"]
        assert section["published_date"] == "2024-01-01"
        assert section["domain"] == "ex.com"
        assert section["discovery_iteration"] == 2


def test_missing_author_and_date_omitted(patched_data_dir):
    enriched = [mk_enriched()]
    sources = {
        "https://ex.com/a": mk_source(author=None, published_date=None)
    }

    out = research_export.export_research_to_json(
        enriched, sources, topic_slug="topic", topic="Topic"
    )

    section = _load_output(out)["sections"][0]
    assert "authors" not in section
    assert "published_date" not in section
    assert section["source_type"] == "research"
    assert section["domain"] == "ex.com"
    assert section["discovery_iteration"] == 0


def test_output_file_exists_on_disk(patched_data_dir):
    enriched = [mk_enriched()]
    sources = {"https://ex.com/a": mk_source()}

    out = research_export.export_research_to_json(
        enriched, sources, topic_slug="topic", topic="Topic"
    )

    expected = patched_data_dir / "topic.json"
    assert out == expected
    assert expected.exists()


def test_slug_with_spaces_is_sanitized(patched_data_dir):
    enriched = [mk_enriched()]
    sources = {"https://ex.com/a": mk_source()}

    out = research_export.export_research_to_json(
        enriched,
        sources,
        topic_slug="Prompt Engineering!",
        topic="Prompt Engineering!",
    )

    assert out.name == "prompt-engineering.json"
    doc = _load_output(out)
    assert doc["name"] == "prompt-engineering"


def test_unknown_url_still_gets_source_type(patched_data_dir):
    enriched = [mk_enriched(url="https://unknown.com/x")]
    sources: dict = {}

    out = research_export.export_research_to_json(
        enriched, sources, topic_slug="topic", topic="Topic"
    )

    section = _load_output(out)["sections"][0]
    assert section["source_type"] == "research"
    assert "domain" not in section
    assert "discovery_iteration" not in section
    assert "authors" not in section
    assert "published_date" not in section


def test_overwrite_warns(patched_data_dir, caplog, capsys):
    enriched = [mk_enriched()]
    sources = {"https://ex.com/a": mk_source()}

    research_export.export_research_to_json(
        enriched, sources, topic_slug="topic", topic="Topic"
    )

    with caplog.at_level(logging.WARNING, logger="king_context.research.export"):
        research_export.export_research_to_json(
            enriched, sources, topic_slug="topic", topic="Topic"
        )

    assert any("Overwriting" in rec.message for rec in caplog.records)
    captured = capsys.readouterr()
    assert "Overwriting" in captured.out


def test_auto_index_with_valid_json_populates_store(tmp_path):
    doc_data = {
        "name": "my-topic",
        "display_name": "My Topic",
        "version": "v1",
        "base_url": "",
        "sections": [
            {
                "title": "A",
                "path": "a",
                "url": "https://ex.com/a",
                "keywords": ["k"],
                "use_cases": ["u"],
                "tags": ["t"],
                "priority": 5,
                "content": "hello",
            }
        ],
    }
    json_path = tmp_path / "research.json"
    json_path.write_text(json.dumps(doc_data))
    store_dir = tmp_path / "docs"
    store_dir.mkdir()

    from king_context.research.export import auto_index

    auto_index(json_path, store_dir=store_dir)

    sections_dir = store_dir / "my-topic" / "sections"
    assert sections_dir.exists()
    assert any(sections_dir.iterdir())


def test_auto_index_missing_file_logs_and_does_not_raise(tmp_path, caplog):
    from king_context.research.export import auto_index

    caplog.set_level("WARNING")
    auto_index(tmp_path / "nope.json", store_dir=tmp_path)
    assert any("auto_index failed" in r.message for r in caplog.records)
