"""Tests for installer .gitignore updates."""

import subprocess
from pathlib import Path


def _run_update_gitignore(project_dir: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = """
const { updateGitignore } = require('./installer/lib/skills');
updateGitignore(process.argv[1]);
"""
    subprocess.run(
        ["node", "-e", script, str(project_dir)],
        cwd=repo_root,
        check=True,
    )


def test_update_gitignore_adds_missing_entries_to_existing_king_context_block(tmp_path):
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(
        "\n".join(
            [
                "node_modules/",
                "",
                "# King Context",
                ".king-context/core/",
                ".king-context/docs/",
                ".king-context/research/",
                ".king-context/data/",
                ".king-context/_temp/",
                ".king-context/_learned/",
                "",
            ]
        ),
        encoding="utf-8",
    )

    _run_update_gitignore(tmp_path)
    _run_update_gitignore(tmp_path)

    updated = gitignore.read_text(encoding="utf-8")
    assert updated.count("# King Context") == 1
    assert updated.count(".king-context/decisions/") == 1
