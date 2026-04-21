"""Integration tests for context_cli.cli module."""

import json
import sys

import pytest

from context_cli.indexer import index_doc


@pytest.fixture
def store_with_doc(tmp_path, monkeypatch):
    """Create a .king-context/docs/ store with one indexed doc and patch STORE_DIR."""
    store_dir = tmp_path / ".king-context" / "docs"
    store_dir.mkdir(parents=True)
    research_store_dir = tmp_path / ".king-context" / "research"
    research_store_dir.mkdir(parents=True)

    # Create source JSON
    source = {
        "name": "test-api",
        "display_name": "Test API",
        "version": "v1",
        "base_url": "https://example.com",
        "sections": [
            {
                "title": "Getting Started",
                "path": "getting-started",
                "url": "https://example.com/getting-started",
                "keywords": ["setup", "install"],
                "use_cases": ["How to install the SDK"],
                "tags": ["guide"],
                "priority": 10,
                "content": "Install with pip install test-api. Then configure your key.",
            },
            {
                "title": "Authentication",
                "path": "authentication",
                "url": "https://example.com/auth",
                "keywords": ["auth", "api-key", "security"],
                "use_cases": ["How to authenticate requests"],
                "tags": ["guide", "security"],
                "priority": 8,
                "content": "Use your API key in the x-api-key header for all requests.",
            },
        ],
    }
    src_file = tmp_path / "test-api.json"
    src_file.write_text(json.dumps(source))
    index_doc(src_file, store_dir)

    import context_cli.cli as cli_mod
    monkeypatch.setattr(cli_mod, "STORE_DIR", store_dir)
    monkeypatch.setattr(cli_mod, "RESEARCH_STORE_DIR", research_store_dir)
    monkeypatch.setattr(cli_mod, "PROJECT_ROOT", tmp_path)

    return store_dir, tmp_path, src_file


def _run_cli(args, monkeypatch):
    """Run CLI by patching sys.argv and calling main()."""
    from context_cli.cli import main
    monkeypatch.setattr(sys, "argv", ["kctx"] + args)
    main()


def test_list_shows_docs(store_with_doc, monkeypatch, capsys):
    _run_cli(["list"], monkeypatch)
    out = capsys.readouterr().out
    assert "test-api" in out
    assert "Test API" in out


def test_list_json(store_with_doc, monkeypatch, capsys):
    _run_cli(["list", "--json"], monkeypatch)
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "docs" in data and "research" in data
    assert len(data["docs"]) == 1
    assert data["docs"][0]["name"] == "test-api"
    assert data["research"] == []


def test_list_docs_only_json(store_with_doc, monkeypatch, capsys):
    _run_cli(["list", "docs", "--json"], monkeypatch)
    out = capsys.readouterr().out
    data = json.loads(out)
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["name"] == "test-api"


def test_list_research_only_empty(store_with_doc, monkeypatch, capsys):
    _run_cli(["list", "research"], monkeypatch)
    out = capsys.readouterr().out
    assert "No docs indexed" in out


def test_list_empty_store(tmp_path, monkeypatch, capsys):
    empty_store = tmp_path / ".king-context" / "docs"
    empty_store.mkdir(parents=True)
    empty_research = tmp_path / ".king-context" / "research"
    empty_research.mkdir(parents=True)
    import context_cli.cli as cli_mod
    monkeypatch.setattr(cli_mod, "STORE_DIR", empty_store)
    monkeypatch.setattr(cli_mod, "RESEARCH_STORE_DIR", empty_research)

    _run_cli(["list"], monkeypatch)
    out = capsys.readouterr().out
    assert "No docs indexed" in out


def test_search_returns_results(store_with_doc, monkeypatch, capsys):
    _run_cli(["search", "install"], monkeypatch)
    out = capsys.readouterr().out
    assert "Getting Started" in out
    assert "score=" in out


def test_search_with_doc_filter(store_with_doc, monkeypatch, capsys):
    _run_cli(["search", "auth", "--doc", "test-api"], monkeypatch)
    out = capsys.readouterr().out
    assert "Authentication" in out


def test_search_with_top(store_with_doc, monkeypatch, capsys):
    _run_cli(["search", "guide", "--top", "1"], monkeypatch)
    out = capsys.readouterr().out
    # Should have exactly 1 numbered result
    lines = [l for l in out.strip().split("\n") if l and l[0].isdigit()]
    assert len(lines) == 1


def test_search_no_results(store_with_doc, monkeypatch, capsys):
    _run_cli(["search", "zzzznonexistent"], monkeypatch)
    out = capsys.readouterr().out
    assert "No results" in out


def test_read_full(store_with_doc, monkeypatch, capsys):
    _run_cli(["read", "test-api", "getting-started"], monkeypatch)
    out = capsys.readouterr().out
    assert "Getting Started" in out
    assert "pip install test-api" in out


def test_read_preview(store_with_doc, monkeypatch, capsys):
    _run_cli(["read", "test-api", "authentication", "--preview"], monkeypatch)
    out = capsys.readouterr().out
    assert "Authentication" in out
    assert "Tokens:" in out


def test_read_not_found(store_with_doc, monkeypatch):
    with pytest.raises(SystemExit):
        _run_cli(["read", "test-api", "nonexistent"], monkeypatch)


