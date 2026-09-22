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
| Stream | Eventstream/Eventhouse | Eventstream output is a non-deployable review scaffold; define retention, schema mapping, approved connections, and KQL validation |
| SQL routine | Warehouse routine | Only when T-SQL semantics are equivalent |
| JavaScript UDF | Notebook | Requires redesign and parity tests |
| Policy tags | Purview and Fabric permissions | Manual governance review required |
| Row access policy | Workspace/item permissions and RLS | No automatic 1:1 security translation |

## Composer schedule compatibility

Composer payload normalization stores the DAG schedule in `properties.schedule_interval` and retains
`properties.schedule` for backward compatibility with existing inventories. Pipeline generation
prefers `schedule_interval`, then uses `schedule` when the canonical field is absent. Both paths
map `@daily`, `@hourly`, and `@weekly` to the corresponding Fabric pipeline triggers.

Raw cron expressions are review-required: BQToFabric does not automatically translate them into a
Fabric trigger. Review the source schedule, timezone, start-date, catchup, and retry semantics
before authoring a target trigger. This is deterministic dry-run guidance, not execution or trigger
parity evidence.

This contract was validated with `python -m pytest tests/test_discovery.py
tests/test_artifact_generation.py -v` (`79 passed`).

Generated schedule triggers use the Fabric expression `@utcNow()` for `startTime` rather than a
stale fixed `2024` date. This behavior was validated with
`python -m pytest tests/test_artifact_generation.py -v` (`44 passed`). Generated pipeline
definitions still require validation against the official Fabric/ADF schema and deployment
validation; this change does not establish deployability or scheduling parity.

Generated operational activities also receive deterministic resilience defaults: `retry: 3`,
`retryIntervalInSeconds: 30`, `secureInput: true`, and `secureOutput: true`. The failure handler
retains its specialized secure policy. This was validated with
`python -m pytest tests/test_artifact_generation.py -v` (`44 passed`). Retry behavior remains open
until validated against the official Fabric/ADF schema and at runtime.

## Composer adapter evidence

Composer DAG normalization writes `properties.runtime_version` from the Composer image version when
available, otherwise from a sanitized environment-version label, otherwise `unknown`. It records
only declared task connection names from `conn_id`, `connection_id`, `gcp_conn_id`, and
`google_cloud_conn_id` in `properties.connections`; it never serializes connection configuration
or secrets.

`connections: []` explicitly establishes that no task declared a connection, so assessment treats
the Composer evidence as complete. A missing `connections` field remains incomplete evidence.
Neither state proves connection configuration, secret bindings, or effective runtime access; review
those manually before relying on a migration decision.

This contract was validated with `python -m pytest tests/test_discovery.py
tests/test_assessment.py -v` (`53 passed`).

## Dataproc adapter evidence

Dataproc job normalization records canonical `properties.language`: PySpark maps to `python`,
Spark SQL and Hive map to `sql`, and Pig maps to `pig`. Unsupported or ambiguous job types map to
`unknown`; the existing `properties.runtime` job classification remains unchanged.

`properties.runtime_version` comes from the referenced cluster's
`config.softwareConfig.imageVersion` when present, otherwise `unknown`. Assessment treats
`unknown` and `not specified` as missing evidence rather than evidence of runtime readiness. Supply
the runtime version or re-discover from a payload containing the referenced cluster's `imageVersion`
before accepting readiness as complete.

This contract was validated with `python -m pytest tests/test_discovery.py
tests/test_assessment.py -v` (`54 passed`).

## Performance-layout review

For `TABLE`, `EXTERNAL_TABLE`, and `MATERIALIZED_VIEW` objects at or above `10 GiB`, assessment
uses only recorded inventory metadata to emit deterministic `WARN` findings when layout evidence
is absent:

| Missing recorded evidence | Finding code |
|---|---|
| Partition field | `PERFORMANCE_PARTITION_REVIEW` |
| Clustering fields | `PERFORMANCE_CLUSTERING_REVIEW` |

These findings are design-review recommendations for migration planning. They are not measured
performance claims and do not automatically select or apply partitioning, clustering, or indexing.
Measured workload telemetry and runtime benchmarking remain open. This behavior was validated with
`python -m pytest tests/test_assessment.py -v` (`16 passed`).

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
| `incomplete_dataform_compilation` | A Dataform compilation-result detail request failed, so the workflow graph is incomplete. |
| `depends_on_incomplete_dataform_compilation` | The item depends on a Dataform workflow with incomplete compilation details. |
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

## Eventstream artifact boundary

Generated Eventstream output is a deterministic authoring scaffold, not an official Fabric
Eventstream definition. It sets `deployable: false` and artifact `valid: false`; the source node
uses `connectionReference: review_required`, never an invented `connectionId`, and includes
explicit authoring TODOs. The generated artifact manifest propagates `valid: false`.

This behavior was validated with `python -m pytest tests/test_artifact_generation.py -v` (`40
passed`). Author the Eventstream against the official Fabric API/schema and provide approved
connections before deployment.

## Semantic-model source-schema boundary

For a table, view, or materialized view whose columns were not discovered, semantic-model
generation returns an invalid review-only scaffold rather than referencing a first source column.
The model reports `valid: false`, `deployable: false`, and
`validationStatus: pending_source_schema`, with no tables, measures, relationships, or connection
placeholders. A `REDESIGN` warning requires source-schema discovery and regeneration. Normal
schema-backed semantic-model output is unchanged.

This behavior was validated with `python -m pytest tests/test_artifact_generation.py -v` (`42
passed`). The guard is not official Fabric semantic-model schema/API validation; validate the
regenerated model before deployment.

Discovery makes no IAM API calls. Project/org IAM, connection IAM bindings, distinct row access
policies, BigQuery Data Policies, and policy tags are not extracted. Treat any mapping involving
those controls as security review work, not verified source-rights parity. Dataflow job metadata is
the first optional live external extraction, limited to explicitly requested regions; portability
and connector compatibility remain evidence-driven. Composer, Dataproc, Dataform, Workflows,
Pub/Sub, GCS, Looker, Vertex AI, Dataplex, Cloud SQL, and Spanner are likewise canonical/offline
assessment inputs until their live adapters and permission contracts exist.

Dataform discovery aggregates successful compilation results into canonical `models`, `assertions`,
and `incremental` evidence on the repository and workflow records. `models` contains sorted
compiled table/view target names. `assertions` and `incremental` are booleans derived from compiled
targets and edges. An explicit empty `models` list and explicit `false` booleans are known evidence,
not an incomplete-data condition.

Only an API-detail failure preserves incomplete Dataform evidence rather than omitting the workflow:
discovery emits a deterministic `dataform_workflow` fallback with `discovered_from: dataform_api`,
`discovery_incomplete: true`, and `lineage_status: unavailable`. Assessment emits `FAIL`
`DATAFORM_COMPILATION_DETAILS_UNAVAILABLE`; planning applies
`incomplete_dataform_compilation` to the fallback and
`depends_on_incomplete_dataform_compilation` to its downstream objects. Re-run discovery after API
or access recovery to capture the actual compilation graph. This behavior was validated with
`python -m pytest tests/test_discovery.py tests/test_assessment.py tests/test_dataform_conversion.py
-v` (`56 passed`).
The complete extraction and permission matrix is in the [migration runbook](MIGRATION_RUNBOOK.md).
