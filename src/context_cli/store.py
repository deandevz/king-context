"""Store module — path resolution for .king-context/, doc listing, validation."""

import json
from dataclasses import dataclass
from pathlib import Path

from context_cli import STORE_DIR


@dataclass
class DocInfo:
    name: str
    display_name: str
    version: str
    section_count: int
    base_url: str


def get_store_dir() -> Path:
    """Return the .king-context/ path relative to PROJECT_ROOT."""
    return STORE_DIR


def list_docs(store_dir: Path) -> list[DocInfo]:
    """Read all <doc>/index.json and return a list of DocInfo."""
    if not store_dir.exists():
        return []

    docs: list[DocInfo] = []
    for entry in sorted(store_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        index_file = entry / "index.json"
        if not index_file.exists():
            continue
        try:
            data = json.loads(index_file.read_text())
            docs.append(DocInfo(
                name=data["name"],
                display_name=data.get("display_name", data["name"]),
                version=data.get("version", ""),
                section_count=data.get("section_count", 0),
                base_url=data.get("base_url", ""),
            ))
        except (json.JSONDecodeError, KeyError):
            continue
    return docs


def doc_exists(doc_name: str, store_dir: Path) -> bool:
    """Check if a doc directory with a valid index.json exists."""
    doc_dir = store_dir / doc_name
    return doc_dir.is_dir() and (doc_dir / "index.json").exists()
