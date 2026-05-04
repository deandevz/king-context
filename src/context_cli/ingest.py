"""Ingest local user-provided content into King Context JSON corpora."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from context_cli import PROJECT_ROOT, RESEARCH_STORE_DIR, STORE_DIR
from context_cli.indexer import index_doc


SUPPORTED_EXTENSIONS = {".md", ".txt", ".srt", ".vtt", ".pdf"}
TRANSCRIPT_EXTENSIONS = {".srt", ".vtt"}
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
BINARY_EXTENSIONS = {
    ".7z",
    ".bin",
    ".class",
    ".dll",
    ".dylib",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".mp3",
    ".mp4",
    ".mov",
    ".png",
    ".pyc",
    ".so",
    ".tar",
    ".wav",
    ".webm",
    ".zip",
}


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


def _titleize_slug(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.replace("_", "-").split("-") if part)


def _read_text_file(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def _read_pdf_file(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "PDF ingestion requires the 'pypdf' package. "
            "Install a build of king-context with PDF support, or run: pip install pypdf"
        ) from exc

    reader = PdfReader(str(path))
    pages: list[str] = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(text)
    return "\n\n".join(pages)


def _read_file_content(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return _read_pdf_file(path)
    return _read_text_file(path)


def _classify_extension(ext: str) -> str:
    if ext == ".md":
        return "markdown"
    if ext in TRANSCRIPT_EXTENSIONS:
        return "transcript"
    if ext == ".pdf":
        return "pdf"
    return "text"


def _should_ignore_file_name(file_name: str) -> bool:
    return file_name.startswith(IGNORED_FILE_PREFIXES)


def _supported_files(path: Path) -> FileDiscovery:
    if path.is_file():
        ext = path.suffix.lower()
        if ext in SUPPORTED_EXTENSIONS:
            return FileDiscovery(files=[path], discovered_count=1, ignored_count=0, ignored_extensions=[])
        return FileDiscovery(files=[], discovered_count=1, ignored_count=1, ignored_extensions=[ext or "<none>"])

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
            if _should_ignore_file_name(file_name):
                ignored_count += 1
                ignored_extensions.add("<hidden>")
                continue

            candidate = root_path / file_name
            ext = candidate.suffix.lower()
            if ext in SUPPORTED_EXTENSIONS:
                files.append(candidate)
                continue

            ignored_count += 1
            if ext in BINARY_EXTENSIONS:
                ignored_extensions.add(ext)
            else:
                ignored_extensions.add(ext or "<none>")

    return FileDiscovery(
        files=sorted(files),
        discovered_count=discovered_count,
        ignored_count=ignored_count,
        ignored_extensions=sorted(ignored_extensions),
    )


def _relative_label(base_path: Path, file_path: Path) -> str:
    if base_path.is_dir():
        rel = file_path.relative_to(base_path)
    else:
        rel = Path(file_path.name)
    return rel.as_posix()


def _file_title(file_path: Path, relative_label: str) -> str:
    stem = Path(relative_label).stem.replace("_", " ").replace("-", " ").strip()
    if stem:
        return " ".join(word.capitalize() for word in stem.split())
    return file_path.stem or "Content"


def _build_markdown(ext: str, title: str, content: str) -> str:
    if ext == ".md":
        return content
    return f"## {title}\n\n{content.strip()}\n"


def _tags_for_extension(ext: str) -> list[str]:
    kind = _classify_extension(ext)
    if kind == "transcript":
        return ["user-content", "transcript"]
    return ["user-content", kind]


def _keywords_for_chunk(relative_label: str, title: str, ext: str) -> list[str]:
    raw_parts = [relative_label, title, ext.lstrip(".")]
    text = " ".join(raw_parts).lower()
    words = re.findall(r"[a-z0-9]{3,}", text)
    seen: list[str] = []
    for word in words:
        if word not in seen:
            seen.append(word)
    return seen[:12] or ["content"]


def _use_case_for_file(relative_label: str) -> list[str]:
    return [f"Reference user-provided content from {relative_label}"]


def _estimate_tokens(text: str) -> int:
    return int(len(text.split()) * 1.33)


def _split_paragraphs(content: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n+", content) if part.strip()]


def _split_markdown_sections(markdown: str, fallback_title: str) -> list[tuple[str, str]]:
    lines = markdown.splitlines()
    splits: list[tuple[int, str]] = []
    in_code_block = False

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
        if in_code_block:
            continue
        if line.startswith("### "):
            splits.append((idx, line[4:].strip()))
        elif line.startswith("## "):
            splits.append((idx, line[3:].strip()))

    if not splits:
        content = markdown.strip()
        return [(fallback_title, content)] if content else []

    sections: list[tuple[str, str]] = []
    for idx, (start_line, title) in enumerate(splits):
        end_line = splits[idx + 1][0] if idx + 1 < len(splits) else len(lines)
        content = "\n".join(lines[start_line + 1:end_line]).strip()
        if content:
            sections.append((title or fallback_title, content))
    return sections


def _subdivide_content(title: str, content: str, chunk_max_tokens: int) -> list[tuple[str, str]]:
    if _estimate_tokens(content) <= chunk_max_tokens:
        return [(title, content)]

    paragraphs = _split_paragraphs(content)
    if len(paragraphs) <= 1:
        return [(title, content)]

    parts: list[tuple[str, str]] = []
    current = ""

    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if _estimate_tokens(candidate) > chunk_max_tokens and current:
            parts.append((title, current.strip()))
            current = paragraph
        else:
            current = candidate

    if current.strip():
        parts.append((title, current.strip()))
    return parts or [(title, content)]


def _merge_small_sections(
    sections: list[tuple[str, str]],
    chunk_min_tokens: int,
) -> list[tuple[str, str]]:
    merged: list[tuple[str, str]] = []
    for title, content in sections:
        if _estimate_tokens(content) < chunk_min_tokens and merged:
            prev_title, prev_content = merged[-1]
            merged[-1] = (prev_title, f"{prev_content}\n\n{content}".strip())
        else:
            merged.append((title, content))
    return merged


def _sections_from_file(
    file_path: Path,
    *,
    base_path: Path,
    collection_name: str,
    source: str,
    chunk_max_tokens: int,
    chunk_min_tokens: int,
) -> list[dict]:
    relative_label = _relative_label(base_path, file_path)
    title = _file_title(file_path, relative_label)
    content = _read_file_content(file_path).strip()
    if not content:
        return []

    ext = file_path.suffix.lower()
    source_kind = _classify_extension(ext)
    markdown = _build_markdown(ext, title, content)
    raw_sections = _split_markdown_sections(markdown, title)
    sized_sections: list[tuple[str, str]] = []
    for section_title, section_content in raw_sections:
        sized_sections.extend(_subdivide_content(section_title, section_content, chunk_max_tokens))
    chunks = _merge_small_sections(sized_sections, chunk_min_tokens)

    if not chunks:
        return []

    file_slug = _slugify(Path(relative_label).with_suffix("").as_posix())
    tags = _tags_for_extension(ext)
    use_cases = _use_case_for_file(relative_label)

    sections: list[dict] = []
    used_paths: set[str] = set()

    for idx, (section_title, section_content) in enumerate(chunks, 1):
        section_slug = _slugify(section_title)
        path = file_slug if len(chunks) == 1 else f"{file_slug}-{section_slug}"
        if path in used_paths:
            path = f"{path}-{idx}"
        used_paths.add(path)

        sections.append(
            {
                "title": section_title,
                "path": path,
                "url": relative_label,
                "keywords": _keywords_for_chunk(relative_label, section_title, ext),
                "use_cases": use_cases,
                "tags": tags,
                "priority": 5,
                "content": section_content.strip(),
                "source_type": "research" if source == "research" else "user-content",
                "source_file": relative_label,
                "source_format": ext.lstrip(".") or "text",
                "source_collection": collection_name,
                "source_kind": source_kind,
            }
        )

    return sections


def build_user_corpus(
    input_path: Path,
    *,
    name: str | None = None,
    display_name: str | None = None,
    source: str = "docs",
    chunk_max_tokens: int = 800,
    chunk_min_tokens: int = 50,
) -> tuple[dict, FileDiscovery]:
    discovery = _supported_files(input_path)
    if not discovery.files:
        raise FileNotFoundError(
            f"No supported files found under {input_path}. "
            "Supported extensions: .md, .txt, .srt, .vtt, .pdf"
        )

    doc_name = name or _slugify(input_path.stem if input_path.is_file() else input_path.name)
    doc_display_name = display_name or _titleize_slug(doc_name)

    sections: list[dict] = []
    for file_path in discovery.files:
        sections.extend(
            _sections_from_file(
                file_path,
                base_path=input_path,
                collection_name=doc_name,
                source=source,
                chunk_max_tokens=chunk_max_tokens,
                chunk_min_tokens=chunk_min_tokens,
            )
        )

    data = {
        "name": doc_name,
        "display_name": doc_display_name,
        "version": "v1",
        "base_url": "",
        "sections": sections,
    }
    return data, discovery


def ingest_path(
    input_path: Path,
    *,
    name: str | None = None,
    display_name: str | None = None,
    source: str = "docs",
    chunk_max_tokens: int = 800,
    chunk_min_tokens: int = 50,
    auto_index: bool = True,
) -> IngestResult:
    source = "research" if source == "research" else "docs"
    doc_data, discovery = build_user_corpus(
        input_path,
        name=name,
        display_name=display_name,
        source=source,
        chunk_max_tokens=chunk_max_tokens,
        chunk_min_tokens=chunk_min_tokens,
    )

    if source == "research":
        json_path = PROJECT_ROOT / ".king-context" / "data" / "research" / f"{doc_data['name']}.json"
        store_dir = RESEARCH_STORE_DIR
    else:
        json_path = PROJECT_ROOT / ".king-context" / "data" / f"{doc_data['name']}.json"
        store_dir = STORE_DIR

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(doc_data, indent=2, ensure_ascii=False))

    if auto_index:
        store_dir.mkdir(parents=True, exist_ok=True)
        index_doc(json_path, store_dir)

    return IngestResult(
        doc_name=doc_data["name"],
        display_name=doc_data["display_name"],
        json_path=json_path,
        store_label=source,
        source_file_count=len(discovery.files),
        discovered_file_count=discovery.discovered_count,
        ignored_file_count=discovery.ignored_count,
        ignored_extensions=discovery.ignored_extensions,
        section_count=len(doc_data["sections"]),
        indexed=auto_index,
    )
