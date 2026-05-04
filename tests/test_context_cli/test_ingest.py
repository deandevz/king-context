"""Tests for local user-content ingestion."""

import json

from context_cli.ingest import build_user_corpus, ingest_path


def test_build_user_corpus_supports_markdown_directory(tmp_path):
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    (notes_dir / "guide.md").write_text(
        "## Authentication\n\nUse an API key.\n\n### OAuth\n\nUse OAuth for user sessions.\n",
        encoding="utf-8",
    )
    (notes_dir / "summary.txt").write_text(
        "This is a plain text summary of the system behavior.",
        encoding="utf-8",
    )

    data, file_count = build_user_corpus(
        notes_dir,
        name="custom-bank",
        chunk_min_tokens=1,
    )

    assert file_count == 2
    assert data["name"] == "custom-bank"
    assert len(data["sections"]) >= 3

    titles = {section["title"] for section in data["sections"]}
    assert "Authentication" in titles
    assert "OAuth" in titles
    assert any("Summary" in title for title in titles)


def test_build_user_corpus_marks_research_sections_when_requested(tmp_path):
    transcript = tmp_path / "video-notes.txt"
    transcript.write_text("Line one.\n\nLine two.", encoding="utf-8")

    data, _ = build_user_corpus(transcript, source="research")

    assert data["sections"]
    assert all(section["source_type"] == "research" for section in data["sections"])


def test_ingest_path_writes_json_and_indexes_docs_store(tmp_path, monkeypatch):
    src_dir = tmp_path / "dropbox"
    src_dir.mkdir()
    (src_dir / "notes.txt").write_text("Operational runbook for the service.", encoding="utf-8")

    import context_cli.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ingest_mod, "STORE_DIR", tmp_path / ".king-context" / "docs")
    monkeypatch.setattr(ingest_mod, "RESEARCH_STORE_DIR", tmp_path / ".king-context" / "research")

    result = ingest_path(src_dir, name="ops-notes")

    assert result.doc_name == "ops-notes"
    assert result.indexed is True
    assert result.store_label == "docs"
    assert result.json_path.exists()
    assert (tmp_path / ".king-context" / "docs" / "ops-notes" / "index.json").exists()

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["name"] == "ops-notes"


def test_ingest_path_writes_research_json_when_requested(tmp_path, monkeypatch):
    transcript = tmp_path / "youtube.vtt"
    transcript.write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nHello world", encoding="utf-8")

    import context_cli.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ingest_mod, "STORE_DIR", tmp_path / ".king-context" / "docs")
    monkeypatch.setattr(ingest_mod, "RESEARCH_STORE_DIR", tmp_path / ".king-context" / "research")

    result = ingest_path(transcript, source="research", auto_index=False)

    assert result.store_label == "research"
    assert result.indexed is False
    assert result.json_path.parent.name == "research"
    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["sections"][0]["source_type"] == "research"
