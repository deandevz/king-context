---
id: ADR-0002
title: Centralize installer layout reconciliation
status: accepted
date: 2026-05-02
areas:
  - installer
  - cli
  - deploy
  - upgrade
supersedes: []
superseded_by: []
related:
  - ADR-0001
keywords:
  - installer-layout
  - upgrade
  - idempotent-scaffold
  - doctor
  - source-of-truth
tags:
  - installer
  - upgrade
  - adr
---


# ADR-0002: Centralize installer layout reconciliation

## Context

The installer had separate code paths for init, update, and doctor. New required directories were added to the scaffold and doctor checks, but the update path did not create them for existing installations. This allowed a successful king-context update to be followed by a failing king-context doctor.

## Decision

The installer scaffold module owns the canonical .king-context directory contract. init and update must call the same idempotent directory reconciliation before relying on the layout, and doctor must validate against the same exported contract instead of maintaining its own copied list.

## Alternatives Considered

Keep separate directory lists in doctor and scaffold; create only the newly missing ADR directories in update; make doctor auto-create missing directories. These options either preserve duplication, make future migrations easy to miss, or mix validation with mutation.

## Consequences

Future installer layout additions are made in one place and are automatically applied to fresh installs, existing installs during update, and health checks. Updates remain backwards-compatible because directory creation is recursive and non-destructive. Doctor stays a validator, while update is responsible for reconciling install state before asking users to validate it.

## Links

installer/lib/scaffold.js, installer/lib/update.js, installer/lib/doctor.js, tests/test_installer_scaffold.py
