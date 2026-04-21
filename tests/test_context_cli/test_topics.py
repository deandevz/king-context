"""Tests for the topics subcommand in context_cli.cli."""

import json
import sys

import pytest


def _build_doc(store_dir, doc_name="test-api"):
    """Create a .king-context/<doc>/ structure with tags.json and section files.

    Returns the doc directory path.
    """
    doc_dir = store_dir / doc_name
    sections_dir = doc_dir / "sections"
    sections_dir.mkdir(parents=True)

    # index.json so doc_exists() returns True
    index_meta = {
        "name": doc_name,
        "display_name": "Test API",
        "version": "v1",
        "base_url": "https://example.com",
        "section_count": 3,
    }
    (doc_dir / "index.json").write_text(json.dumps(index_meta))

    # Section files
    sections = [
        {
            "title": "Getting Started",
            "path": "getting-started",
            "url": "https://example.com/getting-started",
            "keywords": ["setup", "install"],
            "use_cases": ["How to install the SDK"],
            "tags": ["guide"],
            "priority": 10,
            "content": "Install with pip.",
            "token_estimate": 5,
        },
        {
            "title": "Authentication",
            "path": "authentication",
            "url": "https://example.com/auth",
            "keywords": ["auth", "api-key"],
            "use_cases": ["How to authenticate"],
            "tags": ["guide", "security"],
            "priority": 8,
            "content": "Use your API key.",
            "token_estimate": 6,
        },
        {
            "title": "Rate Limits",
            "path": "rate-limits",
            "url": "https://example.com/rate-limits",
            "keywords": ["limits", "throttle"],
            "use_cases": ["Handle rate limits"],
            "tags": ["security"],
            "priority": 5,
            "content": "Rate limit is 100 req/s.",
            "token_estimate": 7,
        },
    ]

    for sec in sections:
        (sections_dir / f"{sec['path']}.json").write_text(json.dumps(sec))

    # tags.json — reverse index: tag -> [section paths]
    tags_index = {
        "guide": ["getting-started", "authentication"],
        "security": ["authentication", "rate-limits"],
    }
    (doc_dir / "tags.json").write_text(json.dumps(tags_index))

    return doc_dir


@pytest.fixture
def store_with_topics(tmp_path, monkeypatch):
    """Create a store with one doc and patch STORE_DIR."""
    store_dir = tmp_path / ".king-context" / "docs"
    store_dir.mkdir(parents=True)
    _build_doc(store_dir)

    import context_cli.cli as cli_mod
    monkeypatch.setattr(cli_mod, "STORE_DIR", store_dir)

    return store_dir


def _run_cli(args, monkeypatch):
    """Run CLI by patching sys.argv and calling main()."""
    from context_cli.cli import main
    monkeypatch.setattr(sys, "argv", ["kctx"] + args)
    main()


def test_topics_all_tags_shown(store_with_topics, monkeypatch, capsys):
    """All tags are shown with their section counts."""
    _run_cli(["topics", "test-api"], monkeypatch)
    out = capsys.readouterr().out

    assert "## guide (2 sections)" in out
    assert "## security (2 sections)" in out
    # Sections should appear under their tags
    assert "Getting Started" in out
    assert "Authentication" in out
    assert "Rate Limits" in out


def test_topics_sections_sorted_by_priority(store_with_topics, monkeypatch, capsys):
    """Sections within each tag are sorted by priority descending."""
    _run_cli(["topics", "test-api"], monkeypatch)
    out = capsys.readouterr().out

    # Under "guide": Getting Started (priority 10) should come before Authentication (priority 8)
    guide_start = out.index("## guide")
    gs_pos = out.index("Getting Started", guide_start)
    auth_pos = out.index("Authentication", guide_start)
    assert gs_pos < auth_pos

    # Under "security": Authentication (priority 8) should come before Rate Limits (priority 5)
    sec_start = out.index("## security")
    auth_pos2 = out.index("Authentication", sec_start)
    rl_pos = out.index("Rate Limits", sec_start)
    assert auth_pos2 < rl_pos


def test_topics_filter_by_tag(store_with_topics, monkeypatch, capsys):
    """Filtering by --tag shows only that tag's sections."""
    _run_cli(["topics", "test-api", "--tag", "security"], monkeypatch)
    out = capsys.readouterr().out

    assert "## security" in out
    assert "Authentication" in out
    assert "Rate Limits" in out
    # "guide" tag should NOT appear
    assert "## guide" not in out


def test_topics_json_output(store_with_topics, monkeypatch, capsys):
    """JSON output returns a dict of tag -> list of section dicts."""
    _run_cli(["topics", "test-api", "--json"], monkeypatch)
    out = capsys.readouterr().out
    data = json.loads(out)

    assert isinstance(data, dict)
    assert "guide" in data
    assert "security" in data
    assert len(data["guide"]) == 2
    assert len(data["security"]) == 2

    # Each entry has title, path, priority
    entry = data["guide"][0]
    assert "title" in entry
    assert "path" in entry
    assert "priority" in entry


def test_topics_doc_not_found(tmp_path, monkeypatch, capsys):
    """When the doc does not exist, an error message with available docs is shown."""
    store_dir = tmp_path / ".king-context" / "docs"
    store_dir.mkdir(parents=True)

    # Create a different doc so the error can list available docs
    _build_doc(store_dir, doc_name="other-api")

    import context_cli.cli as cli_mod
    monkeypatch.setattr(cli_mod, "STORE_DIR", store_dir)

    with pytest.raises(SystemExit):
        _run_cli(["topics", "nonexistent-api"], monkeypatch)

    err = capsys.readouterr().err
    assert "nonexistent-api" in err or "not found" in err.lower()
    assert "other-api" in err


def test_topics_requires_explicit_source_when_slug_exists_in_both_stores(
    tmp_path, monkeypatch, capsys
):
    docs_store = tmp_path / ".king-context" / "docs"
    research_store = tmp_path / ".king-context" / "research"
    docs_store.mkdir(parents=True)
    research_store.mkdir(parents=True)
    _build_doc(docs_store, doc_name="shared-api")
    _build_doc(research_store, doc_name="shared-api")

    import context_cli.cli as cli_mod
    monkeypatch.setattr(cli_mod, "STORE_DIR", docs_store)
    monkeypatch.setattr(cli_mod, "RESEARCH_STORE_DIR", research_store)

    with pytest.raises(SystemExit):
        _run_cli(["topics", "shared-api"], monkeypatch)

    err = capsys.readouterr().err
    assert "exists in multiple stores" in err
    assert "--source docs" in err
    assert "--source research" in err
