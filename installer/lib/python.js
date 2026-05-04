'use strict';

const { execFileSync, spawnSync } = require('child_process');
const path = require('path');

function getVenvPath(projectDir) {
  return path.join(projectDir, '.king-context', 'core', 'venv');
}

function getVenvBinDir(projectDir) {
  return path.join(getVenvPath(projectDir), process.platform === 'win32' ? 'Scripts' : 'bin');
}

function getVenvPython(projectDir) {
  return path.join(getVenvBinDir(projectDir), process.platform === 'win32' ? 'python.exe' : 'python');
}

function getPythonCandidates() {
  return process.platform === 'win32'
    ? [
        { cmd: 'py', args: ['-3'], display: 'py -3' },
        { cmd: 'python', args: [], display: 'python' },
        { cmd: 'python3', args: [], display: 'python3' },
      ]
    : [
        { cmd: 'python3', args: [], display: 'python3' },
        { cmd: 'python', args: [], display: 'python' },
        { cmd: 'py', args: ['-3'], display: 'py -3' },
      ];
}

function parsePythonVersion(raw) {
  const match = String(raw || '').match(/Python\s+(\d+\.\d+(?:\.\d+)?)/);
  return match ? match[1] : null;
}

/**
 * Detect a usable Python installation (>= 3.10).
 * Tries platform-appropriate Python launchers in priority order.
 * Returns { cmd, version } or throws with install instructions.
 */
function detectPython() {
  for (const candidate of getPythonCandidates()) {
    const result = spawnSync(candidate.cmd, [...candidate.args, '--version'], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });

    if (result.error || result.status !== 0) {
      continue;
    }

    const version = parsePythonVersion(`${result.stdout || ''}${result.stderr || ''}`.trim());
    if (!version) {
      continue;
    }

    const [major, minor] = version.split('.').map(Number);
    if (major < 3 || (major === 3 && minor < 10)) {
      continue;
    }

    return {
      cmd: candidate.cmd,
      args: candidate.args,
      display: candidate.display,
      version,
    };
  }

  throw new Error(
    'Python >= 3.10 is required but was not found.\n' +
    '  Install it from https://www.python.org/downloads/\n' +
    '  or via your package manager:\n' +
    '    macOS:  brew install python@3.12\n' +
    '    Ubuntu: sudo apt install python3\n' +
    '    Fedora: sudo dnf install python3\n' +
    '    Windows: winget install Python.Python.3.12'
  );
}

/**
 * Create a virtual environment inside .king-context/core/venv.
 */
function createVenv(projectDir) {
  const { cmd, args } = detectPython();
  const venvPath = getVenvPath(projectDir);

  execFileSync(cmd, [...args, '-m', 'venv', venvPath], {
    stdio: 'pipe',
    windowsHide: true,
  });
}

/**
 * Install king-context package into the project venv.
 */
function installPackage(projectDir) {
  const python = getVenvPython(projectDir);

  execFileSync(
    python,
    ['-m', 'pip', 'install', '--no-cache-dir', 'git+https://github.com/deandevz/king-context.git'],
    { stdio: 'pipe', timeout: 300000, windowsHide: true }
  );
}

/**
 * Upgrade king-context package in the project venv.
 */
function upgradePackage(projectDir) {
  const python = getVenvPython(projectDir);

  execFileSync(
    python,
    [
      '-m',
      'pip',
      'install',
      '--upgrade',
      '--force-reinstall',
      '--no-deps',
      '--no-cache-dir',
      'git+https://github.com/deandevz/king-context.git',
    ],
    { stdio: 'pipe', timeout: 300000, windowsHide: true }
  );
}

module.exports = {
  detectPython,
  createVenv,
  getVenvBinDir,
  getPythonCandidates,
  getVenvPath,
  getVenvPython,
  installPackage,
  parsePythonVersion,
  upgradePackage,
};
