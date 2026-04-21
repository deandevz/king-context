"""Searcher — metadata-based scoring on reverse indexes in .king-context/."""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SearchResult:
    doc_name: str
    section_path: str
    title: str
    score: float
    keywords: list[str]
    use_cases: list[str]
    tags: list[str]
    priority: int
    source: str = "docs"


def _normalize_query(query: str) -> list[str]:
    """Lowercase, strip, and tokenize query into terms."""
    return query.lower().strip().split()


def _load_json(path: Path) -> dict:
    """Load a JSON file, returning empty dict on failure."""
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        return {}


def _score_sections_in_doc(
    terms: list[str],
    doc_dir: Path,
) -> dict[str, float]:
    """Score sections using reverse indexes in a single doc directory.

    Returns a dict mapping section_path to its accumulated score.
    """
    keywords_index = _load_json(doc_dir / "keywords.json")
    use_cases_index = _load_json(doc_dir / "use_cases.json")
    tags_index = _load_json(doc_dir / "tags.json")

    scores: dict[str, float] = {}

    # Keyword exact match (weight 3)
    for term in terms:
        for key, paths in keywords_index.items():
            if term == key.lower():
                for p in paths:
                    scores[p] = scores.get(p, 0.0) + 3.0

    # Use-case substring match (weight 2)
    for term in terms:
        for use_case, paths in use_cases_index.items():
            if term in use_case.lower():
                for p in paths:
                    scores[p] = scores.get(p, 0.0) + 2.0

    # Tag exact match (weight 1)
    for term in terms:
        for key, paths in tags_index.items():
            if term == key.lower():
                for p in paths:
                    scores[p] = scores.get(p, 0.0) + 1.0

    return scores


def search(
    query: str,
    store_dir: Path,
    doc_name: str | None = None,
    top: int = 5,
    source: str = "docs",
) -> list[SearchResult]:
    """Search documentation sections by query using reverse-index scoring.

    Args:
        query: The search query string.
        store_dir: Path to the .king-context/ directory.
        doc_name: If given, restrict search to this doc only.
        top: Maximum number of results to return.

    Returns:
        List of SearchResult sorted by score descending, limited to `top`.
    """
    terms = _normalize_query(query)
    if not terms:
        return []

    # Determine which doc directories to search
    if doc_name is not None:
        doc_dir = store_dir / doc_name
        if not doc_dir.is_dir() or not (doc_dir / "index.json").exists():
            return []
        doc_dirs = [(doc_name, doc_dir)]
    else:
        doc_dirs = []
        if store_dir.exists():
            for entry in sorted(store_dir.iterdir()):
                if not entry.is_dir() or entry.name.startswith("_"):
                    continue
                if not (entry / "index.json").exists():
                    continue
                doc_dirs.append((entry.name, entry))

    # Score all sections across selected docs
    candidates: list[SearchResult] = []

    for d_name, doc_dir in doc_dirs:
        section_scores = _score_sections_in_doc(terms, doc_dir)

        sections_dir = doc_dir / "sections"
        for section_path, base_score in section_scores.items():
            section_file = sections_dir / f"{section_path}.json"
            section_data = _load_json(section_file)
            if not section_data:
                continue

            priority = section_data.get("priority", 0)
            final_score = base_score + priority * 0.5

            candidates.append(SearchResult(
                doc_name=d_name,
                section_path=section_path,
                title=section_data.get("title", ""),
                score=final_score,
                keywords=section_data.get("keywords", []),
                use_cases=section_data.get("use_cases", []),
                tags=section_data.get("tags", []),
                priority=priority,
                source=source,
            ))

    # Sort by score descending, then limit
    candidates.sort(key=lambda r: r.score, reverse=True)
    return candidates[:top]
