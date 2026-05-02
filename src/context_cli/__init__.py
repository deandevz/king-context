"""Context CLI - File-based documentation search for AI agents."""

from pathlib import Path

PROJECT_ROOT = Path.cwd()
STORE_DIR = PROJECT_ROOT / ".king-context" / "docs"
RESEARCH_STORE_DIR = PROJECT_ROOT / ".king-context" / "research"
DECISIONS_STORE_DIR = PROJECT_ROOT / ".king-context" / "decisions"
