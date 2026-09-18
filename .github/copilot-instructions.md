# BQToFabric project instructions

BQToFabric assesses and plans migrations from Google BigQuery to Microsoft Fabric.

## Architecture

`JSON inventory -> canonical model -> assessment/mapping -> strategy -> dependency plan -> dry-run artifacts`

## Non-negotiable rules

- Keep cloud operations out of the default path. V1 is offline and non-destructive.
- Never emit credentials, service-account keys, tokens, tenant IDs, or workspace secrets.
- Translate GoogleSQL transformations to T-SQL, Spark SQL, or PySpark. DAX is only for
  semantic-model measures, never for ETL.
- Recommend Fabric targets from workload evidence. Do not default every object to Lakehouse.
- Prefer the native Fabric BigQuery connector for Dataflow Gen2, Pipeline Copy/Lookup, and
  Copy Job rather than implementing a proprietary data mover.
- Every recommendation must include rationale and compatibility: direct, transform,
  redesign, or unsupported.
- Keep generated output deterministic and dry-run unless an explicit deployment phase is added.
- Add focused tests for every mapping or strategy rule.

## Commands

```powershell
bqtofabric inventory inventory.json
bqtofabric assess inventory.json
bqtofabric map inventory.json
bqtofabric plan inventory.json --output artifacts/plan
bqtofabric generate inventory.json --output artifacts/project
bqtofabric validate inventory.json
```
