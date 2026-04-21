'use strict';

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const ui = require('./ui');

/**
 * Run a single diagnostic check.
 * Returns { status: 'ok'|'warn'|'fail', label: string }.
 */
function checkPython() {
  try {
    const raw = execSync('python3 --version', { stdio: 'pipe' }).toString().trim();
    return { status: 'ok', label: `Python: ${raw}` };
  } catch {
    return { status: 'fail', label: 'Python: python3 not found' };
  }
}

function checkVenv(projectDir) {
  const venvPython = path.join(projectDir, '.king-context', 'core', 'venv', 'bin', 'python');
  if (fs.existsSync(venvPython)) {
    return { status: 'ok', label: 'Venv: .king-context/core/venv/bin/python exists' };
  }
  return { status: 'fail', label: 'Venv: virtual environment not found' };
}

function checkCliTools(projectDir) {
  const results = [];
  const binDir = path.join(projectDir, '.king-context', 'bin');

  // Check kctx
  const kctxPath = path.join(binDir, 'kctx');
  try {
    if (fs.existsSync(kctxPath)) {
      execSync(`"${kctxPath}" --version`, { stdio: 'pipe', timeout: 10000 });
      results.push({ status: 'ok', label: 'CLI: kctx is working' });
    } else {
      results.push({ status: 'fail', label: 'CLI: kctx not found' });
    }
  } catch {
    results.push({ status: 'warn', label: 'CLI: kctx found but returned an error' });
  }

  // Check king-scrape
  const scrapePath = path.join(binDir, 'king-scrape');
  try {
    if (fs.existsSync(scrapePath)) {
      execSync(`"${scrapePath}" --help`, { stdio: 'pipe', timeout: 10000 });
      results.push({ status: 'ok', label: 'CLI: king-scrape is working' });
    } else {
      results.push({ status: 'fail', label: 'CLI: king-scrape not found' });
    }
  } catch {
    results.push({ status: 'warn', label: 'CLI: king-scrape found but returned an error' });
  }

  // Check king-research
  const researchPath = path.join(binDir, 'king-research');
  try {
    if (fs.existsSync(researchPath)) {
      execSync(`"${researchPath}" --help`, { stdio: 'pipe', timeout: 10000 });
      results.push({ status: 'ok', label: 'CLI: king-research is working' });
    } else {
      results.push({ status: 'fail', label: 'CLI: king-research not found' });
    }
  } catch {
    results.push({ status: 'warn', label: 'CLI: king-research found but returned an error' });
  }

  return results;
}

function checkSkills(projectDir) {
  const results = [];
  const skills = [
    { path: '.claude/skills/king-context/skill.md', name: 'king-context' },
    { path: '.claude/skills/scraper-workflow/skill.md', name: 'scraper-workflow' },
  ];

  for (const skill of skills) {
    const fullPath = path.join(projectDir, skill.path);
    if (fs.existsSync(fullPath)) {
      results.push({ status: 'ok', label: `Skill: ${skill.name} installed` });
    } else {
      results.push({ status: 'fail', label: `Skill: ${skill.name} not found` });
    }
  }

  return results;
}

function checkApiKeys(projectDir) {
  const results = [];
  const envPath = path.join(projectDir, '.king-context', '.env');

  if (!fs.existsSync(envPath)) {
    // Also check project root .env
    const rootEnvPath = path.join(projectDir, '.env');
    if (!fs.existsSync(rootEnvPath)) {
      return [{ status: 'warn', label: 'API Keys: no .env file found' }];
    }
  }

  // Try both locations
  let envContent = '';
  const envPath1 = path.join(projectDir, '.king-context', '.env');
  const envPath2 = path.join(projectDir, '.env');

  if (fs.existsSync(envPath1)) {
    envContent += fs.readFileSync(envPath1, 'utf8');
  }
  if (fs.existsSync(envPath2)) {
    envContent += '\n' + fs.readFileSync(envPath2, 'utf8');
  }

  // Check FIRECRAWL_API_KEY (required)
  if (envContent.match(/^FIRECRAWL_API_KEY=.+/m)) {
    results.push({ status: 'ok', label: 'API Keys: FIRECRAWL_API_KEY is set' });
  } else {
    results.push({ status: 'fail', label: 'API Keys: FIRECRAWL_API_KEY is missing (required)' });
  }

  // Check OPENROUTER_API_KEY (optional)
  if (envContent.match(/^OPENROUTER_API_KEY=.+/m)) {
    results.push({ status: 'ok', label: 'API Keys: OPENROUTER_API_KEY is set' });
  } else {
    results.push({ status: 'warn', label: 'API Keys: OPENROUTER_API_KEY is missing (optional, needed for LLM enrichment)' });
  }

  return results;
}

function checkDirStructure(projectDir) {
  const expectedDirs = [
    '.king-context/bin',
    '.king-context/core',
    '.king-context/data',
    '.king-context/docs',
    '.king-context/research',
    '.king-context/_learned',
    '.king-context/_temp',
  ];

  const missing = [];
  for (const dir of expectedDirs) {
    if (!fs.existsSync(path.join(projectDir, dir))) {
      missing.push(dir);
    }
  }

  if (missing.length === 0) {
    return { status: 'ok', label: 'Directories: all expected directories exist' };
  }
  return { status: 'fail', label: `Directories: missing ${missing.join(', ')}` };
}

function checkVersion() {
  const localVersion = require('../package.json').version;

  try {
    const remote = execSync('npm view @king-context/cli version', {
      stdio: 'pipe',
      timeout: 10000,
    }).toString().trim();

    if (remote === localVersion) {
      return { status: 'ok', label: `Version: ${localVersion} (latest)` };
    }
    return { status: 'warn', label: `Version: ${localVersion} (latest: ${remote})` };
  } catch {
    return { status: 'ok', label: `Version: ${localVersion} (could not check for updates)` };
  }
}

async function run() {
  const projectDir = process.cwd();

  ui.header('King Context Doctor');

  const results = [];

  // 1. Python
  results.push(checkPython());

  // 2. Venv
  results.push(checkVenv(projectDir));

  // 3. CLI tools
  results.push(...checkCliTools(projectDir));

  // 4. Skills
  results.push(...checkSkills(projectDir));

  // 5. API keys
  results.push(...checkApiKeys(projectDir));

  // 6. Dir structure
  results.push(checkDirStructure(projectDir));

  // 7. Version
  results.push(checkVersion());

  // Print results
  for (const result of results) {
    switch (result.status) {
      case 'ok':
        ui.ok(result.label);
        break;
      case 'warn':
        ui.warn(result.label);
        break;
      case 'fail':
        ui.fail(result.label);
        break;
    }
  }

  // Summary
  const fails = results.filter(r => r.status === 'fail').length;
  const warns = results.filter(r => r.status === 'warn').length;
  const oks = results.filter(r => r.status === 'ok').length;

  console.log();
  console.log(`  ${oks} passed, ${warns} warnings, ${fails} failed`);
  console.log();

  if (fails > 0) {
    console.log('  Run "king-context init" to fix missing components.');
    console.log();
    process.exit(1);
  }
}

module.exports = { run };
