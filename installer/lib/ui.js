'use strict';

const OK = '\u2713';    // checkmark
const FAIL = '\u2717';  // x mark
const WARN = '\u26A0';  // warning

function ok(msg) { console.log(`  ${OK} ${msg}`); }
function fail(msg) { console.log(`  ${FAIL} ${msg}`); }
function warn(msg) { console.log(`  ${WARN} ${msg}`); }
function header(title) {
  console.log();
  console.log(`  ${title}`);
  console.log(`  ${'\u2500'.repeat(title.length)}`);
  console.log();
}
function step(msg) { process.stdout.write(`  \u2026 ${msg}`); }
function stepDone(msg) { process.stdout.write(`\r  ${OK} ${msg}\n`); }
function stepFail(msg) { process.stdout.write(`\r  ${FAIL} ${msg}\n`); }

module.exports = { ok, fail, warn, header, step, stepDone, stepFail, OK, FAIL, WARN };
