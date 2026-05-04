"""Indexer — reads .king-context/data/*.json monolithic files and generates .king-context/docs/ structure."""

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

@dataclass
class IndexResult:
    doc_name: str
    section_count: int
    store_path: Path


def _estimate_tokens(text: str) -> int:
    """Estimate token count from text (words * 1.33)."""
    return int(len(text.split()) * 1.33)


def index_doc(json_path: Path, store_dir: Path) -> IndexResult:
    """Read a monolithic JSON and create the .king-context/<doc>/ structure."""
    data = json.loads(json_path.read_text())

    name = data["name"]
    doc_dir = store_dir / name

    # Clean previous index
    if doc_dir.exists():
        shutil.rmtree(doc_dir)

    sections_dir = doc_dir / "sections"
    sections_dir.mkdir(parents=True)

    # Write index.json (metadata only)
    sections = data.get("sections", [])
    index_meta = {
        "name": name,
        "display_name": data.get("display_name", name),
        "version": data.get("version", ""),
        "base_url": data.get("base_url", ""),
        "section_count": len(sections),
        "indexed_at": datetime.now(timezone.utc).isoformat(),
    }
    (doc_dir / "index.json").write_text(json.dumps(index_meta, indent=2))

    # Reverse indexes
    keywords_index: dict[str, list[str]] = {}
    use_cases_index: dict[str, list[str]] = {}
    tags_index: dict[str, list[str]] = {}

    for section in sections:
        path = section.get("path", "")
        content = section.get("content", "")

        # Write individual section file
        section_data = {
            "title": section.get("title", ""),
            "path": path,
            "url": section.get("url", ""),
            "keywords": section.get("keywords", []),
            "use_cases": section.get("use_cases", []),
            "tags": section.get("tags", []),
            "priority": section.get("priority", 0),
            "content": content,
            "token_estimate": _estimate_tokens(content),
        }
        for key in (
            "source_type",
            "source_file",
            "source_format",
            "source_collection",
            "source_kind",
        ):
            if key in section:
                section_data[key] = section[key]
        (sections_dir / f"{path}.json").write_text(
            json.dumps(section_data, indent=2)
        )

        # Build reverse indexes
        for kw in section.get("keywords", []):
            keywords_index.setdefault(kw, []).append(path)
        for uc in section.get("use_cases", []):
            use_cases_index.setdefault(uc, []).append(path)
        for tag in section.get("tags", []):
            tags_index.setdefault(tag, []).append(path)

    # Write reverse indexes
    (doc_dir / "keywords.json").write_text(json.dumps(keywords_index, indent=2))
    (doc_dir / "use_cases.json").write_text(json.dumps(use_cases_index, indent=2))
    (doc_dir / "tags.json").write_text(json.dumps(tags_index, indent=2))

    return IndexResult(
        doc_name=name,
        section_count=len(sections),
        store_path=doc_dir,
    )


def index_all(data_dir: Path, store_dir: Path) -> list[IndexResult]:
    """Index all *.json files in data_dir."""
    results: list[IndexResult] = []
    for json_file in sorted(data_dir.glob("*.json")):
        results.append(index_doc(json_file, store_dir))
    return results
