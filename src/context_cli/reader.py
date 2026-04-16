"""Reader module — reads section content with optional preview truncation."""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SectionContent:
    title: str
    content: str
    url: str
    token_estimate: int
    is_preview: bool


def _estimate_tokens(text: str) -> int:
    """Estimate token count from text (words * 1.33)."""
    return int(len(text.split()) * 1.33)


def read_section(
    doc_name: str,
    section_path: str,
    store_dir: Path,
    preview: bool = False,
) -> SectionContent:
    """Read a section file and return its content.

    Args:
        doc_name: Name of the documentation (directory under store_dir).
        section_path: Filename stem of the section (without .json).
        store_dir: Root .king-context/ directory.
        preview: If True, truncate content to ~200 tokens (~150 words).

    Returns:
        SectionContent with the (possibly truncated) content.

    Raises:
        FileNotFoundError: When the section file does not exist.
            The error message includes up to 5 similar path suggestions.
    """
    section_file = store_dir / doc_name / "sections" / f"{section_path}.json"

    if not section_file.exists():
        suggestions = suggest_similar(doc_name, section_path, store_dir)
        hint = ""
        if suggestions:
            hint = "\n  Did you mean:\n" + "\n".join(
                f"    - {s}" for s in suggestions
            )
        raise FileNotFoundError(
            f"Section '{section_path}' not found in '{doc_name}'.{hint}"
        )

    data = json.loads(section_file.read_text())
    content = data.get("content", "")
    full_token_estimate = data.get("token_estimate", _estimate_tokens(content))

    is_preview = False
    if preview and content:
        words = content.split()
        if len(words) > 150:
            content = " ".join(words[:150])
            is_preview = True

    return SectionContent(
        title=data.get("title", ""),
        content=content,
        url=data.get("url", ""),
        token_estimate=full_token_estimate,
        is_preview=is_preview,
    )


def suggest_similar(
    doc_name: str,
    section_path: str,
    store_dir: Path,
) -> list[str]:
    """Return up to 5 section paths similar to *section_path*.

    Uses simple substring and prefix matching against the filenames in
    the doc's sections/ directory.
    """
    sections_dir = store_dir / doc_name / "sections"
    if not sections_dir.is_dir():
        return []

    all_paths = sorted(
        p.stem for p in sections_dir.iterdir() if p.suffix == ".json"
    )

    query = section_path.lower()

    # Score each candidate: prefix match scores higher than substring match.
    scored: list[tuple[int, str]] = []
    for name in all_paths:
        lower = name.lower()
        if lower.startswith(query) or query.startswith(lower):
            scored.append((0, name))
        elif query in lower or lower in query:
            scored.append((1, name))

    scored.sort()
    return [name for _, name in scored[:5]]
