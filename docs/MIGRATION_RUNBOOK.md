# Migration runbook

1. Export or build the canonical BigQuery inventory.
2. Validate it with `bqtofabric validate`.
3. Run `bqtofabric assess` and resolve FAIL findings.
4. Review target and type mappings, especially ARRAY, STRUCT, GEOGRAPHY, BIGNUMERIC, policies,
   UDFs, procedures, and external dependencies.
5. Generate the migration plan and verify dependency waves.
6. Generate dry-run Fabric artifacts and review SQL, notebooks, pipelines, identities, and names.
7. Design parity checks for row counts, schemas, nulls, aggregates, samples, and security behavior.
8. Use the native Fabric BigQuery connector for Dataflow Gen2, Pipeline Copy/Lookup, or Copy Job.
9. Pilot one representative dataset before scaling by migration wave.
10. Add live deployment only after explicit approval, credentials, rollback, and audit controls.
