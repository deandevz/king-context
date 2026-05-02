"""Tests for installer scaffolding shared by install, update, and doctor."""

import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_doctor_uses_scaffold_directory_contract():
    doctor = Path("installer/lib/doctor.js").read_text(encoding="utf-8")

    assert "expectedDirPaths" in doctor
    assert "const expectedDirs = [" not in doctor


def test_doctor_uses_skill_template_contract():
    doctor = Path("installer/lib/doctor.js").read_text(encoding="utf-8")

    assert "expectedSkillPaths" in doctor
    assert ".claude/skills/king-context/skill.md" not in doctor


def test_expected_skill_paths_follow_template_directories():
    script = """
const { expectedSkillPaths } = require('./installer/lib/skills');
console.log(JSON.stringify(expectedSkillPaths()));
"""

    result = subprocess.run(
        ["node", "-e", script],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    skills = json.loads(result.stdout)
    names = {skill["name"] for skill in skills}
    template_names = {
        path.parent.name
        for path in (REPO_ROOT / "installer" / "templates" / "skills").glob("*/skill.md")
    }
    assert names == template_names
    assert "king-decisions" in names
    assert "king-record-decision" in names


def test_update_creates_missing_directories_for_existing_install(tmp_path):
    king_dir = tmp_path / ".king-context"
    king_dir.mkdir()
    (king_dir / "data").mkdir()
    (king_dir / "docs").mkdir()

    script = """
const path = require('path');
const repoRoot = process.argv[1];
const projectDir = process.argv[2];

const pythonPath = require.resolve(path.join(repoRoot, 'installer/lib/python.js'));
require.cache[pythonPath] = {
  id: pythonPath,
  filename: pythonPath,
  loaded: true,
  exports: {
    upgradePackage() {},
  },
};

const skillsPath = require.resolve(path.join(repoRoot, 'installer/lib/skills.js'));
require.cache[skillsPath] = {
  id: skillsPath,
  filename: skillsPath,
  loaded: true,
  exports: {
    installSkills() {},
    mergeSettings() {},
  },
};

process.chdir(projectDir);
Promise.resolve(require(path.join(repoRoot, 'installer/lib/update.js')).run()).catch((err) => {
  console.error(err);
  process.exit(1);
});
"""

    subprocess.run(
        ["node", "-e", script, str(REPO_ROOT), str(tmp_path)],
        cwd=REPO_ROOT,
        check=True,
    )

    for dirname in [
        "bin",
        "core",
        "data",
        "docs",
        "adr",
        "decisions",
        "research",
        "_learned",
        "_temp",
    ]:
        assert (king_dir / dirname).is_dir()
