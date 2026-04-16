"""Tests for context_cli.searcher module."""

import json

from context_cli.searcher import SearchResult, search


def _make_doc(store_dir, name, sections):
    """Create a full .king-context/<doc>/ structure with reverse indexes.

    Each section dict must have: path, title, keywords, use_cases, tags, priority, content.
    """
    doc_dir = store_dir / name
    sections_dir = doc_dir / "sections"
    sections_dir.mkdir(parents=True)

    # index.json
    (doc_dir / "index.json").write_text(json.dumps({
        "name": name,
        "display_name": name,
        "version": "v1",
        "base_url": "https://example.com",
        "section_count": len(sections),
    }))

    # Build reverse indexes
    keywords_index: dict[str, list[str]] = {}
    use_cases_index: dict[str, list[str]] = {}
    tags_index: dict[str, list[str]] = {}

    for s in sections:
        path = s["path"]
        section_data = {
            "title": s["title"],
            "path": path,
            "url": s.get("url", ""),
            "keywords": s.get("keywords", []),
            "use_cases": s.get("use_cases", []),
            "tags": s.get("tags", []),
            "priority": s.get("priority", 0),
            "content": s.get("content", ""),
            "token_estimate": len(s.get("content", "").split()),
        }
        (sections_dir / f"{path}.json").write_text(json.dumps(section_data))

        for kw in s.get("keywords", []):
            keywords_index.setdefault(kw, []).append(path)
        for uc in s.get("use_cases", []):
            use_cases_index.setdefault(uc, []).append(path)
        for tag in s.get("tags", []):
            tags_index.setdefault(tag, []).append(path)

    (doc_dir / "keywords.json").write_text(json.dumps(keywords_index))
    (doc_dir / "use_cases.json").write_text(json.dumps(use_cases_index))
    (doc_dir / "tags.json").write_text(json.dumps(tags_index))

    return doc_dir


SECTIONS_A = [
    {
        "path": "getting-started",
        "title": "Getting Started",
        "keywords": ["setup", "install"],
        "use_cases": ["How to install the SDK"],
        "tags": ["guide"],
        "priority": 10,
        "content": "Install with pip install test-api",
    },
    {
        "path": "authentication",
        "title": "Authentication",
        "keywords": ["auth", "api-key"],
        "use_cases": ["How to authenticate requests"],
        "tags": ["guide", "security"],
        "priority": 8,
        "content": "Use your API key in the header",
    },
    {
        "path": "rate-limiting",
        "title": "Rate Limiting",
        "keywords": ["rate-limit", "throttle"],
        "use_cases": ["How to handle rate limits"],
        "tags": ["reference"],
        "priority": 5,
        "content": "Rate limits are 100 requests per minute",
    },
]

SECTIONS_B = [
    {
        "path": "setup",
        "title": "Setup Guide",
        "keywords": ["setup", "configuration"],
        "use_cases": ["How to set up the CLI tool"],
        "tags": ["guide"],
        "priority": 9,
        "content": "Run the setup wizard to get started",
    },
    {
        "path": "plugins",
        "title": "Plugins",
        "keywords": ["plugins", "extensions"],
        "use_cases": ["How to install plugins"],
        "tags": ["reference"],
        "priority": 6,
        "content": "Plugins extend the core functionality",
    },
]


def test_keyword_match_scoring(tmp_path):
    """Keyword exact match should add 3 points per hit."""
    _make_doc(tmp_path, "test-api", SECTIONS_A)

    results = search("setup", tmp_path, doc_name="test-api")

    assert len(results) >= 1
    # "getting-started" has keyword "setup" (3) + priority 10*0.5 (5) = 8
    gs = [r for r in results if r.section_path == "getting-started"][0]
    assert gs.score == 3.0 + 10 * 0.5


def test_use_case_substring_match(tmp_path):
    """Use-case substring match should add 2 points per hit."""
    _make_doc(tmp_path, "test-api", SECTIONS_A)

    results = search("install", tmp_path, doc_name="test-api")

    # "getting-started" has keyword "install" (3) + use_case contains "install" (2)
    # + priority 10*0.5 (5) = 10
    gs = [r for r in results if r.section_path == "getting-started"][0]
    assert gs.score == 3.0 + 2.0 + 10 * 0.5


