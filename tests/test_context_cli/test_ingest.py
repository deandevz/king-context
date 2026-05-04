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

    data, discovery = build_user_corpus(
        notes_dir,
        name="custom-bank",
        chunk_min_tokens=1,
    )

    assert discovery.discovered_count == 2
    assert len(discovery.files) == 2
    assert data["name"] == "custom-bank"
    assert len(data["sections"]) >= 3

    titles = {section["title"] for section in data["sections"]}
    assert "Authentication" in titles
    assert "OAuth" in titles
    assert any("Summary" in title for title in titles)
    auth_section = next(section for section in data["sections"] if section["title"] == "Authentication")
    assert auth_section["source_type"] == "user-content"
    assert auth_section["source_format"] == "md"
    assert auth_section["source_collection"] == "custom-bank"
    assert auth_section["source_file"] == "guide.md"


def test_build_user_corpus_marks_research_sections_when_requested(tmp_path):
    transcript = tmp_path / "video-notes.txt"
    transcript.write_text("Line one.\n\nLine two.", encoding="utf-8")

    data, _ = build_user_corpus(transcript, source="research")

    assert data["sections"]
    assert all(section["source_type"] == "research" for section in data["sections"])
    assert all(section["source_kind"] == "text" for section in data["sections"])


def test_build_user_corpus_ignores_hidden_and_binary_files(tmp_path):
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    (notes_dir / "guide.md").write_text("## Intro\n\nVisible content.", encoding="utf-8")
    (notes_dir / ".secret.txt").write_text("ignore me", encoding="utf-8")
    (notes_dir / "diagram.png").write_bytes(b"png")
    (notes_dir / "node_modules").mkdir()
    (notes_dir / "node_modules" / "package.txt").write_text("ignored", encoding="utf-8")

    data, discovery = build_user_corpus(notes_dir)

    assert len(discovery.files) == 1
    assert discovery.discovered_count == 3
    assert discovery.ignored_count == 2
    assert "<hidden>" in discovery.ignored_extensions
    assert ".png" in discovery.ignored_extensions
    assert len(data["sections"]) == 1


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
    section = payload["sections"][0]
    assert section["source_collection"] == "ops-notes"
    indexed_section = json.loads(
        (tmp_path / ".king-context" / "docs" / "ops-notes" / "sections" / section["path"]).with_suffix(".json").read_text(encoding="utf-8")
    )
    assert indexed_section["source_file"] == "notes.txt"
    assert indexed_section["source_format"] == "txt"


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
    assert payload["sections"][0]["source_kind"] == "transcript"
