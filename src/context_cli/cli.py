"""CLI entry point for kctx."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from context_cli import PROJECT_ROOT, RESEARCH_STORE_DIR, STORE_DIR
from context_cli.formatter import (
    format_grep,
    format_list,
    format_search,
    format_section,
    format_topics,
)
from context_cli.grep import grep_docs
from context_cli.indexer import index_doc
from context_cli.reader import read_section
from context_cli.searcher import search
from context_cli.store import list_docs


SOURCE_CHOICES = ("all", "docs", "research")


def _active_stores(source: str) -> list[tuple[str, Path]]:
    """Return [(label, store_dir), ...] the given source selector targets."""
    if source == "docs":
        return [("docs", STORE_DIR)]
    if source == "research":
        return [("research", RESEARCH_STORE_DIR)]
    return [("docs", STORE_DIR), ("research", RESEARCH_STORE_DIR)]


def _find_doc_store(doc_name: str, source: str) -> Path | None:
    """Find which store contains a given doc_name. Returns None if not found."""
    for _, store_dir in _active_stores(source):
        if (store_dir / doc_name / "index.json").exists():
            return store_dir
    return None


def _detect_source(json_path: Path) -> str:
    """Inspect the JSON at json_path and classify as 'research' or 'docs'."""
    try:
        data = json.loads(json_path.read_text())
        sections = data.get("sections", [])
        if any(s.get("source_type") == "research" for s in sections):
            return "research"
    except (json.JSONDecodeError, OSError, KeyError):
        pass
    return "docs"


def _cmd_list(args: argparse.Namespace) -> None:
    source = args.source or "all"
    stores = _active_stores(source)

    if args.json:
        payload = {label: [asdict(d) for d in list_docs(s)] for label, s in stores}
        if source != "all":
            print(json.dumps(payload[source], indent=2))
        else:
            print(json.dumps(payload, indent=2))
        return

    blocks: list[str] = []
    total = 0
    for label, store_dir in stores:
        docs = list_docs(store_dir)
        total += len(docs)
        if not docs:
            continue
        header = f"== {label.title()} ({len(docs)}) =="
        blocks.append(header + "\n" + format_list(docs))

    if total == 0:
        print("No docs indexed. Run: king-scrape <url>  or  king-research <topic>")
        return

    print("\n\n".join(blocks))


def _cmd_search(args: argparse.Namespace) -> None:
    source = args.source or "all"
    stores = _active_stores(source)

    all_results = []
    for label, store_dir in stores:
        if args.doc is not None and not (store_dir / args.doc / "index.json").exists():
            continue
        all_results.extend(
            search(args.query, store_dir, doc_name=args.doc, top=args.top, source=label)
        )

    all_results.sort(key=lambda r: r.score, reverse=True)
    all_results = all_results[: args.top]
    print(format_search(all_results, as_json=args.json))


def _cmd_read(args: argparse.Namespace) -> None:
    source = args.source or "all"
    target_store = _find_doc_store(args.doc, source)
    if target_store is None:
        stores = ", ".join(label for label, _ in _active_stores(source))
        print(
            f"Doc '{args.doc}' not found in {stores} store(s).",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        content = read_section(
            args.doc,
            args.section,
            target_store,
            preview=args.preview,
        )
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    print(format_section(content, as_json=args.json))


def _cmd_grep(args: argparse.Namespace) -> None:
    source = args.source or "all"
    stores = _active_stores(source)

    all_matches = []
    for label, store_dir in stores:
        if args.doc is not None and not (store_dir / args.doc / "index.json").exists():
            continue
        all_matches.extend(
            grep_docs(args.pattern, store_dir, doc_name=args.doc,
                      context_lines=args.context, source=label)
        )
    print(format_grep(all_matches, as_json=args.json))


def _cmd_topics(args: argparse.Namespace) -> None:
    source = args.source or "all"
    target_store = _find_doc_store(args.doc, source)
    if target_store is None:
        available: list[str] = []
        for _, store_dir in _active_stores(source):
            available.extend(d.name for d in list_docs(store_dir))
        available_str = ", ".join(available) if available else "none"
        print(
            f"Doc '{args.doc}' not found. Available: {available_str}",
            file=sys.stderr,
        )
        sys.exit(1)

    doc_dir = target_store / args.doc
    tags_path = doc_dir / "tags.json"
    if not tags_path.exists():
        print(format_topics({}, as_json=args.json))
        return

    tags_index: dict[str, list[str]] = json.loads(tags_path.read_text())

    if args.tag:
        if args.tag in tags_index:
            tags_index = {args.tag: tags_index[args.tag]}
        else:
            tags_index = {}

    tag_groups: dict[str, list[dict]] = {}
    sections_dir = doc_dir / "sections"

    for tag, section_paths in tags_index.items():
        sections = []
        for spath in section_paths:
            sec_file = sections_dir / f"{spath}.json"
            if sec_file.exists():
                sec_data = json.loads(sec_file.read_text())
                sections.append({
                    "title": sec_data.get("title", ""),
                    "path": sec_data.get("path", spath),
                    "priority": sec_data.get("priority", 0),
                })
        sections.sort(key=lambda s: s["priority"], reverse=True)
        tag_groups[tag] = sections

    print(format_topics(tag_groups, as_json=args.json))


def _resolve_index_store(json_path: Path, args: argparse.Namespace) -> tuple[str, Path]:
    """Pick the target store for a given index command invocation."""
    if args.source == "docs":
        return "docs", STORE_DIR
    if args.source == "research":
        return "research", RESEARCH_STORE_DIR
    label = _detect_source(json_path)
    return label, (RESEARCH_STORE_DIR if label == "research" else STORE_DIR)


def _cmd_index(args: argparse.Namespace) -> None:
    if args.all:
        data_root = PROJECT_ROOT / ".king-context" / "data"
        if not data_root.exists():
            print(".king-context/data/ directory not found.", file=sys.stderr)
            sys.exit(1)

        candidates = list(data_root.glob("*.json"))
        research_dir = data_root / "research"
        if research_dir.exists():
            candidates.extend(research_dir.glob("*.json"))

        if not candidates:
            print("No JSON files found in .king-context/data/.")
            return

        for json_path in sorted(candidates):
            label, target_store = _resolve_index_store(json_path, args)
            target_store.mkdir(parents=True, exist_ok=True)
            result = index_doc(json_path, target_store)
            print(f"Indexed {result.doc_name} ({label}): {result.section_count} sections")
    else:
        json_path = Path(args.path)
        if not json_path.exists():
            print(f"File not found: {args.path}", file=sys.stderr)
            sys.exit(1)
        label, target_store = _resolve_index_store(json_path, args)
        target_store.mkdir(parents=True, exist_ok=True)
        result = index_doc(json_path, target_store)
        print(f"Indexed {result.doc_name} ({label}): {result.section_count} sections")


def _add_source_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--source",
        choices=SOURCE_CHOICES,
        default="all",
        help="Which store(s) to target: docs, research, or all (default: all)",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kctx",
        description="File-based documentation search for AI agents",
    )
    parser.add_argument(
        "--version", action="version", version="kctx 0.1.0"
    )
    subparsers = parser.add_subparsers(dest="command")

    # list [source]
    p_list = subparsers.add_parser("list", help="List indexed documentation")
    p_list.add_argument(
        "source",
        nargs="?",
        choices=SOURCE_CHOICES,
        default="all",
        help="Filter by store: docs, research, or all (default: all)",
    )
    p_list.add_argument("--json", action="store_true", help="JSON output")
    p_list.set_defaults(func=_cmd_list)

    # search
    p_search = subparsers.add_parser("search", help="Search docs by keywords/use cases")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--doc", default=None, help="Restrict to one doc")
    p_search.add_argument("--top", type=int, default=5, help="Max results (default: 5)")
    _add_source_arg(p_search)
    p_search.add_argument("--json", action="store_true", help="JSON output")
    p_search.set_defaults(func=_cmd_search)

    # read
    p_read = subparsers.add_parser("read", help="Read a specific section")
    p_read.add_argument("doc", help="Documentation name")
    p_read.add_argument("section", help="Section path")
    p_read.add_argument("--preview", action="store_true", help="Show first ~200 tokens only")
    _add_source_arg(p_read)
    p_read.add_argument("--json", action="store_true", help="JSON output")
    p_read.set_defaults(func=_cmd_read)

    # grep
    p_grep = subparsers.add_parser("grep", help="Search content with regex patterns")
    p_grep.add_argument("pattern", help="Regex pattern to search for")
    p_grep.add_argument("--doc", default=None, help="Restrict to one doc")
    p_grep.add_argument("--context", type=int, default=0, help="Surrounding lines")
    _add_source_arg(p_grep)
    p_grep.add_argument("--json", action="store_true", help="JSON output")
    p_grep.set_defaults(func=_cmd_grep)

    # topics
    p_topics = subparsers.add_parser("topics", help="Show tags and sections for a doc")
    p_topics.add_argument("doc", help="Documentation name")
    p_topics.add_argument("--tag", default=None, help="Filter to a single tag")
    _add_source_arg(p_topics)
    p_topics.add_argument("--json", action="store_true", help="JSON output")
    p_topics.set_defaults(func=_cmd_topics)

    # index
    p_index = subparsers.add_parser("index", help="Index documentation from JSON files")
    p_index.add_argument("path", nargs="?", default=None, help="Path to a JSON file")
    p_index.add_argument("--all", action="store_true",
                         help="Index all .king-context/data/*.json files (including research/)")
    p_index.add_argument(
        "--source",
        choices=SOURCE_CHOICES,
        default="all",
        help="Force routing to a specific store (default: auto-detect from source_type)",
    )
    p_index.set_defaults(func=_cmd_index)

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
