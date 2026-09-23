# Inventory Schema Guide

BQToFabric consumes a canonical JSON inventory. The inventory is cloud-independent: discovery adapters and hand-authored fixtures must produce the same shape before assessment begins.

## Shape at a Glance

```mermaid
flowchart TD
    ROOT[Inventory JSON] --> META[project_id + schema_version]
    ROOT --> DATASETS[datasets[]]
    ROOT --> COMPONENTS[components[]]
    DATASETS --> DATASET[Dataset]
    DATASET --> OBJECTS[objects[]]
    OBJECTS --> OBJECT[BigQueryObject]
    COMPONENTS --> OBJECT
    OBJECT --> COLUMNS[columns[]]
    OBJECT --> PROPS[properties]
    OBJECT --> DEPS[dependencies[]]
```

## Minimal Inventory

```json
{
  "project_id": "demo-project",
  "schema_version": "1.1",
  "datasets": [],
  "components": [
    {
      "source_id": "demo-project.analytics.orders",
      "name": "orders",
      "kind": "table",
      "dataset": "analytics",
      "columns": [
        {
          "name": "order_id",
          "data_type": "STRING",
          "nullable": false,
          "mode": "REQUIRED"
        }
      ],
      "dependencies": [],
      "properties": {}
    }
  ],
  "metadata": {}
}
```

## Top-Level Fields

| Field | Required | Meaning |
|---|---:|---|
| `project_id` | Yes | Stable source project identifier |
| `schema_version` | No | Canonical inventory version; defaults to `1.0` when omitted |
| `datasets` | No | BigQuery datasets containing nested objects |
| `components` | No | Cross-dataset or ecosystem objects such as jobs, streams, and DAGs |
| `metadata` | No | Preferences and provenance-safe configuration |

## Object Fields

| Field | Required | Meaning |
|---|---:|---|
| `source_id` | Yes | Immutable globally meaningful source identifier |
| `name` | Yes | Source object name |
| `kind` | Yes | `ObjectKind` value such as `table`, `view`, `spark_job`, or `composer_dag` |
| `discovered_from` | No | `inventory`, provider name, or `external_payload` |
| `dataset` | No | Owning BigQuery dataset |
| `columns` | No | Ordered column metadata, including nested `fields` |
| `sql` | No | Source SQL or procedure body |
| `dependencies` | No | Source IDs or explicit external references |
| `partition_field` | No | Recorded source partitioning field |
| `clustering_fields` | No | Recorded source clustering fields |
| `size_bytes` | No | Recorded source size; used only for review recommendations |
| `labels` | No | Non-secret source labels |
| `properties` | No | Workload-specific evidence and adapter metadata |

## `kind` Values

The canonical model supports BigQuery and surrounding GCP workloads, including:

- Storage and SQL: `table`, `view`, `materialized_view`, `external_table`, `routine`, `procedure`, `scheduled_query`
- Compute and orchestration: `bigquery_job`, `spark_job`, `dataproc_job`, `dataflow_job`, `dataform_workflow`, `composer_dag`, `workflow`
- Streaming and integration: `stream`, `pubsub_topic`, `gcs_source`
- Analytics and governance: `looker_asset`, `bqml_model`, `vertex_ai_pipeline`, `dataplex_asset`, `security_policy`, `connection`
- Databases: `cloud_sql_database`, `spanner_database`

Use the exact enum spelling accepted by the CLI. Unknown kinds are validation errors, not custom extension points.

## Evidence Rules

- Use `source_id` for lineage and dependency references; do not use display names as identifiers.
- Keep credentials, tokens, private keys, connection passwords, tenant IDs, and workspace secrets out of every field.
- Preserve unknown evidence as absent or `unknown`; do not infer runtime, IAM, parity, or deployment facts.
- `dependencies` may reference objects outside the inventory. The planner reports those as external dependencies.
- `size_bytes`, partitioning, and clustering metadata support review recommendations only. They do not prove performance.
- `discovered_from: external_payload` requires the adapter evidence expected by assessment or the component is blocked for review.

## Validate and Inspect

```powershell
bqtofabric validate path/to/inventory.json
bqtofabric inventory path/to/inventory.json
bqtofabric assess path/to/inventory.json
```

For a complete sanitized example, use `tests/fixtures/gcp_ecosystem_project.json`. For the end-to-end local workflow, see [USER_MANUAL.md](USER_MANUAL.md) and run `scripts/smoke_test.ps1`.
