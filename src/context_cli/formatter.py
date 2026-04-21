"""Formatter — compact plain text and JSON output for CLI commands."""

import json
from dataclasses import asdict


def _to_dict(obj):
    """Convert a dataclass or namespace object to a dict."""
    try:
        return asdict(obj)
    except TypeError:
        return vars(obj)


def format_list(docs, as_json=False) -> str:
    """Format a list of DocInfo objects as a table or JSON.

    Plain: compact table with columns Name | Display Name | Version | Sections.
    JSON: list of doc dicts.
    """
    if as_json:
        return json.dumps([_to_dict(d) for d in docs], indent=2)

    if not docs:
        return "No documentation indexed."

    # Calculate column widths
    headers = ("Name", "Display Name", "Version", "Sections")
    rows = [
        (d.name, d.display_name, d.version, str(d.section_count))
        for d in docs
    ]
    widths = [
        max(len(h), *(len(r[i]) for r in rows))
        for i, h in enumerate(headers)
    ]

    def _row(cells):
        return "  ".join(c.ljust(w) for c, w in zip(cells, widths)).rstrip()

    lines = [_row(headers), "  ".join("-" * w for w in widths)]
    for r in rows:
        lines.append(_row(r))
    return "\n".join(lines)


def format_search(results, as_json=False) -> str:
    """Format ranked search results as a numbered list or JSON.

    Plain: numbered list with title, path, score, first use_case.
    JSON: list of result dicts.
    """
    if as_json:
        return json.dumps([_to_dict(r) for r in results], indent=2)

    if not results:
        return "No results found."

    lines = []
    for i, r in enumerate(results, 1):
        use_case = r.use_cases[0] if r.use_cases else ""
        source = getattr(r, "source", "docs")
        line = f"{i}. [{source}] {r.title} ({r.doc_name}/{r.section_path}) score={r.score:.2f}"
        if use_case:
            line += f"\n   {use_case}"
        lines.append(line)
    return "\n".join(lines)


def format_section(content, as_json=False) -> str:
    """Format a single section's content or JSON.

    Plain: "# title\\n\\ncontent\\n\\n---\\nURL: url | Tokens: N [PREVIEW]"
    JSON: content dict.
    """
    if as_json:
        return json.dumps(_to_dict(content), indent=2)

    footer_parts = []
    if content.url:
        footer_parts.append(f"URL: {content.url}")
    footer_parts.append(f"Tokens: {content.token_estimate}")
    if content.is_preview:
        footer_parts.append("[PREVIEW]")

    footer = " | ".join(footer_parts)
    return f"# {content.title}\n\n{content.content}\n\n---\n{footer}"


def format_topics(tag_groups, as_json=False) -> str:
    """Format sections grouped by tag.

    tag_groups: dict[str, list[dict]] where each dict has title, path, priority.
    Plain: "## tag (N sections)\\n  - title (path) [priority: N]"
    JSON: the tag_groups dict.
    """
    if as_json:
        return json.dumps(tag_groups, indent=2)

    if not tag_groups:
        return "No topics found."

    lines = []
    for tag, sections in tag_groups.items():
        lines.append(f"## {tag} ({len(sections)} sections)")
        for s in sections:
            lines.append(f"  - {s['title']} ({s['path']}) [priority: {s['priority']}]")
    return "\n".join(lines)


def format_grep(matches, as_json=False) -> str:
    """Format grep matches grouped by section.

    Plain: "## doc/section-title\\n  line_number: line_content"
    JSON: list of match dicts.
    """
    if as_json:
        return json.dumps([_to_dict(m) for m in matches], indent=2)

    if not matches:
        return "No matches found."

    # Group by source + doc_name + section_title
    groups: dict[str, list] = {}
    for m in matches:
        source = getattr(m, "source", "docs")
        key = f"[{source}] {m.doc_name}/{m.section_title}"
        groups.setdefault(key, []).append(m)

    lines = []
    for heading, group in groups.items():
        lines.append(f"## {heading}")
        for m in group:
            lines.append(f"  {m.line_number}: {m.line_content}")
    return "\n".join(lines)
