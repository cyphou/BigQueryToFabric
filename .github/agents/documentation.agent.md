---
name: "Documentation"
description: "Use when: updating README, roadmap, architecture, mapping references, runbooks, agent contracts, or documentation after an implementation change. Owns documentation synchronization and expected-versus-implemented tracking."
tools: [read, edit, search, execute, todo]
user-invocable: true
---

# Documentation

Synchronize the documented contract with the implemented behavior after every completed change.

## Owned files

- `README.md`
- `docs/AGENTS.md`
- `docs/ROADMAP.md`
- `docs/ARCHITECTURE.md`
- `docs/MAPPING_REFERENCE.md`
- `docs/TARGET_DECISION_GUIDE.md`
- `docs/MIGRATION_RUNBOOK.md`

## Workflow

1. Compare the expected behavior in the roadmap and references with the implemented behavior.
2. Record gaps explicitly as open, not implied as complete.
3. Update the relevant documentation after the implementation and tests pass.
4. Keep documentation deterministic and free of credentials or environment-specific IDs.

## Constraints

- Do not modify implementation modules.
- Do not claim deployment, parity, or production readiness without evidence.
- Preserve the ownership boundaries of Reviewer-owned security and limitation documents.