def test_read_json(store_with_doc, monkeypatch, capsys):
    _run_cli(["read", "test-api", "authentication", "--json"], monkeypatch)
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["title"] == "Authentication"
    assert "content" in data


def test_read_requires_explicit_source_when_slug_exists_in_both_stores(
    store_with_doc, monkeypatch, capsys
):
    _, tmp_path, _ = store_with_doc
    research_source = {
        "name": "test-api",
        "display_name": "Test API Research",
        "version": "v1",
        "base_url": "",
        "sections": [
            {
                "title": "Research Finding",
                "path": "finding",
                "url": "https://example.com/research/finding",
                "keywords": ["finding"],
                "use_cases": ["Read a research-only finding"],
                "tags": ["research"],
                "priority": 7,
                "content": "Research-only section content.",
                "source_type": "research",
            }
        ],
    }
    research_file = tmp_path / "test-api-research.json"
    research_file.write_text(json.dumps(research_source))

    import context_cli.cli as cli_mod
    index_doc(research_file, cli_mod.RESEARCH_STORE_DIR)

    with pytest.raises(SystemExit):
        _run_cli(["read", "test-api", "finding"], monkeypatch)

    err = capsys.readouterr().err
    assert "exists in multiple stores" in err
    assert "--source docs" in err
    assert "--source research" in err


def test_index_single_file(tmp_path, monkeypatch, capsys):
    store_dir = tmp_path / ".king-context" / "docs"
    research_store = tmp_path / ".king-context" / "research"
    import context_cli.cli as cli_mod
    monkeypatch.setattr(cli_mod, "STORE_DIR", store_dir)
    monkeypatch.setattr(cli_mod, "RESEARCH_STORE_DIR", research_store)

    source = {
        "name": "new-api",
        "display_name": "New API",
        "version": "v1",
        "base_url": "https://new.com",
        "sections": [
            {
                "title": "Intro",
                "path": "intro",
                "url": "https://new.com/intro",
                "keywords": ["intro"],
                "use_cases": ["Getting started"],
                "tags": ["guide"],
                "priority": 5,
                "content": "Welcome to the new API.",
            }
        ],
    }
    src_file = tmp_path / "new-api.json"
    src_file.write_text(json.dumps(source))

    _run_cli(["index", str(src_file)], monkeypatch)
    out = capsys.readouterr().out
    assert "Indexed new-api" in out
    assert (store_dir / "new-api" / "index.json").exists()


def test_index_auto_detects_research(tmp_path, monkeypatch, capsys):
    store_dir = tmp_path / ".king-context" / "docs"
    research_store = tmp_path / ".king-context" / "research"
    import context_cli.cli as cli_mod
    monkeypatch.setattr(cli_mod, "STORE_DIR", store_dir)
    monkeypatch.setattr(cli_mod, "RESEARCH_STORE_DIR", research_store)

    source = {
        "name": "my-topic",
        "display_name": "My Topic",
        "version": "v1",
        "base_url": "",
        "sections": [
            {
                "title": "A",
                "path": "a",
                "url": "https://ex.com/a",
                "keywords": ["k"], "use_cases": ["u"], "tags": ["t"],
                "priority": 5,
                "content": "hello",
                "source_type": "research",
            }
        ],
    }
    src_file = tmp_path / "my-topic.json"
    src_file.write_text(json.dumps(source))

    _run_cli(["index", str(src_file)], monkeypatch)
    out = capsys.readouterr().out
    assert "(research)" in out
    assert (research_store / "my-topic" / "index.json").exists()
    assert not (store_dir / "my-topic").exists()


def test_index_all(tmp_path, monkeypatch, capsys):
    store_dir = tmp_path / ".king-context" / "docs"
    research_store = tmp_path / ".king-context" / "research"
    data_dir = tmp_path / ".king-context" / "data"
    data_dir.mkdir(parents=True)

    import context_cli.cli as cli_mod
    monkeypatch.setattr(cli_mod, "STORE_DIR", store_dir)
    monkeypatch.setattr(cli_mod, "RESEARCH_STORE_DIR", research_store)
    monkeypatch.setattr(cli_mod, "PROJECT_ROOT", tmp_path)

    for name in ["api-a", "api-b"]:
        src = {
            "name": name,
            "display_name": name.title(),
            "version": "v1",
            "base_url": f"https://{name}.com",
            "sections": [],
        }
        (data_dir / f"{name}.json").write_text(json.dumps(src))

    _run_cli(["index", "--all"], monkeypatch)
    out = capsys.readouterr().out
    assert "Indexed api-a" in out
    assert "Indexed api-b" in out


def test_index_file_not_found(tmp_path, monkeypatch):
    store_dir = tmp_path / ".king-context" / "docs"
    research_store = tmp_path / ".king-context" / "research"
    import context_cli.cli as cli_mod
    monkeypatch.setattr(cli_mod, "STORE_DIR", store_dir)
    monkeypatch.setattr(cli_mod, "RESEARCH_STORE_DIR", research_store)

    with pytest.raises(SystemExit):
        _run_cli(["index", "/nonexistent/file.json"], monkeypatch)


def test_help_shows_subcommands(monkeypatch, capsys):
    _run_cli([], monkeypatch)
    out = capsys.readouterr().out
    assert "list" in out
    assert "search" in out
    assert "read" in out
    assert "index" in out
