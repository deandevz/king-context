# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Renamed the Python MCP server console script from `king-context` to
  `king-context-server`. The `king-context` name is reserved for the npm
  installer (`@king-context/cli`), which is the user facing entry point.
  Users with a Claude Code or Claude Desktop MCP config that points at
  `king-context` should update it to `king-context-server`. The
  `python -m king_context.server` invocation is unchanged.
