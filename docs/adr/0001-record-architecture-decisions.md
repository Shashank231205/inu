# 0001. Record architecture decisions

- **Status:** accepted
- **Date:** 2026-10-02

## Context

INU will grow over many months and dozens of phases. Without a record, the reasons behind choices get lost and settled questions get reopened.

## Decision

Every significant decision gets an Architecture Decision Record in `docs/adr/`, numbered in order and copied from [the template](0000-template.md). An accepted ADR is never edited to change its meaning. A new ADR supersedes it.

A decision counts as significant if it is hard to reverse, adds a dependency or service, or changes a requirement.

## Consequences

Decisions are reviewable and easy to explain in interviews. It costs a few minutes per decision.
