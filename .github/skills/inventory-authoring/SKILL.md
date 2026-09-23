---
name: inventory-authoring
description: >-
  Author, complete, and repair a canonical BQToFabric inventory JSON so an assessment
  is based on evidence rather than gaps. Use when writing an inventory by hand, when
  evidence coverage is low, when EVIDENCE_MISSING or EXTERNAL_PAYLOAD_INCOMPLETE_ADAPTER
  findings appear, or when a readiness score looks unexpectedly low. Triggers:
  "write a BigQuery inventory", "inventory schema", "evidence missing", "improve
  evidence coverage", "fix EVIDENCE_MISSING", "why is my score low", "compléter
  l'inventaire".
---

# Inventory authoring

A low readiness score usually means missing evidence, not an unmigratable estate.
The score is scaled by evidence coverage and clamped to zero when a component carries
a FAIL finding, so completing evidence is the fastest way to a defensible assessment.

## Minimal shape

```json
{
  "project_id": "acme-analytics",
  "datasets": [
    {
      "source_id": "acme-analytics.sales",
      "name": "sales",
      "location": "EU",
      "objects": []
    }
  ],
  "components": [],
  "metadata": {}
}
```

Objects live either in `datasets[].objects` or in top-level `components`. Both are
assessed identically.

## Object fields

| Field | Required | Notes |
|---|---|---|
| `source_id` | yes | Globally unique. Duplicates are rejected before model coercion. |
| `name` | yes | Non-empty string. |
| `kind` | yes | One of the 26 `ObjectKind` values. |
| `dataset` | no | Free-form; used as the Warehouse schema name. |
| `sql` | depends on kind | GoogleSQL body. |
| `columns` | depends on kind | Nested `fields` supported for STRUCT. |
| `dependencies` | no | Array of `source_id`; unknown ids become external dependencies. |
| `size_bytes` | depends on kind | Non-negative integer. An explicit `null` is valid and means "recorded as unknown". |
| `partition_field`, `clustering_fields` | no | Drive layout findings on large tables. |
| `properties` | depends on kind | Free-form evidence bag. |
| `discovered_from` | no | `inventory` (default), `bigquery_api`, `dataflow_api`, `composer_api`, `dataproc_api`, `dataform_api`, `external_payload`. |

Validate before assessing:

```powershell
bqtofabric validate inventory.json
```

## Required evidence by kind

Missing entries produce `EVIDENCE_MISSING` (WARN) and reduce the component score.
If `discovered_from` is `external_payload`, they produce
`EXTERNAL_PAYLOAD_INCOMPLETE_ADAPTER` (FAIL), which clamps the component to zero.

| Kind | Required evidence |
|---|---|
| `table` | `columns`, `size_bytes` |
| `view` | `sql` |
| `materialized_view` | `sql`, `columns` |
| `external_table` | `columns` |
| `routine` | `language`, `sql` |
| `procedure` | `language`, `sql` |
| `sql_script` | `sql` |
| `spark_job` | `language`, `runtime_version`, `code` |
| `dataproc_job` | `language`, `runtime_version`, `code` |
| `dataflow_job` | `streaming`, `portable`, `connector_compatible` |
| `dataform_workflow` | `models`, `assertions`, `incremental` |
| `composer_dag` | `operators`, `runtime_version`, `connections` |
| `looker_asset` | `explores`, `measures`, `joins` |
| `bqml_model` | `model_type`, `features`, `evaluation_metrics` |
| `vertex_ai_pipeline` | `pipeline_steps`, `models`, `endpoints` |
| `cloud_sql_database` | `engine`, `version`, `replication` |
| `spanner_database` | `dialect`, `replication`, `change_streams` |
| `security_policy` | `policy_type` |

No contract is defined for `scheduled_query`, `bigquery_job`, `stream`, `workflow`,
`pubsub_topic`, `gcs_source`, `connection`, or `dataplex_asset`. Those kinds report
100% coverage by default — treat that as "not yet contracted", not as "verified".

## Evidence rules that trip people up

- **A recorded boolean counts as evidence in either state.** `"streaming": false` is
  evidence, not absence. Mapping already acts on it.
- **`"unknown"`, `"not specified"` and empty strings do not count.** They read as
  absence.
- **Empty lists count only for `connections` and `models`**, where an adapter can
  legitimately report "there are none".
- **`columns`, `sql`, `size_bytes` are model fields**, not `properties` entries. Put
  them at the object level.
- **`code` for Spark and Dataproc jobs is the source body**, not a URI. Live discovery
  records only `main_file`, so this must be supplied to get converted notebook logic.

## Worked example

```json
{
  "source_id": "acme-analytics.sales.orders",
  "name": "orders",
  "kind": "table",
  "dataset": "sales",
  "size_bytes": 5497558138880,
  "partition_field": "order_date",
  "clustering_fields": ["customer_id"],
  "columns": [
    { "name": "order_id", "data_type": "INT64", "mode": "REQUIRED" },
    { "name": "order_date", "data_type": "DATE" },
    { "name": "basket", "data_type": "STRUCT", "fields": [
      { "name": "sku", "data_type": "STRING" }
    ]}
  ],
  "dependencies": ["acme-analytics.dataflow.ingest"]
}
```

## Checking your work

```powershell
bqtofabric validate inventory.json
bqtofabric assess inventory.json
```

Then read `assessment-summary.json`:

- `evidenceCoverage` below 100 lists which objects are short.
- `manualReviewReasons.missing_required_evidence` counts the affected components.
- `blockers` names every FAIL, each of which zeroes its component's score.

## References

- [Inventory schema](../../../docs/INVENTORY_SCHEMA.md)
- [Mapping reference](../../../docs/MAPPING_REFERENCE.md)
