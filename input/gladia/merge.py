#!/usr/bin/env python3
"""Merge all batch JSON files into a single gladia.json file."""

import json
import os
from pathlib import Path

INPUT_DIR = Path("/Users/dean/Documents/Projetos/mcp docs/input/gladia")
OUTPUT_FILE = Path("/Users/dean/Documents/Projetos/mcp docs/mcp-docs-server/data/gladia.json")

def find_batch_files(directory: Path) -> list[Path]:
    """Find all batch*.json files recursively."""
    return sorted(directory.rglob("batch*.json"))

def load_batch(filepath: Path) -> list[dict]:
    """Load a batch JSON file and return sections."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and 'sections' in data:
                return data['sections']
            else:
                print(f"  Warning: Unexpected format in {filepath}")
                return []
    except json.JSONDecodeError as e:
        print(f"  Error parsing {filepath}: {e}")
        return []

def validate_section(section: dict, filepath: Path) -> bool:
    """Validate a section has all required fields."""
    required = ['title', 'path', 'url', 'keywords', 'use_cases', 'tags', 'priority', 'content']
    missing = [f for f in required if f not in section]
    if missing:
        print(f"  Warning: Missing fields {missing} in section from {filepath}")
        return False
    return True

def main():
    print("=== Gladia Documentation Merge ===\n")

    # Find all batch files
    batch_files = find_batch_files(INPUT_DIR)
    print(f"Found {len(batch_files)} batch files:\n")

    all_sections = []
    urls_seen = set()

    for filepath in batch_files:
        relative_path = filepath.relative_to(INPUT_DIR)
        sections = load_batch(filepath)
        print(f"  {relative_path}: {len(sections)} sections")

        for section in sections:
            # Skip duplicates
            url = section.get('url', '')
            if url in urls_seen:
                print(f"    Skipping duplicate: {url}")
                continue
            urls_seen.add(url)

            # Validate
            validate_section(section, filepath)
            all_sections.append(section)

    # Sort by priority (highest first), then by path
    all_sections.sort(key=lambda s: (-s.get('priority', 5), s.get('path', '')))

    # Create final JSON
    output = {
        "name": "gladia",
        "display_name": "Gladia",
        "version": "v1",
        "base_url": "https://docs.gladia.io",
        "sections": all_sections
    }

    # Write output
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n=== Summary ===")
    print(f"Total sections: {len(all_sections)}")
    print(f"Unique URLs: {len(urls_seen)}")
    print(f"Output: {OUTPUT_FILE}")

    # Priority distribution
    priority_dist = {}
    for s in all_sections:
        p = s.get('priority', 0)
        priority_dist[p] = priority_dist.get(p, 0) + 1
    print(f"\nPriority distribution:")
    for p in sorted(priority_dist.keys(), reverse=True):
        print(f"  Priority {p}: {priority_dist[p]} sections")

if __name__ == "__main__":
    main()
