---
id: ADR-0001
title: Adopt CLI-first architecture for agent retrieval
status: accepted
date: 2026-05-02
areas:
  - cli
  - retrieval
  - agents
  - mcp
  - product-strategy
supersedes: []
superseded_by: []
related:
  - ADR-0002
keywords:
  - cli-first
  - agent-retrieval
  - context-budget
  - mcp
  - context7
  - research
  - code-intelligence
tags:
  - architecture
  - product
  - retrieval
  - agents
---


# ADR-0001: Adopt CLI-first architecture for agent retrieval

## Context

King Context started as local-first documentation retrieval for AI agents, with MCP support as an integration path. In practice, the CLI now gives agents better performance, clearer primitives, easier validation, and more flexible workflows than the MCP surface. The project is also expanding beyond a Context7-style documentation competitor into a broader retrieval tool for code, general research, and durable project knowledge while keeping agent context usage small.

## Decision

Future King Context capabilities should be designed CLI-first. The CLI is the canonical product interface for agent retrieval workflows, indexing, validation, research, code knowledge, and decision memory. MCP remains useful and may continue to exist as an integration layer, but it should not define the primary architecture, block CLI capabilities, or require parity before CLI features ship.

## Alternatives Considered

A MCP-first architecture would preserve the original server-centric shape, but it would constrain agent workflows behind a less ergonomic and less transparent interface. A strict CLI-and-MCP parity rule would slow development and force MVP features into two surfaces before the CLI workflow proves the value. Keeping King Context framed only as a Context7 competitor would understate the broader retrieval role the project now serves for agents.

## Consequences

New features should expose reliable CLI primitives first and may add MCP support later when there is a clear integration need. Skills should prefer CLI commands for retrieval and maintenance workflows. Tests should cover CLI behavior as the primary contract. Product language should describe King Context as an optimized retrieval layer for AI agents across documentation, research, code, and project knowledge, with context-budget efficiency as a core design constraint.

## Links
