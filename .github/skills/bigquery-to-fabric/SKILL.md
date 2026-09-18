---
name: bigquery-to-fabric
description: >-
  Assess and plan migrations from Google Cloud BigQuery to Microsoft Fabric. Use when
  mapping BigQuery, Spark, Dataproc, Dataflow/Beam, Dataform, Composer/Airflow,
  Workflows, Pub/Sub, GCS, Looker, BQML, Vertex AI, Dataplex, Cloud SQL, Spanner,
  security, or GoogleSQL to Fabric Lakehouse, Notebook, Warehouse, Eventhouse,
  Data Factory, OneLake, Data Science, Purview, or semantic models. Triggers: "migrate BigQuery to Fabric",
  "BQ vers Fabric", "assess BigQuery migration", "map GCP data platform to Fabric".
---

# BigQuery to Fabric

Use the BQToFabric CLI to turn a canonical BigQuery inventory into an explainable,
reviewable migration plan.

## Workflow

1. Discover a live project read-only with `bqtofabric discover <project-id> --output <inventory.json>`,
   or start from a hand-authored canonical inventory.
2. Summarize the source with `bqtofabric inventory <inventory.json>`.
3. Check its contract with `bqtofabric validate <inventory.json>`.
4. Run `bqtofabric assess <inventory.json>`.
5. Review decisions with `bqtofabric map <inventory.json>`.
6. Run `bqtofabric plan <inventory.json> --output <folder>`.
7. Run `bqtofabric generate <inventory.json> --output <folder>` for dry-run artifacts.
8. Review every WARN/FAIL before any cloud deployment.

## Golden rules

- Discovery is read-only and never writes credentials into an inventory.
- Choose targets by workload, not by product preference.
- Honor Lakehouse and Notebook preferences for compatible analytical workloads.
- Preserve existing Composer DAGs as Airflow Job candidates when operators remain reusable.
- Convert GoogleSQL to T-SQL, Spark SQL, or PySpark; reserve DAX for semantic measures.
- Prefer native Fabric BigQuery connectors over custom data-copy code.
- Treat generated artifacts as review material, not production deployment payloads.

## References

- [Component mapping](references/component-mapping.md)
- [Type mapping](references/type-mapping.md)
- [SQL compatibility](references/sql-compatibility.md)
- [GCP component assessment](../../../docs/GCP_COMPONENT_ASSESSMENT.md)
