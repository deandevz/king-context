import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from king_context.scraper.config import ScraperConfig


@dataclass
class Chunk:
    title: str
    breadcrumb: str
    content: str
    source_url: str
    path: str
    token_count: int


def _estimate_tokens(text: str) -> int:
    return int(len(text.split()) * 1.33)


def _title_to_slug(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug or "section"


def _make_path(source_url: str, title: str) -> str:
    parsed = urlparse(source_url)
    base_path = parsed.path.rstrip("/") if parsed.scheme else source_url.rstrip("/")
    slug = _title_to_slug(title)
    return f"{base_path}/{slug}"


def _split_paragraphs_respecting_tables(content: str) -> list[str]:
    """Split by double newlines, keeping table blocks intact."""
    raw = re.split(r"\n\n+", content)
    result: list[str] = []
    table_buf: list[str] = []

    for para in raw:
        stripped = para.strip()
        if not stripped:
            continue
        lines = [l for l in stripped.split("\n") if l.strip()]
        is_table = lines and all(l.strip().startswith("|") for l in lines)

        if is_table:
            table_buf.append(stripped)
        else:
            if table_buf:
                result.append("\n\n".join(table_buf))
                table_buf = []
            result.append(stripped)

    if table_buf:
        result.append("\n\n".join(table_buf))

    return result


def _subdivide_chunk(chunk: "Chunk", config: ScraperConfig) -> list["Chunk"]:
    """Split an oversized chunk by paragraphs."""
    paragraphs = _split_paragraphs_respecting_tables(chunk.content)
    if len(paragraphs) <= 1:
        return [chunk]

    sub_chunks: list[Chunk] = []
    current = ""

    for para in paragraphs:
        candidate = (current + "\n\n" + para).strip() if current else para
        if _estimate_tokens(candidate) > config.chunk_max_tokens and current:
            sub_chunks.append(Chunk(
                title=chunk.title,
                breadcrumb=chunk.breadcrumb,
                content=current,
                source_url=chunk.source_url,
                path=chunk.path,
                token_count=_estimate_tokens(current),
            ))
            current = para
        else:
            current = candidate

    if current:
        sub_chunks.append(Chunk(
            title=chunk.title,
            breadcrumb=chunk.breadcrumb,
            content=current,
            source_url=chunk.source_url,
            path=chunk.path,
            token_count=_estimate_tokens(current),
        ))

    return sub_chunks if sub_chunks else [chunk]


def chunk_page(markdown: str, source_url: str, config: ScraperConfig) -> list[Chunk]:
    """Split a Markdown page into chunks at h2/h3 boundaries."""
    lines = markdown.split("\n")

    # Find header split points, skipping those inside code blocks
    splits: list[tuple[int, str, int]] = []
    in_code_block = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
        if not in_code_block:
            if line.startswith("### "):
                splits.append((i, line[4:].strip(), 3))
            elif line.startswith("## "):
                splits.append((i, line[3:].strip(), 2))

    if not splits:
        content = markdown.strip()
        if not content:
            return []
        return [Chunk(
            title="",
            breadcrumb="",
            content=content,
            source_url=source_url,
            path=_make_path(source_url, "content"),
            token_count=_estimate_tokens(content),
        )]

    # Build raw chunks from header positions
    current_h2 = ""
    raw_chunks: list[Chunk] = []

    for idx, (line_idx, title, level) in enumerate(splits):
        end_line = splits[idx + 1][0] if idx + 1 < len(splits) else len(lines)
        content = "\n".join(lines[line_idx + 1:end_line]).strip()

        if level == 2:
            current_h2 = title
            breadcrumb = title
        else:
            breadcrumb = f"{current_h2} > {title}" if current_h2 else title

        raw_chunks.append(Chunk(
            title=title,
            breadcrumb=breadcrumb,
            content=content,
            source_url=source_url,
            path=_make_path(source_url, title),
            token_count=_estimate_tokens(content),
        ))

    # Subdivide large chunks
    sized: list[Chunk] = []
    for chunk in raw_chunks:
        if chunk.token_count > config.chunk_max_tokens:
            sized.extend(_subdivide_chunk(chunk, config))
        else:
            sized.append(chunk)

    # Merge small chunks with previous
    merged: list[Chunk] = []
    for chunk in sized:
        if chunk.token_count < config.chunk_min_tokens and merged:
            prev = merged[-1]
            new_content = prev.content + "\n\n" + chunk.content
            merged[-1] = Chunk(
                title=prev.title,
                breadcrumb=prev.breadcrumb,
                content=new_content.strip(),
                source_url=prev.source_url,
                path=prev.path,
                token_count=_estimate_tokens(new_content.strip()),
            )
        else:
            merged.append(chunk)

    return merged


def chunk_pages(pages_dir: Path, output_dir: Path, config: ScraperConfig) -> list[Chunk]:
    """Process all .md files in pages_dir and save per-page chunk JSONs."""
    chunks_dir = output_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    all_chunks: list[Chunk] = []

    for md_file in sorted(pages_dir.glob("*.md")):
        markdown = md_file.read_text()
        slug = md_file.stem
        page_chunks = chunk_page(markdown, slug, config)
        all_chunks.extend(page_chunks)

        chunk_data = [
            {
                "title": c.title,
                "breadcrumb": c.breadcrumb,
                "content": c.content,
                "source_url": c.source_url,
                "path": c.path,
                "token_count": c.token_count,
            }
            for c in page_chunks
        ]
        (chunks_dir / f"{slug}.json").write_text(json.dumps(chunk_data, indent=2))

    return all_chunks
