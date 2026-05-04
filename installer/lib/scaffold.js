'use strict';

const fs = require('fs');
const path = require('path');

const DIRS = [
  'bin',
  'core',
  'data',
  'docs',
  'adr',
  'decisions',
  'research',
  '_learned',
  '_temp',
];

function expectedDirPaths() {
  return DIRS.map((dir) => path.join('.king-context', dir));
}

/**
 * Create the .king-context/ directory structure.
 */
function createDirs(projectDir) {
  for (const dir of expectedDirPaths()) {
    fs.mkdirSync(path.join(projectDir, dir), { recursive: true });
  }
}

/**
 * Write shell wrapper scripts from templates to .king-context/bin/.
 * Makes them executable (mode 0o755).
 */
function writeWrappers(projectDir) {
  const binDir = path.join(projectDir, '.king-context', 'bin');

  fs.mkdirSync(binDir, { recursive: true });

  const wrappers = [
    { module: 'context_cli.cli', target: 'kctx' },
    { module: 'king_context.scraper.cli', target: 'king-scrape' },
    { module: 'king_context.research.cli', target: 'king-research' },
  ];

  for (const { module, target } of wrappers) {
    const shellPath = path.join(binDir, target);
    const shellContent = process.platform === 'win32'
      ? `#!/bin/sh\nSCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"\nexec "$SCRIPT_DIR/../core/venv/Scripts/python.exe" -m ${module} "$@"\n`
      : `#!/bin/sh\nSCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"\nexec "$SCRIPT_DIR/../core/venv/bin/python" -m ${module} "$@"\n`;
    fs.writeFileSync(shellPath, shellContent, { mode: 0o755 });

    if (process.platform === 'win32') {
      const cmdPath = path.join(binDir, `${target}.cmd`);
      const cmdContent = `@echo off\r\nset SCRIPT_DIR=%~dp0\r\n"%SCRIPT_DIR%..\\core\\venv\\Scripts\\python.exe" -m ${module} %*\r\n`;
      fs.writeFileSync(cmdPath, cmdContent);
    }
  }
}

/**
 * Write .env.example from template into .king-context/.
 */
function writeEnvExample(projectDir) {
  const templatesDir = path.join(__dirname, '..', 'templates');
  const src = path.join(templatesDir, 'env.example');
  const dest = path.join(projectDir, '.king-context', '.env.example');

  const content = fs.readFileSync(src, 'utf8');
  fs.writeFileSync(dest, content);
}

module.exports = { createDirs, expectedDirPaths, writeWrappers, writeEnvExample };
