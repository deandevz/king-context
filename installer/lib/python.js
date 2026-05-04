'use strict';

const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');

/**
 * Detect a usable Python installation (>= 3.10).
 * Tries python3 first, then python.
 * Returns { cmd, version } or throws with install instructions.
 */
function detectPython() {
  const candidates = ['python3', 'python'];

  for (const cmd of candidates) {
    try {
      const raw = execSync(`${cmd} --version`, { stdio: 'pipe' }).toString().trim();
      const match = raw.match(/Python\s+(\d+\.\d+\.\d+)/);
      if (!match) continue;

      const version = match[1];
      const [major, minor] = version.split('.').map(Number);

      if (major < 3 || (major === 3 && minor < 10)) {
        continue;
      }

      return { cmd, version };
    } catch {
      // command not found, try next
    }
  }

  throw new Error(
    'Python >= 3.10 is required but was not found.\n' +
    '  Install it from https://www.python.org/downloads/\n' +
    '  or via your package manager:\n' +
    '    macOS:  brew install python@3.12\n' +
    '    Ubuntu: sudo apt install python3\n' +
    '    Fedora: sudo dnf install python3'
  );
}

/**
 * Create a virtual environment inside .king-context/core/venv.
 */
function createVenv(projectDir) {
  const { cmd } = detectPython();
  const venvPath = path.join(projectDir, '.king-context', 'core', 'venv');

  execSync(`${cmd} -m venv "${venvPath}"`, { stdio: 'pipe' });
}

/**
 * Install king-context package into the project venv.
 */
function installPackage(projectDir) {
  const pip = path.join(projectDir, '.king-context', 'core', 'venv', 'bin', 'pip');

  execSync(
    `"${pip}" install --no-cache-dir git+https://github.com/deandevz/king-context.git`,
    { stdio: 'pipe', timeout: 300000 }
  );
}

/**
 * Upgrade king-context package in the project venv.
 */
function upgradePackage(projectDir) {
  const pip = path.join(projectDir, '.king-context', 'core', 'venv', 'bin', 'pip');

  execSync(
    `"${pip}" install --upgrade --force-reinstall --no-deps --no-cache-dir git+https://github.com/deandevz/king-context.git`,
    { stdio: 'pipe', timeout: 300000 }
  );
}

module.exports = { detectPython, createVenv, installPackage, upgradePackage };
