"""CLI entry point for kctx."""

import argparse
import json
import sys
from pathlib import Path

from context_cli import PROJECT_ROOT, STORE_DIR
from context_cli.formatter import (
    format_grep,
    format_list,
    format_search,
    format_section,
)
from context_cli.formatter import format_topics
from context_cli.grep import grep_docs
from context_cli.indexer import index_all, index_doc
from context_cli.reader import read_section
from context_cli.searcher import search
from context_cli.store import doc_exists, list_docs


def _cmd_list(args: argparse.Namespace) -> None:
    store_dir = STORE_DIR
    docs = list_docs(store_dir)
    if not docs and not args.json:
        print("No docs indexed. Run: kctx index data/<file>.json")
        return
    print(format_list(docs, as_json=args.json))


def _cmd_search(args: argparse.Namespace) -> None:
    store_dir = STORE_DIR
    results = search(
        args.query,
        store_dir,
        doc_name=args.doc,
        top=args.top,
    )
    print(format_search(results, as_json=args.json))


def _cmd_read(args: argparse.Namespace) -> None:
    store_dir = STORE_DIR
    try:
        content = read_section(
            args.doc,
            args.section,
            store_dir,
            preview=args.preview,
        )
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    print(format_section(content, as_json=args.json))


def _cmd_grep(args: argparse.Namespace) -> None:
    store_dir = STORE_DIR
    matches = grep_docs(
        args.pattern,
        store_dir,
        doc_name=args.doc,
        context_lines=args.context,
    )
    print(format_grep(matches, as_json=args.json))


def _cmd_topics(args: argparse.Namespace) -> None:
    store_dir = STORE_DIR
    doc_name = args.doc

    if not doc_exists(doc_name, store_dir):
        docs = list_docs(store_dir)
        available = ", ".join(d.name for d in docs) if docs else "none"
        print(
            f"Doc '{doc_name}' not found. Available: {available}",
            file=sys.stderr,
        )
        sys.exit(1)

    doc_dir = store_dir / doc_name
    tags_path = doc_dir / "tags.json"
    if not tags_path.exists():
        print(format_topics({}, as_json=args.json))
        return

    tags_index: dict[str, list[str]] = json.loads(tags_path.read_text())

    # Optionally filter to a single tag
    if args.tag:
        if args.tag in tags_index:
            tags_index = {args.tag: tags_index[args.tag]}
        else:
            tags_index = {}

    # Load section metadata for each tag
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
        # Sort by priority descending
        sections.sort(key=lambda s: s["priority"], reverse=True)
        tag_groups[tag] = sections

    print(format_topics(tag_groups, as_json=args.json))


def _cmd_index(args: argparse.Namespace) -> None:
    store_dir = STORE_DIR
    store_dir.mkdir(parents=True, exist_ok=True)

    if args.all:
        data_dir = PROJECT_ROOT / "data"
        if not data_dir.exists():
            print("data/ directory not found.", file=sys.stderr)
            sys.exit(1)
        results = index_all(data_dir, store_dir)
        for r in results:
            print(f"Indexed {r.doc_name}: {r.section_count} sections")
        if not results:
            print("No JSON files found in data/.")
    else:
        json_path = Path(args.path)
        if not json_path.exists():
            print(f"File not found: {args.path}", file=sys.stderr)
            sys.exit(1)
        result = index_doc(json_path, store_dir)
        print(f"Indexed {result.doc_name}: {result.section_count} sections")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kctx",
        description="File-based documentation search for AI agents",
    )
    parser.add_argument(
        "--version", action="version", version="kctx 0.1.0"
    )
    subparsers = parser.add_subparsers(dest="command")

    # list
    p_list = subparsers.add_parser("list", help="List indexed documentation")
    p_list.add_argument("--json", action="store_true", help="JSON output")
    p_list.set_defaults(func=_cmd_list)

    # search
    p_search = subparsers.add_parser("search", help="Search docs by keywords/use cases")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--doc", default=None, help="Restrict to one doc")
    p_search.add_argument("--top", type=int, default=5, help="Max results (default: 5)")
    p_search.add_argument("--json", action="store_true", help="JSON output")
    p_search.set_defaults(func=_cmd_search)

    # read
    p_read = subparsers.add_parser("read", help="Read a specific section")
    p_read.add_argument("doc", help="Documentation name")
    p_read.add_argument("section", help="Section path")
    p_read.add_argument("--preview", action="store_true", help="Show first ~200 tokens only")
    p_read.add_argument("--json", action="store_true", help="JSON output")
    p_read.set_defaults(func=_cmd_read)

    # grep
    p_grep = subparsers.add_parser("grep", help="Search content with regex patterns")
    p_grep.add_argument("pattern", help="Regex pattern to search for")
    p_grep.add_argument("--doc", default=None, help="Restrict to one doc")
    p_grep.add_argument("--context", type=int, default=0, help="Surrounding lines")
    p_grep.add_argument("--json", action="store_true", help="JSON output")
    p_grep.set_defaults(func=_cmd_grep)

    # topics
    p_topics = subparsers.add_parser("topics", help="Show tags and sections for a doc")
    p_topics.add_argument("doc", help="Documentation name")
    p_topics.add_argument("--tag", default=None, help="Filter to a single tag")
    p_topics.add_argument("--json", action="store_true", help="JSON output")
    p_topics.set_defaults(func=_cmd_topics)

    # index
    p_index = subparsers.add_parser("index", help="Index documentation from JSON files")
    p_index.add_argument("path", nargs="?", default=None, help="Path to a JSON file")
    p_index.add_argument("--all", action="store_true", help="Index all data/*.json files")
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
