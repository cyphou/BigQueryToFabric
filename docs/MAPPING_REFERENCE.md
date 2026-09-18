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

If an `external_payload` component lacks required offline evidence, assessment emits exactly one
`FAIL` `EXTERNAL_PAYLOAD_INCOMPLETE_ADAPTER` finding in category `adapter`, explaining that the
evidence must be completed because no live adapter is implemented. Planning marks the component and
all direct/transitive dependents `manual_review`. This review propagation does not create an
`unresolved_dependencies` entry; that field is only for missing or external source IDs and cycles.

## Manual-review decision contract

`manual_review` remains the planner's decision flag. Every flagged `PlanItem` also includes a
deterministic `manual_review_reasons` list that makes the decision actionable. The codes are:

| Code | Review trigger |
|---|---|
| `external_dependency` | A required source dependency is external to the planned inventory. |
| `incompatible_mapping` | The selected source-to-target mapping requires compatibility review. |
| `streaming_downstream_review` | A downstream consumer requires streaming delivery review. |
| `incomplete_external_adapter` | An external payload has incomplete evidence for an unimplemented live adapter. |
| `depends_on_incomplete_external_adapter` | The item depends on an incomplete external-adapter component. |
| `sql_incompatibility` | SQL assessment identified a compatibility issue that needs review. |
| `cycle_or_unresolved_dependency` | Planning found a dependency cycle or unresolved dependency. |

`migration-plan.md` renders `manual_review` and its reason codes. The generated
`fabric/target-manifest.json` exposes the same values as `manualReview` and
`manualReviewReasons`. These fields are deterministic offline review metadata; they do not call
cloud services or change deployment behavior.

## Stage-readiness summary

`fabric/target-manifest.json` includes a top-level `stageReadiness` summary for every processing
stage that has one or more entries; absent stages are omitted. Each stage has `total`, counts for
`direct`, `transform`, `redesign`, and `unsupported`, `manualReview`, and `readiness`.
`readiness` is the deterministic rounded weighted average of the stage's component compatibility:
`direct=100`, `transform=80`, `redesign=50`, and `unsupported=0`.

The rollup prioritizes migration review. It is not proof of execution, parity, security
remediation, or deployment readiness.

Discovery makes no IAM API calls. Project/org IAM, connection IAM bindings, distinct row access
policies, BigQuery Data Policies, and policy tags are not extracted. Treat any mapping involving
those controls as security review work, not verified source-rights parity. Dataflow, Composer,
Dataproc, Dataform, Workflows, Pub/Sub, GCS, Looker, Vertex AI, Dataplex, Cloud SQL, and Spanner are
likewise canonical/offline assessment inputs until their live adapters and permission contracts exist.
The complete extraction and permission matrix is in the [migration runbook](MIGRATION_RUNBOOK.md).
