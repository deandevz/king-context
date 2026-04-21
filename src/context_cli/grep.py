"""Grep engine — content-level regex search within indexed sections."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GrepMatch:
    doc_name: str
    section_path: str
    section_title: str
    line_number: int
    line_content: str
    context_before: list[str] = field(default_factory=list)
    context_after: list[str] = field(default_factory=list)
    source: str = "docs"


def grep_docs(
    pattern: str,
    store_dir: Path,
    doc_name: str | None = None,
    context_lines: int = 0,
    source: str = "docs",
) -> list[GrepMatch]:
    """Search section content for lines matching a regex pattern.

    Args:
        pattern: Regular expression to match (case-insensitive).
        store_dir: Path to the .king-context/ directory.
        doc_name: If set, restrict search to this doc only.
        context_lines: Number of surrounding lines to include.

    Returns:
        List of GrepMatch objects, grouped by section (matches within the
        same section are adjacent in the list).
    """
    regex = re.compile(pattern, re.IGNORECASE)

    if not store_dir.exists():
        return []

    # Determine which doc directories to scan
    if doc_name is not None:
        doc_dirs = [store_dir / doc_name]
    else:
        doc_dirs = sorted(
            d for d in store_dir.iterdir()
            if d.is_dir() and not d.name.startswith("_")
        )

    matches: list[GrepMatch] = []

    for doc_dir in doc_dirs:
        sections_dir = doc_dir / "sections"
        if not sections_dir.exists():
            continue

        for section_file in sorted(sections_dir.glob("*.json")):
            try:
                data = json.loads(section_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            content = data.get("content", "")
            title = data.get("title", "")
            section_path = data.get("path", section_file.stem)
            lines = content.split("\n")

            section_matches: list[GrepMatch] = []
            for i, line in enumerate(lines):
                if regex.search(line):
                    before = lines[max(0, i - context_lines):i]
                    after = lines[i + 1:i + 1 + context_lines]
                    section_matches.append(GrepMatch(
                        doc_name=doc_dir.name,
                        section_path=section_path,
                        section_title=title,
                        line_number=i + 1,
                        line_content=line,
                        context_before=before,
                        context_after=after,
                        source=source,
                    ))

            matches.extend(section_matches)

    return matches
