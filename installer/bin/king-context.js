#!/usr/bin/env node
'use strict';

const command = process.argv[2];

switch (command) {
  case 'init':
    require('../lib/init').run();
    break;
  case 'doctor':
    require('../lib/doctor').run();
    break;
  case 'update':
    require('../lib/update').run();
    break;
  case '--version':
  case '-v':
    console.log(require('../package.json').version);
    break;
  default:
    console.log(`
  Usage: king-context <command>

  Commands:
    init      Install King Context in the current project
    doctor    Check installation health
    update    Update tools and skills (preserves your data)

  Options:
    --version  Show version
`);
    if (command) process.exit(1);
}
