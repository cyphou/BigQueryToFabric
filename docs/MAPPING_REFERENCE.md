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
`security_policy` records with `evidence_scope: dataset_access_entry`. Assessment emits `FAIL`
`SECURITY_EFFECTIVE_ACCESS_REVIEW`: dataset entries do not prove effective project, organization,
group, or inherited IAM access and require manual security review.

Use assessment provenance when reviewing the mapping evidence: `evidence_summary` exposes each
object's `discovered_from`, while `discovery_coverage` gives deterministic counts for `inventory`,
`bigquery_api`, and `external_payload`. The latter represents supplied associated-service payloads
normalized offline, not live discovery of those services. Neither value proves metadata freshness.

Discovery makes no IAM API calls. Project/org IAM, connection IAM bindings, distinct row access
policies, BigQuery Data Policies, and policy tags are not extracted. Treat any mapping involving
those controls as security review work, not verified source-rights parity. Dataflow, Composer,
Dataproc, Dataform, Workflows, Pub/Sub, GCS, Looker, Vertex AI, Dataplex, Cloud SQL, and Spanner are
likewise canonical/offline assessment inputs until their live adapters and permission contracts exist.
The complete extraction and permission matrix is in the [migration runbook](MIGRATION_RUNBOOK.md).
