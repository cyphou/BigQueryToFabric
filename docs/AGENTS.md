# Agents

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

Each implementation path has one owner. Shared changes must be coordinated by Orchestrator.
