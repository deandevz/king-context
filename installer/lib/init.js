'use strict';

const path = require('path');
const ui = require('./ui');
const { detectPython, createVenv, installPackage } = require('./python');
const { createDirs, writeWrappers, writeEnvExample } = require('./scaffold');
const { installSkills, mergeSettings, updateClaudeMd, updateGitignore } = require('./skills');

async function run() {
  const projectDir = process.cwd();

  ui.header('King Context Installer');

  // 1. Detect Python
  let pythonInfo;
  try {
    ui.step('Detecting Python...');
    pythonInfo = detectPython();
    ui.stepDone(`Python ${pythonInfo.version} found (${pythonInfo.cmd})`);
  } catch (err) {
    ui.stepFail('Python not found');
    console.error();
    console.error(err.message);
    process.exit(1);
  }

  // 2. Create directory structure
  try {
    ui.step('Creating directory structure...');
    createDirs(projectDir);
    ui.stepDone('Directory structure created');
  } catch (err) {
    ui.stepFail('Failed to create directories');
    console.error(`    ${err.message}`);
    process.exit(1);
  }

  // 3. Create virtual environment
  try {
    ui.step('Creating virtual environment...');
    createVenv(projectDir);
    ui.stepDone('Virtual environment created');
  } catch (err) {
    ui.stepFail('Failed to create virtual environment');
    console.error(`    ${err.message}`);
    process.exit(1);
  }

  // 4. Install king-context package
  try {
    ui.step('Installing king-context (this may take a minute)...');
    installPackage(projectDir);
    ui.stepDone('king-context package installed');
  } catch (err) {
    ui.stepFail('Failed to install king-context');
    console.error(`    ${err.message}`);
    process.exit(1);
  }

  // 5. Write wrapper scripts
  try {
    ui.step('Writing CLI wrappers...');
    writeWrappers(projectDir);
    ui.stepDone('CLI wrappers installed');
  } catch (err) {
    ui.stepFail('Failed to write CLI wrappers');
    console.error(`    ${err.message}`);
  }

  // 6. Install skills
  try {
    ui.step('Installing Claude skills...');
    installSkills(projectDir);
    ui.stepDone('Claude skills installed');
  } catch (err) {
    ui.stepFail('Failed to install skills');
    console.error(`    ${err.message}`);
  }

  // 7. Merge settings
  try {
    ui.step('Configuring Claude settings...');
    mergeSettings(projectDir);
    ui.stepDone('Claude settings configured');
  } catch (err) {
    ui.stepFail('Failed to configure settings');
    console.error(`    ${err.message}`);
  }

  // 8. Write .env.example
  try {
    ui.step('Writing .env.example...');
    writeEnvExample(projectDir);
    ui.stepDone('.env.example written');
  } catch (err) {
    ui.stepFail('Failed to write .env.example');
    console.error(`    ${err.message}`);
  }

  // 9. Update CLAUDE.md
  try {
    ui.step('Updating CLAUDE.md...');
    updateClaudeMd(projectDir);
    ui.stepDone('CLAUDE.md updated');
  } catch (err) {
    ui.stepFail('Failed to update CLAUDE.md');
    console.error(`    ${err.message}`);
  }

  // 10. Update .gitignore
  try {
    ui.step('Updating .gitignore...');
    updateGitignore(projectDir);
    ui.stepDone('.gitignore updated');
  } catch (err) {
    ui.stepFail('Failed to update .gitignore');
    console.error(`    ${err.message}`);
  }

  // Done — print next steps
  console.log();
  ui.header('Next Steps');
  console.log('  1. Copy .king-context/.env.example to .env and add your API keys:');
  console.log();
  console.log('       cp .king-context/.env.example .env');
  console.log();
  console.log('  2. Run the doctor to verify your installation:');
  console.log();
  console.log('       npx @king-context/cli doctor');
  console.log();
  console.log('  3. Ask Claude to search documentation:');
  console.log();
  console.log('       "Search the Next.js docs for server components"');
  console.log();
}

module.exports = { run };
