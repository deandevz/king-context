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
  const templatesDir = path.join(__dirname, '..', 'templates');
  const binDir = path.join(projectDir, '.king-context', 'bin');

  fs.mkdirSync(binDir, { recursive: true });

  const wrappers = [
    { template: 'wrapper-kctx.sh', target: 'kctx' },
    { template: 'wrapper-scrape.sh', target: 'king-scrape' },
    { template: 'wrapper-research.sh', target: 'king-research' },
  ];

  for (const { template, target } of wrappers) {
    const src = path.join(templatesDir, template);
    const dest = path.join(binDir, target);

    const content = fs.readFileSync(src, 'utf8');
    fs.writeFileSync(dest, content, { mode: 0o755 });
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
