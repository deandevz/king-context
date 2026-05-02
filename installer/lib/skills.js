'use strict';

const fs = require('fs');
const path = require('path');

/**
 * Copy skill templates into the project's .claude/skills/ directory.
 * Always overwrites to ensure latest version.
 */
function installSkills(projectDir) {
  const srcDir = path.join(__dirname, '..', 'templates', 'skills');
  const destDir = path.join(projectDir, '.claude', 'skills');
  copyDirRecursive(srcDir, destDir);

  // Also copy agent definitions
  const agentsSrc = path.join(__dirname, '..', 'templates', 'agents');
  const agentsDest = path.join(projectDir, '.claude', 'agents');
  if (fs.existsSync(agentsSrc)) {
    copyDirRecursive(agentsSrc, agentsDest);
  }
}

/**
 * Recursively copy a directory, creating targets as needed.
 */
function copyDirRecursive(src, dest) {
  fs.mkdirSync(dest, { recursive: true });

  const entries = fs.readdirSync(src, { withFileTypes: true });

  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);

    if (entry.isDirectory()) {
      copyDirRecursive(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

/**
 * Create or merge .claude/settings.local.json.
 * Merges env.PATH and permissions.allow arrays without duplicating entries.
 */
function mergeSettings(projectDir) {
  const filePath = path.join(projectDir, '.claude', 'settings.local.json');
  const newEntries = {
    permissions: {
      allow: [
        'Bash(.king-context/bin/kctx *)',
        'Bash(.king-context/bin/king-scrape *)',
        'Bash(.king-context/bin/king-research *)',
        'Bash(python3 *)',
        'Bash(python3*)',
        'Write(.king-context/**)',
        'Read(.king-context/**)',
      ],
    },
  };

  let existing = {};

  if (fs.existsSync(filePath)) {
    try {
      existing = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    } catch {
      // corrupt file — start fresh
      existing = {};
    }
  } else {
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
  }

  // Merge permissions.allow
  if (!existing.permissions) existing.permissions = {};
  if (!Array.isArray(existing.permissions.allow)) existing.permissions.allow = [];

  for (const entry of newEntries.permissions.allow) {
    if (!existing.permissions.allow.includes(entry)) {
      existing.permissions.allow.push(entry);
    }
  }

  fs.writeFileSync(filePath, JSON.stringify(existing, null, 2) + '\n');
}

/**
 * Append King Context section to CLAUDE.md if not already present.
 * Creates CLAUDE.md if it does not exist.
 */
function updateClaudeMd(projectDir) {
  const claudeMdPath = path.join(projectDir, 'CLAUDE.md');
  const snippetPath = path.join(__dirname, '..', 'templates', 'claude-md-snippet.md');
  const snippet = fs.readFileSync(snippetPath, 'utf8');

  if (fs.existsSync(claudeMdPath)) {
    const content = fs.readFileSync(claudeMdPath, 'utf8');
    if (content.includes('# King Context')) {
      return; // already present
    }
    fs.appendFileSync(claudeMdPath, '\n' + snippet);
  } else {
    fs.writeFileSync(claudeMdPath, snippet);
  }
}

/**
 * Append missing gitignore entries for .king-context internals.
 */
function updateGitignore(projectDir) {
  const gitignorePath = path.join(projectDir, '.gitignore');
  const marker = '# King Context';
  const requiredEntries = [
    '.king-context/core/',
    '.king-context/docs/',
    '.king-context/decisions/',
    '.king-context/research/',
    '.king-context/data/',
    '.king-context/_temp/',
    '.king-context/_learned/',
  ];
  const entries = ['', marker, ...requiredEntries, ''].join('\n');

  if (fs.existsSync(gitignorePath)) {
    const content = fs.readFileSync(gitignorePath, 'utf8');
    const lines = content.split(/\r?\n/);
    const markerIndex = lines.findIndex((line) => line.trim() === marker);

    if (markerIndex === -1) {
      fs.appendFileSync(gitignorePath, entries);
      return;
    }

    const existingEntries = new Set(lines.map((line) => line.trim()));
    const missingEntries = requiredEntries.filter((entry) => !existingEntries.has(entry));
    if (missingEntries.length === 0) {
      return;
    }

    const newline = content.includes('\r\n') ? '\r\n' : '\n';
    lines.splice(markerIndex + 1, 0, ...missingEntries);
    fs.writeFileSync(gitignorePath, lines.join(newline));
  } else {
    fs.writeFileSync(gitignorePath, entries.trimStart());
  }
}

module.exports = { installSkills, mergeSettings, updateClaudeMd, updateGitignore };
