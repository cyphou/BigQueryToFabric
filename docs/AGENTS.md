# Agents

## Ownership and documentation gate

- Every implementation file or directory has exactly one owning agent.
- Ownership is exclusive: agents coordinate through `Orchestrator` instead of editing another
	agent's owned path.
- Each change follows this sequence: expected behavior -> implementation -> focused tests ->
	documentation update.
- The `Documentation` agent must update the relevant README, roadmap, architecture, mapping, or
	runbook after the implementation is validated.
- Documentation must distinguish `expected`, `implemented`, `validated`, and `open` behavior.

| Agent | Responsibility |
|---|---|
| Orchestrator | CLI, reporting, workflow coordination |
| Extractor | Canonical BigQuery model and inventory providers |
| Assessor | Readiness score and evidence-based findings |
| Architect | Component mapping, Fabric strategy, types, migration waves |
| SqlConverter | GoogleSQL compatibility and structured translation |
| FabricGenerator | Dry-run Fabric definitions |
| Deployer | Future packaging and authenticated deployment boundary |
| Reviewer | Fidelity, security, parity, and limitations |
| Tester | Fixtures, contracts, and regressions |
| Documentation | README, roadmap, architecture, mapping references, and runbooks |

Each implementation path has one owner. Shared changes must be coordinated by Orchestrator.
