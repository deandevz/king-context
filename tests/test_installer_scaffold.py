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


def test_write_wrappers_uses_python_modules_on_unix(tmp_path):
    script = """
Object.defineProperty(process, 'platform', { value: 'linux' });
const { writeWrappers } = require('./installer/lib/scaffold');
process.chdir(process.argv[1]);
writeWrappers(process.argv[1]);
"""

    subprocess.run(
        ["node", "-e", script, str(tmp_path)],
        cwd=REPO_ROOT,
        check=True,
    )

    kctx = (tmp_path / ".king-context" / "bin" / "kctx").read_text(encoding="utf-8")
    scrape = (tmp_path / ".king-context" / "bin" / "king-scrape").read_text(encoding="utf-8")
    research = (tmp_path / ".king-context" / "bin" / "king-research").read_text(encoding="utf-8")

    assert "-m context_cli.cli" in kctx
    assert "../core/venv/bin/python" in kctx
    assert "-m king_context.scraper.cli" in scrape
    assert "-m king_context.research.cli" in research


def test_write_wrappers_creates_cmd_shims_on_windows(tmp_path):
    script = """
const path = require('path');
Object.defineProperty(process, 'platform', { value: 'win32' });
const { writeWrappers } = require('./installer/lib/scaffold');
process.chdir(process.argv[1]);
writeWrappers(process.argv[1]);
"""

    subprocess.run(
        ["node", "-e", script, str(tmp_path)],
        cwd=REPO_ROOT,
        check=True,
    )

    shell_wrapper = (tmp_path / ".king-context" / "bin" / "kctx").read_text(encoding="utf-8")
    cmd_wrapper = (tmp_path / ".king-context" / "bin" / "kctx.cmd").read_text(encoding="utf-8")

    assert "../core/venv/Scripts/python.exe" in shell_wrapper
    assert "python.exe" in cmd_wrapper
    assert "-m context_cli.cli" in cmd_wrapper


def test_python_helpers_resolve_platform_specific_venv_paths():
    script = """
const path = require('path');
Object.defineProperty(process, 'platform', { value: 'win32' });
const { getVenvPath, getVenvBinDir, getVenvPython } = require('./installer/lib/python');
const projectDir = process.argv[1];
console.log(JSON.stringify({
  venv: getVenvPath(projectDir),
  bin: getVenvBinDir(projectDir),
  python: getVenvPython(projectDir),
}));
"""

    result = subprocess.run(
        ["node", "-e", script, str(REPO_ROOT)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    data = json.loads(result.stdout)
    assert data["venv"].endswith(".king-context\\core\\venv")
    assert data["bin"].endswith(".king-context\\core\\venv\\Scripts")
    assert data["python"].endswith(".king-context\\core\\venv\\Scripts\\python.exe")


def test_detect_python_supports_windows_py_launcher():
    script = """
const childProcess = require('child_process');
Object.defineProperty(process, 'platform', { value: 'win32' });
childProcess.spawnSync = (cmd, args) => {
  if (cmd === 'py' && args.join(' ') === '-3 --version') {
    return { status: 0, stdout: '', stderr: 'Python 3.12.4\\n' };
  }
  return { status: 1, stdout: '', stderr: '' };
};
const { detectPython } = require('./installer/lib/python');
console.log(JSON.stringify(detectPython()));
"""

    result = subprocess.run(
        ["node", "-e", script],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    data = json.loads(result.stdout)
    assert data["cmd"] == "py"
    assert data["args"] == ["-3"]
    assert data["display"] == "py -3"
    assert data["version"] == "3.12.4"


def test_doctor_uses_shared_python_detection_contract():
    doctor = Path("installer/lib/doctor.js").read_text(encoding="utf-8")

    assert "detectPython" in doctor
    assert "getVenvPython" in doctor
    assert "python3 --version" not in doctor
