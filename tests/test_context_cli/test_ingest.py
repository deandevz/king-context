"""Tests for local Markdown ingestion."""

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace

from context_cli.ingest import build_user_corpus, ingest_path


@dataclass
class FakeEnrichedChunk:
    title: str
    path: str
    url: str
    content: str
    keywords: list[str]
    use_cases: list[str]
    tags: list[str]
    priority: int


async def _fake_enrich(chunks, config, output_dir=None):
    return [
        FakeEnrichedChunk(
            title=chunk.title,
            path=chunk.path,
            url=chunk.source_url,
            content=chunk.content,
            keywords=["authentication", "oauth", "sessions", "api", "guide"],
            use_cases=["Use when authenticating requests", "Configure when enabling OAuth"],
            tags=["authentication"],
            priority=7,
        )
        for chunk in chunks
    ]


def test_build_user_corpus_uses_enrichment_pipeline_for_markdown(monkeypatch, tmp_path):
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    (notes_dir / "agent-memory.md").write_text(
        "# Agent Memory\n\nUse this note to explain retrieval and memory flows.\n",
        encoding="utf-8",
    )

    import context_cli.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "_enrich_markdown_chunks", lambda chunks: asyncio.run(_fake_enrich(chunks, None)))

    data, discovery = build_user_corpus(notes_dir, name="custom-bank")

    assert discovery.discovered_count == 1
    assert len(discovery.files) == 1
    assert data["name"] == "custom-bank"
    assert len(data["sections"]) == 1

    section = data["sections"][0]
    assert section["title"] == "Agent Memory"
    assert section["path"] == "agent-memory"
    assert section["source_type"] == "user-content"
    assert section["source_file"] == "agent-memory.md"
    assert section["keywords"] == ["authentication", "oauth", "sessions", "api", "guide"]
    assert "retrieval and memory flows" in section["content"]


def test_build_user_corpus_marks_research_sections_when_requested(monkeypatch, tmp_path):
    note = tmp_path / "research-note.md"
    note.write_text("# Research Note\n\nTrack findings here.\n", encoding="utf-8")

    import context_cli.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "_enrich_markdown_chunks", lambda chunks: asyncio.run(_fake_enrich(chunks, None)))

    data, _ = build_user_corpus(note, source="research")

    assert data["sections"]
    assert all(section["source_type"] == "research" for section in data["sections"])


def test_build_user_corpus_keeps_one_section_per_markdown_file(monkeypatch, tmp_path):
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    (notes_dir / "deep-dive.md").write_text(
        "# Deep Dive\n\n## Part One\n\nAlpha.\n\n### Part Two\n\nBeta.\n",
        encoding="utf-8",
    )

    import context_cli.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "_enrich_markdown_chunks", lambda chunks: asyncio.run(_fake_enrich(chunks, None)))

    data, _ = build_user_corpus(notes_dir)

    assert len(data["sections"]) == 1
    assert "## Part One" in data["sections"][0]["content"]
    assert "### Part Two" in data["sections"][0]["content"]


def test_build_user_corpus_ignores_hidden_and_non_markdown_files(monkeypatch, tmp_path):
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    (notes_dir / "guide.md").write_text("# Intro\n\nVisible content.", encoding="utf-8")
    (notes_dir / ".secret.md").write_text("# Secret\n\nignore me", encoding="utf-8")
    (notes_dir / "summary.txt").write_text("ignored", encoding="utf-8")
    (notes_dir / "node_modules").mkdir()
    (notes_dir / "node_modules" / "package.md").write_text("# Ignored\n\nNope", encoding="utf-8")

    import context_cli.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "_enrich_markdown_chunks", lambda chunks: asyncio.run(_fake_enrich(chunks, None)))

    data, discovery = build_user_corpus(notes_dir)

    assert len(discovery.files) == 1
    assert discovery.discovered_count == 3
    assert discovery.ignored_count == 2
    assert "<hidden>" in discovery.ignored_extensions
    assert ".txt" in discovery.ignored_extensions
    assert len(data["sections"]) == 1


def test_ingest_path_writes_json_and_indexes_docs_store(monkeypatch, tmp_path):
    src_dir = tmp_path / "dropbox"
    src_dir.mkdir()
    (src_dir / "notes.md").write_text("# Ops Notes\n\nOperational runbook for the service.", encoding="utf-8")

    import context_cli.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "_enrich_markdown_chunks", lambda chunks: asyncio.run(_fake_enrich(chunks, None)))

    result = ingest_path(
        src_dir,
        name="ops-notes",
        project_root=tmp_path,
        store_dir=tmp_path / ".king-context" / "docs",
        research_store_dir=tmp_path / ".king-context" / "research",
    )

    assert result.doc_name == "ops-notes"
    assert result.indexed is True
    assert result.store_label == "docs"
    assert result.json_path.exists()
    assert (tmp_path / ".king-context" / "docs" / "ops-notes" / "index.json").exists()

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["name"] == "ops-notes"
    section = payload["sections"][0]
    assert section["source_file"] == "notes.md"
    indexed_section = json.loads(
        (tmp_path / ".king-context" / "docs" / "ops-notes" / "sections" / section["path"]).with_suffix(".json").read_text(encoding="utf-8")
    )
    assert indexed_section["source_file"] == "notes.md"
    assert indexed_section["source_type"] == "user-content"
    assert "source_format" not in indexed_section
    assert "source_collection" not in indexed_section
    assert "source_kind" not in indexed_section


def test_build_user_corpus_fails_when_enrichment_returns_partial_results(monkeypatch, tmp_path):
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    (notes_dir / "a.md").write_text("# A\n\nOne", encoding="utf-8")
    (notes_dir / "b.md").write_text("# B\n\nTwo", encoding="utf-8")

    import context_cli.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "_enrich_markdown_chunks", lambda chunks: asyncio.run(_fake_enrich(chunks[:1], None)))

    try:
        build_user_corpus(notes_dir)
    except RuntimeError as exc:
        assert "Failed to enrich one or more Markdown files" in str(exc)
    else:
        raise AssertionError("Expected partial enrichment mismatch error")


def test_ingest_path_requires_openrouter_key(monkeypatch, tmp_path):
    note = tmp_path / "notes.md"
    note.write_text("# Notes\n\nBody", encoding="utf-8")

    import context_cli.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "load_config", lambda: SimpleNamespace(openrouter_api_key=""))

    try:
        ingest_mod._enrich_markdown_chunks([])
    except RuntimeError as exc:
        assert "OPENROUTER_API_KEY" in str(exc)
    else:
        raise AssertionError("Expected OPENROUTER_API_KEY error")
