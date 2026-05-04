"""Ingest local Markdown content into King Context JSON corpora."""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from context_cli import PROJECT_ROOT, RESEARCH_STORE_DIR, STORE_DIR
from context_cli.indexer import index_doc
from king_context.scraper.config import load_config


SUPPORTED_EXTENSIONS = {".md"}
IGNORED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
}
IGNORED_FILE_PREFIXES = (".", "~$")


@dataclass
class FileDiscovery:
    files: list[Path]
    discovered_count: int
    ignored_count: int
    ignored_extensions: list[str]


@dataclass
class IngestResult:
    doc_name: str
    display_name: str
    json_path: Path
    store_label: str
    source_file_count: int
    discovered_file_count: int
    ignored_file_count: int
    ignored_extensions: list[str]
    section_count: int
    indexed: bool


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "content"


def _read_text_file(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def _supported_files(path: Path) -> FileDiscovery:
    if path.is_file():
        ext = path.suffix.lower()
        if ext in SUPPORTED_EXTENSIONS and not path.name.startswith(IGNORED_FILE_PREFIXES):
            return FileDiscovery(files=[path], discovered_count=1, ignored_count=0, ignored_extensions=[])
        ignored_ext = "<hidden>" if path.name.startswith(IGNORED_FILE_PREFIXES) else (ext or "<none>")
        return FileDiscovery(files=[], discovered_count=1, ignored_count=1, ignored_extensions=[ignored_ext])

    if not path.is_dir():
        return FileDiscovery(files=[], discovered_count=0, ignored_count=0, ignored_extensions=[])

    files: list[Path] = []
    discovered_count = 0
    ignored_count = 0
    ignored_extensions: set[str] = set()

    for root, dir_names, file_names in os.walk(path, topdown=True):
        dir_names[:] = [
            name
            for name in dir_names
            if name not in IGNORED_DIR_NAMES and not name.startswith(".")
        ]

        root_path = Path(root)
        for file_name in sorted(file_names):
            discovered_count += 1
            if file_name.startswith(IGNORED_FILE_PREFIXES):
                ignored_count += 1
                ignored_extensions.add("<hidden>")
                continue

            candidate = root_path / file_name
            ext = candidate.suffix.lower()
            if ext in SUPPORTED_EXTENSIONS:
                files.append(candidate)
                continue

            ignored_count += 1
            ignored_extensions.add(ext or "<none>")

    return FileDiscovery(
        files=sorted(files),
        discovered_count=discovered_count,
        ignored_count=ignored_count,
        ignored_extensions=sorted(ignored_extensions),
    )

def _build_chunks(input_path: Path, files: list[Path]) -> tuple[list["Chunk"], list[str]]:
    from king_context.scraper.chunk import Chunk

    chunks: list[Chunk] = []
    relative_labels: list[str] = []

    for file_path in files:
        content = _read_text_file(file_path).strip()
        if not content:
            continue

        if input_path.is_dir():
            relative_label = file_path.relative_to(input_path).as_posix()
        else:
            relative_label = file_path.name

        stem = Path(relative_label).stem.replace("_", " ").replace("-", " ").strip()
        title = " ".join(word.capitalize() for word in stem.split()) if stem else (file_path.stem or "Content")
        slug = _slugify(Path(relative_label).with_suffix("").as_posix())

        chunks.append(
            Chunk(
                title=title,
                breadcrumb=title,
                content=content,
                source_url=relative_label,
                path=slug,
                token_count=int(len(content.split()) * 1.33),
            )
        )
        relative_labels.append(relative_label)

    return chunks, relative_labels


def _enrich_markdown_chunks(chunks: list["Chunk"]) -> list:
    config = load_config()
    if not config.openrouter_api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is required for kctx ingest. "
            "Add it to .env or .king-context/.env before ingesting content."
        )
    from king_context.scraper.enrich import enrich_chunks
    return asyncio.run(enrich_chunks(chunks, config))


def build_user_corpus(
    input_path: Path,
    *,
    name: str | None = None,
    display_name: str | None = None,
    source: str = "docs",
) -> tuple[dict, FileDiscovery]:
    discovery = _supported_files(input_path)
    if not discovery.files:
        raise FileNotFoundError(
            f"No supported files found under {input_path}. Supported extensions: .md"
        )

    doc_name = name or _slugify(input_path.stem if input_path.is_file() else input_path.name)
    doc_display_name = display_name or " ".join(
        part.capitalize() for part in doc_name.replace("_", "-").split("-") if part
    )

    chunks, relative_labels = _build_chunks(input_path, discovery.files)
    if not chunks:
        raise FileNotFoundError(f"No readable Markdown content found under {input_path}.")

    enriched_chunks = _enrich_markdown_chunks(chunks)
    if len(enriched_chunks) != len(relative_labels):
        raise RuntimeError(
            "Failed to enrich one or more Markdown files during kctx ingest. "
            "Please try again after checking your OPENROUTER_API_KEY and network access."
        )
    source_type = "research" if source == "research" else "user-content"
    sections = []
    for chunk, relative_label in zip(enriched_chunks, relative_labels, strict=True):
        sections.append(
            {
                "title": chunk.title,
                "path": chunk.path,
                "url": chunk.url,
                "keywords": chunk.keywords,
                "use_cases": chunk.use_cases,
                "tags": chunk.tags,
                "priority": chunk.priority,
                "content": chunk.content,
                "source_type": source_type,
                "source_file": relative_label,
            }
        )

    doc_data = {
        "name": doc_name,
        "display_name": doc_display_name,
        "version": "v1",
        "base_url": "",
        "sections": sections,
    }

    return doc_data, discovery


def ingest_path(
    input_path: Path,
    *,
    name: str | None = None,
    display_name: str | None = None,
    source: str = "docs",
    auto_index: bool = True,
    project_root: Path = PROJECT_ROOT,
    store_dir: Path = STORE_DIR,
    research_store_dir: Path = RESEARCH_STORE_DIR,
) -> IngestResult:
    source = "research" if source == "research" else "docs"
    doc_data, discovery = build_user_corpus(
        input_path,
        name=name,
        display_name=display_name,
        source=source,
    )

    if source == "research":
        json_path = project_root / ".king-context" / "data" / "research" / f"{doc_data['name']}.json"
        target_store = research_store_dir
    else:
        json_path = project_root / ".king-context" / "data" / f"{doc_data['name']}.json"
        target_store = store_dir

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(doc_data, indent=2, ensure_ascii=False))

    if auto_index:
        target_store.mkdir(parents=True, exist_ok=True)
        index_doc(json_path, target_store)

    return IngestResult(
        doc_name=doc_data["name"],
        display_name=doc_data["display_name"],
        json_path=json_path,
        store_label=source,
        source_file_count=len(doc_data["sections"]),
        discovered_file_count=discovery.discovered_count,
        ignored_file_count=discovery.ignored_count,
        ignored_extensions=discovery.ignored_extensions,
        section_count=len(doc_data["sections"]),
        indexed=auto_index,
    )
