import os
from pathlib import Path

from dotenv import dotenv_values


def _apply_env_file(path: Path, *, override: bool, protected: set[str]) -> None:
    for key, value in dotenv_values(path).items():
        if value is None:
            continue
        if key in protected:
            continue
        if override or key not in os.environ:
            os.environ[key] = value


def load_project_env(project_root: Path | None = None) -> None:
    """Load installer and project env files for CLI entry points."""
    if os.environ.get("KING_CONTEXT_DISABLE_DOTENV", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return

    root = project_root if project_root is not None else Path.cwd()
    protected = set(os.environ)

    installer_env = root / ".king-context" / ".env"
    if installer_env.exists():
        _apply_env_file(installer_env, override=False, protected=protected)

    developer_env = root / ".env"
    if developer_env.exists():
        _apply_env_file(developer_env, override=True, protected=protected)
