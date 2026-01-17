"""
Script para indexar JSONs de documentação no banco.
Lê arquivos de data/*.json e insere no SQLite.
"""

import json
from pathlib import Path

from db import init_db, insert_documentation

DATA_DIR = Path(__file__).parent / "data"


def seed_all() -> None:
    """Read all .json files from DATA_DIR and insert into database.

    Prints progress for each file processed.
    Handles empty data directory gracefully.
    """
    json_files = list(DATA_DIR.glob("*.json"))

    for json_file in json_files:
        with open(json_file, "r", encoding="utf-8") as f:
            doc_data = json.load(f)

        insert_documentation(doc_data)
        num_sections = len(doc_data.get("sections", []))
        print(f"Seeding {json_file.name}... done ({num_sections} sections)")


def seed_one(json_path: Path) -> None:
    """Index a single JSON documentation file into the database.

    Useful for adding a new doc without re-indexing everything.

    Args:
        json_path: Path to the JSON file to index.
    """
    with open(json_path, "r", encoding="utf-8") as f:
        doc_data = json.load(f)

    insert_documentation(doc_data)
    num_sections = len(doc_data.get("sections", []))
    print(f"Seeding {json_path.name}... done ({num_sections} sections)")


if __name__ == "__main__":
    init_db()
    seed_all()
