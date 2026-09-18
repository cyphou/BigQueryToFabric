# Mapping reference

| BigQuery | Fabric | Notes |
|---|---|---|
| Project | Domain/workspace topology | Governance decision, not a strict 1:1 mapping |
| Dataset | Warehouse schema or Lakehouse | Choose from workload and isolation requirements |
| Flat table | Warehouse table | Preferred for governed relational BI |
| Nested table | Lakehouse Delta table | Preserve ARRAY/STRUCT before optional normalization |
| View | Warehouse view or Spark SQL | Translate GoogleSQL and test result parity |
| Materialized view | Orchestrated Gold table | Recreate refresh semantics explicitly |
| Scheduled Query | Data Pipeline | Carry schedule, parameters, retries, and identity |
| External table | Shortcut or Copy activity | Validate shortcut source support first |
| Stream | Eventstream/Eventhouse | Define retention, schema mapping, and KQL validation |
| SQL routine | Warehouse routine | Only when T-SQL semantics are equivalent |
| JavaScript UDF | Notebook | Requires redesign and parity tests |
| Policy tags | Purview and Fabric permissions | Manual governance review required |
| Row access policy | Workspace/item permissions and RLS | No automatic 1:1 security translation |

## Discovery evidence boundary

The live provider discovers BigQuery core metadata, jobs, scheduled-query transfer configurations,
connections, and dataset GET `access` entries. The `access` entries are redacted and become canonical
`security_policy` records; they are not a substitute for project Cloud IAM bindings.

Project IAM, connection IAM bindings, row access policies, BigQuery Data Policies, and policy tags
are not extracted. Treat any mapping involving those controls as security review work, not verified
source-rights parity. Dataflow, Composer, Dataproc, Dataform, Workflows, Pub/Sub, GCS, Looker,
Vertex AI, Dataplex, Cloud SQL, and Spanner are likewise canonical/offline assessment inputs until
their live adapters and permission contracts exist. The complete extraction and permission matrix is
in the [migration runbook](MIGRATION_RUNBOOK.md).
