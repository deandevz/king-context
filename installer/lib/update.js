'use strict';

const fs = require('fs');
const path = require('path');
const ui = require('./ui');
const { upgradePackage } = require('./python');
const { writeWrappers } = require('./scaffold');
const { installSkills, mergeSettings } = require('./skills');

async function run() {
  const projectDir = process.cwd();
  const kingDir = path.join(projectDir, '.king-context');

  ui.header('King Context Update');

  // Check that .king-context/ exists
  if (!fs.existsSync(kingDir)) {
    ui.fail('King Context is not installed in this project.');
    console.log();
    console.log('  Run: npx @king-context/cli init');
    console.log();
    process.exit(1);
  }

  // 1. Upgrade pip package
  try {
    ui.step('Upgrading king-context package...');
    upgradePackage(projectDir);
    ui.stepDone('king-context package upgraded');
  } catch (err) {
    ui.stepFail('Failed to upgrade package');
    console.error(`    ${err.message}`);
  }

  // 2. Overwrite wrapper scripts
  try {
    ui.step('Updating CLI wrappers...');
    writeWrappers(projectDir);
    ui.stepDone('CLI wrappers updated');
  } catch (err) {
    ui.stepFail('Failed to update CLI wrappers');
    console.error(`    ${err.message}`);
  }

  // 3. Overwrite skills
  try {
    ui.step('Updating Claude skills...');
    installSkills(projectDir);
    ui.stepDone('Claude skills updated');
  } catch (err) {
    ui.stepFail('Failed to update skills');
    console.error(`    ${err.message}`);
  }

  // 4. Merge settings (add any new entries)
  try {
    ui.step('Merging Claude settings...');
    mergeSettings(projectDir);
    ui.stepDone('Claude settings merged');
  } catch (err) {
    ui.stepFail('Failed to merge settings');
    console.error(`    ${err.message}`);
  }

  // Summary
  console.log();
  ui.ok('Update complete. Your data/ and docs/ directories were preserved.');
  console.log();
  console.log('  Run "king-context doctor" to verify the update.');
  console.log();
}

module.exports = { run };
