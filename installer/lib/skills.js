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
        'Bash(python3 *)',
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
 * Append gitignore entries for .king-context internals if not already present.
 */
function updateGitignore(projectDir) {
  const gitignorePath = path.join(projectDir, '.gitignore');
  const marker = '# King Context';
  const entries = [
    '',
    marker,
    '.king-context/core/',
    '.king-context/docs/',
    '.king-context/data/',
    '.king-context/_temp/',
    '.king-context/_learned/',
    '',
  ].join('\n');

  if (fs.existsSync(gitignorePath)) {
    const content = fs.readFileSync(gitignorePath, 'utf8');
    if (content.includes(marker)) {
      return; // already present
    }
    fs.appendFileSync(gitignorePath, entries);
  } else {
    fs.writeFileSync(gitignorePath, entries.trimStart());
  }
}

module.exports = { installSkills, mergeSettings, updateClaudeMd, updateGitignore };