def test_tag_match_scoring(tmp_path):
    """Tag exact match should add 1 point per hit."""
    _make_doc(tmp_path, "test-api", SECTIONS_A)

    results = search("guide", tmp_path, doc_name="test-api")

    # Both "getting-started" and "authentication" have tag "guide"
    paths = {r.section_path for r in results}
    assert "getting-started" in paths
    assert "authentication" in paths
    # "getting-started": tag "guide"(1) + priority 10*0.5(5) = 6
    gs = [r for r in results if r.section_path == "getting-started"][0]
    assert gs.score == 1.0 + 10 * 0.5


def test_combined_scoring(tmp_path):
    """A term matching keywords, use_cases, and tags should accumulate all weights."""
    _make_doc(tmp_path, "test-api", SECTIONS_A)

    # "security" matches tag "security" on authentication section
    # Also "authenticate" in use_case "How to authenticate requests" would not match
    # because the term is "security" not "authenticate".
    # auth section: tag "security"(1) + priority 8*0.5(4) = 5
    results = search("security", tmp_path, doc_name="test-api")

    auth = [r for r in results if r.section_path == "authentication"][0]
    assert auth.score == 1.0 + 8 * 0.5


def test_cross_doc_search(tmp_path):
    """Search without doc_name should return results from all docs."""
    _make_doc(tmp_path, "api-a", SECTIONS_A)
    _make_doc(tmp_path, "api-b", SECTIONS_B)

    results = search("setup", tmp_path)

    doc_names = {r.doc_name for r in results}
    assert "api-a" in doc_names
    assert "api-b" in doc_names


def test_single_doc_filtering(tmp_path):
    """Search with doc_name should only return results from that doc."""
    _make_doc(tmp_path, "api-a", SECTIONS_A)
    _make_doc(tmp_path, "api-b", SECTIONS_B)

    results = search("setup", tmp_path, doc_name="api-a")

    for r in results:
        assert r.doc_name == "api-a"


def test_empty_results(tmp_path):
    """Search with no matching terms should return empty list."""
    _make_doc(tmp_path, "test-api", SECTIONS_A)

    results = search("nonexistent-foobar", tmp_path, doc_name="test-api")

    assert results == []


def test_top_n_limiting(tmp_path):
    """Results should be limited to the top parameter."""
    _make_doc(tmp_path, "test-api", SECTIONS_A)

    results = search("guide", tmp_path, doc_name="test-api", top=1)

    assert len(results) == 1
    # Should return highest-scored result (getting-started has higher priority)
    assert results[0].section_path == "getting-started"


def test_empty_query_returns_nothing(tmp_path):
    """An empty query string should return empty list."""
    _make_doc(tmp_path, "test-api", SECTIONS_A)

    results = search("", tmp_path, doc_name="test-api")

    assert results == []


def test_nonexistent_doc_returns_empty(tmp_path):
    """Searching a doc_name that does not exist returns empty."""
    _make_doc(tmp_path, "test-api", SECTIONS_A)

    results = search("setup", tmp_path, doc_name="no-such-doc")

    assert results == []


def test_results_sorted_by_score_descending(tmp_path):
    """Results must come back sorted highest score first."""
    _make_doc(tmp_path, "test-api", SECTIONS_A)

    results = search("guide", tmp_path, doc_name="test-api")

    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_search_result_has_metadata_fields(tmp_path):
    """Each SearchResult should carry metadata from the section file."""
    _make_doc(tmp_path, "test-api", SECTIONS_A)

    results = search("setup", tmp_path, doc_name="test-api")

    gs = [r for r in results if r.section_path == "getting-started"][0]
    assert gs.title == "Getting Started"
    assert "setup" in gs.keywords
    assert gs.priority == 10
    assert isinstance(gs.use_cases, list)
    assert isinstance(gs.tags, list)


def test_skips_underscore_directories(tmp_path):
    """Directories starting with underscore should be skipped in cross-doc search."""
    _make_doc(tmp_path, "real-doc", SECTIONS_A)
    _make_doc(tmp_path, "_internal", SECTIONS_B)

    results = search("setup", tmp_path)

    doc_names = {r.doc_name for r in results}
    assert "_internal" not in doc_names
