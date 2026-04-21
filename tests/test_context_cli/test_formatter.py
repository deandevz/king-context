"""Tests for context_cli.formatter module."""

import json
from types import SimpleNamespace

from context_cli.formatter import (
    format_grep,
    format_list,
    format_search,
    format_section,
    format_topics,
)


def _doc(**kwargs):
    defaults = dict(
        name="react",
        display_name="React",
        version="v18",
        section_count=42,
        base_url="https://react.dev",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _result(**kwargs):
    defaults = dict(
        doc_name="react",
        section_path="hooks/use-state",
        title="useState",
        score=0.95,
        keywords=["state", "hooks"],
        use_cases=["manage component state"],
        tags=["hooks"],
        priority=10,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _section(**kwargs):
    defaults = dict(
        title="useState",
        content="useState is a React Hook...",
        url="https://react.dev/reference/react/useState",
        token_estimate=120,
        is_preview=False,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _grep_match(**kwargs):
    defaults = dict(
        doc_name="react",
        section_path="hooks/use-state",
        section_title="useState",
        line_number=15,
        line_content="const [count, setCount] = useState(0);",
        context_before=["// initialize state"],
        context_after=["return count;"],
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# --- format_list ---


def test_format_list_plain():
    docs = [_doc(), _doc(name="vue", display_name="Vue.js", version="v3", section_count=30)]
    output = format_list(docs)

    assert "Name" in output
    assert "Display Name" in output
    assert "react" in output
    assert "Vue.js" in output
    assert "42" in output
    assert "30" in output
    # Table has header, separator, and 2 data rows
    lines = output.strip().split("\n")
    assert len(lines) == 4


def test_format_list_plain_empty():
    assert format_list([]) == "No documentation indexed."


def test_format_list_json():
    docs = [_doc()]
    output = format_list(docs, as_json=True)
    data = json.loads(output)

    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["name"] == "react"
    assert data[0]["section_count"] == 42


# --- format_search ---


def test_format_search_plain():
    results = [
        _result(),
        _result(title="useEffect", section_path="hooks/use-effect", score=0.80,
                use_cases=["run side effects"]),
    ]
    output = format_search(results)

    assert "1. [docs] useState" in output
    assert "score=0.95" in output
    assert "manage component state" in output
    assert "2. [docs] useEffect" in output
    assert "score=0.80" in output
    assert "run side effects" in output


def test_format_search_plain_empty():
    assert format_search([]) == "No results found."


def test_format_search_plain_no_use_case():
    results = [_result(use_cases=[])]
    output = format_search(results)
    assert "1. [docs] useState" in output
    # No indented use_case line
    assert output.count("\n") == 0


def test_format_search_json():
    results = [_result()]
    output = format_search(results, as_json=True)
    data = json.loads(output)

    assert isinstance(data, list)
    assert data[0]["doc_name"] == "react"
    assert data[0]["score"] == 0.95
    assert data[0]["keywords"] == ["state", "hooks"]


# --- format_section ---


def test_format_section_plain():
    content = _section()
    output = format_section(content)

    assert output.startswith("# useState")
    assert "useState is a React Hook..." in output
    assert "---" in output
    assert "URL: https://react.dev/reference/react/useState" in output
    assert "Tokens: 120" in output
    assert "[PREVIEW]" not in output


def test_format_section_plain_preview():
    content = _section(is_preview=True)
    output = format_section(content)
    assert "[PREVIEW]" in output


def test_format_section_plain_no_url():
    content = _section(url="")
    output = format_section(content)
    assert "URL:" not in output
    assert "Tokens: 120" in output


def test_format_section_json():
    content = _section()
    output = format_section(content, as_json=True)
    data = json.loads(output)

    assert data["title"] == "useState"
    assert data["token_estimate"] == 120
    assert data["is_preview"] is False


# --- format_topics ---


def test_format_topics_plain():
    tag_groups = {
        "hooks": [
            {"title": "useState", "path": "hooks/use-state", "priority": 10},
            {"title": "useEffect", "path": "hooks/use-effect", "priority": 8},
        ],
        "components": [
            {"title": "Fragment", "path": "api/fragment", "priority": 5},
        ],
    }
    output = format_topics(tag_groups)

    assert "## hooks (2 sections)" in output
    assert "  - useState (hooks/use-state) [priority: 10]" in output
    assert "  - useEffect (hooks/use-effect) [priority: 8]" in output
    assert "## components (1 sections)" in output
    assert "  - Fragment (api/fragment) [priority: 5]" in output


def test_format_topics_plain_empty():
    assert format_topics({}) == "No topics found."


def test_format_topics_json():
    tag_groups = {
        "hooks": [{"title": "useState", "path": "hooks/use-state", "priority": 10}],
    }
    output = format_topics(tag_groups, as_json=True)
    data = json.loads(output)

    assert "hooks" in data
    assert data["hooks"][0]["title"] == "useState"


# --- format_grep ---


def test_format_grep_plain():
    matches = [
        _grep_match(),
        _grep_match(line_number=20, line_content="setCount(prev => prev + 1);"),
    ]
    output = format_grep(matches)

    assert "## [docs] react/useState" in output
    assert "  15: const [count, setCount] = useState(0);" in output
    assert "  20: setCount(prev => prev + 1);" in output


def test_format_grep_plain_multiple_sections():
    matches = [
        _grep_match(),
        _grep_match(doc_name="vue", section_title="ref", line_number=5,
                     line_content="const count = ref(0);"),
    ]
    output = format_grep(matches)

    assert "## [docs] react/useState" in output
    assert "## [docs] vue/ref" in output


def test_format_grep_plain_empty():
    assert format_grep([]) == "No matches found."


def test_format_grep_json():
    matches = [_grep_match()]
    output = format_grep(matches, as_json=True)
    data = json.loads(output)

    assert isinstance(data, list)
    assert data[0]["doc_name"] == "react"
    assert data[0]["line_number"] == 15
    assert data[0]["context_before"] == ["// initialize state"]
