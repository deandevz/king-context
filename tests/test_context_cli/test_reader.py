"""Tests for context_cli.reader module."""

import json

import pytest

from context_cli.reader import SectionContent, read_section, suggest_similar


def _make_section(store_dir, doc_name, section_path, title="Test Section",
                  content="Some content here.", url="https://example.com/s",
                  keywords=None, use_cases=None, tags=None, priority=5):
    """Helper to create a doc structure with a single section file."""
    sections_dir = store_dir / doc_name / "sections"
    sections_dir.mkdir(parents=True, exist_ok=True)

    token_estimate = int(len(content.split()) * 1.33)
    data = {
        "title": title,
        "path": section_path,
        "url": url,
        "keywords": keywords or [],
        "use_cases": use_cases or [],
        "tags": tags or [],
        "priority": priority,
        "content": content,
        "token_estimate": token_estimate,
    }
    (sections_dir / f"{section_path}.json").write_text(json.dumps(data))
    return sections_dir / f"{section_path}.json"


# --- Full read ---

def test_full_read_returns_complete_content(tmp_path):
    content = "This is the full content of the section."
    _make_section(tmp_path, "my-api", "getting-started", content=content)

    result = read_section("my-api", "getting-started", tmp_path)

    assert isinstance(result, SectionContent)
    assert result.content == content
    assert result.title == "Test Section"
    assert result.url == "https://example.com/s"
    assert result.is_preview is False
    assert result.token_estimate == int(len(content.split()) * 1.33)


# --- Preview mode ---

def test_preview_mode_truncates_long_content(tmp_path):
    # Build content with 300 words (well over the 150-word preview limit).
    words = [f"word{i}" for i in range(300)]
    long_content = " ".join(words)
    _make_section(tmp_path, "my-api", "long-section", content=long_content)

    result = read_section("my-api", "long-section", tmp_path, preview=True)

    assert result.is_preview is True
    # Preview should contain only the first 150 words.
    assert result.content == " ".join(words[:150])


def test_preview_includes_full_token_estimate(tmp_path):
    words = [f"word{i}" for i in range(300)]
    long_content = " ".join(words)
    full_estimate = int(len(long_content.split()) * 1.33)
    _make_section(tmp_path, "my-api", "long-section", content=long_content)

    result = read_section("my-api", "long-section", tmp_path, preview=True)

    # token_estimate reflects the *full* content, not the truncated preview.
    assert result.token_estimate == full_estimate


def test_preview_short_content_not_truncated(tmp_path):
    short = "A few words only."
    _make_section(tmp_path, "my-api", "short", content=short)

    result = read_section("my-api", "short", tmp_path, preview=True)

    assert result.content == short
    assert result.is_preview is False


# --- Section not found ---

def test_section_not_found_raises(tmp_path):
    # Create doc dir with one section so suggestions can be generated.
    _make_section(tmp_path, "my-api", "getting-started")

    with pytest.raises(FileNotFoundError, match="not found in 'my-api'"):
        read_section("my-api", "nonexistent-section", tmp_path)


def test_section_not_found_includes_suggestions(tmp_path):
    _make_section(tmp_path, "my-api", "getting-started")

    with pytest.raises(FileNotFoundError, match="getting-started"):
        read_section("my-api", "getting", tmp_path)


# --- suggest_similar ---

def test_suggest_similar_returns_matching_paths(tmp_path):
    _make_section(tmp_path, "my-api", "getting-started")
    _make_section(tmp_path, "my-api", "getting-advanced")
    _make_section(tmp_path, "my-api", "auth-setup")
    _make_section(tmp_path, "my-api", "configuration")

    results = suggest_similar("my-api", "getting", tmp_path)

    assert "getting-started" in results
    assert "getting-advanced" in results
    # "auth-setup" and "configuration" should not match "getting"
    assert "auth-setup" not in results
    assert "configuration" not in results


def test_suggest_similar_max_five(tmp_path):
    for i in range(10):
        _make_section(tmp_path, "my-api", f"setup-{i}")

    results = suggest_similar("my-api", "setup", tmp_path)

    assert len(results) <= 5


def test_suggest_similar_no_sections_dir(tmp_path):
    results = suggest_similar("nonexistent", "anything", tmp_path)
    assert results == []


# --- Edge case: empty content ---

def test_empty_content(tmp_path):
    _make_section(tmp_path, "my-api", "empty-section", content="")

    result = read_section("my-api", "empty-section", tmp_path)

    assert result.content == ""
    assert result.is_preview is False
    assert result.token_estimate == 0
