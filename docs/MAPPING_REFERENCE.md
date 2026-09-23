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

## Connections

A BigQuery connection carries exactly one backend block, and each maps to a different
Fabric recreation path. Fabric connections are created once and bound by reference, so the
migration output is a setup instruction, never a credential.

| Backend | Fabric target | How to recreate |
|---|---|---|
| `cloudSql` (POSTGRES) | Data Pipeline connection | Create a PostgreSQL connection in Fabric; add a gateway if the instance is not publicly reachable |
| `cloudSql` (MYSQL) | Data Pipeline connection | Create a MySQL connection in Fabric; same gateway consideration |
| `cloudSpanner` | Manual — **redesign** | Fabric has no native Spanner connector; replicate into OneLake or a Fabric SQL database |
| `aws` | OneLake shortcut | Create an Amazon S3 shortcut or S3 pipeline connection; the AWS IAM role trust must be reissued for Fabric |
| `azure` | Data Pipeline connection | Replace the federated Entra application with a Fabric workspace identity or service principal, then re-grant the target resource |
| `cloudResource` | OneLake shortcut | Create a Google Cloud Storage shortcut or GCS connection; grant it its own credential |
| `spark` | Lakehouse | Drop the connection and bind the migrated notebook to its Lakehouse |

When the Cloud SQL engine is not recorded, assessment returns `manual`/`redesign` rather
than naming a connector, because the Fabric connection type cannot be derived without it.
An unrecognized backend falls through to `manual`/`redesign` for the same reason; the
backend list above is not exhaustive and newer BigQuery backends will take that path.

## Assessment finding codes

Assessment emits 18 stable finding codes. Codes are the review contract; message text is not.
Every `FAIL` blocks reliance on the affected recommendation until it is resolved or explicitly
accepted. Every `WARN` requires documented design or manual review.

| Code | Severity | Category | Trigger | Reviewer action |
|---|---|---|---|---|
| `ACTION_REQUIRED` | WARN | mapping | The selected mapping records concrete follow-up actions before the target can be built. | Work through the recorded actions in the component mapping and mark each resolved or accepted. |
| `DATAFORM_COMPILATION_DETAILS_UNAVAILABLE` | FAIL | adapter | A Dataform compilation-result detail request failed, so the workflow's lineage graph is unavailable. | Restore Dataform API access, re-run discovery, and re-assess. Do not rely on lineage-dependent waves. |
| `EVIDENCE_MISSING` | WARN | evidence | A required evidence field for the object's kind is absent. See the [required-evidence matrix](INVENTORY_SCHEMA.md#required-evidence-by-kind). | Supply the missing field in the inventory or re-discover the object, then re-assess. |
| `EXTERNAL_PAYLOAD_INCOMPLETE_ADAPTER` | FAIL | adapter | A `discovered_from: external_payload` component lacks the offline evidence its kind requires, and no live adapter covers that service. | Complete the offline evidence for the component before relying on its target or wave. |
| `ASSISTED_EVIDENCE_INCOMPLETE` | FAIL | provenance | A `discovered_from: assisted` component still lacks the evidence its kind requires. | Inference did not close the gap; capture the evidence from the source system. |
| `ASSISTED_EVIDENCE_UNVERIFIED` | WARN | provenance | A component's evidence was inferred by an agent rather than read from a source system. | Confirm the inferred evidence against the source. Always forces manual review, even when evidence is complete. |
| `MAPPING_REDESIGN` | WARN | mapping | The source-to-Fabric mapping is classified `redesign`. | Design the target explicitly; do not treat the generated artifact as a translation. |
| `MAPPING_UNSUPPORTED` | FAIL | mapping | No safe automatic mapping is claimed for the source object. | Decide the target manually, or descope the object from the migration wave. |
| `PARITY_FAILED` | FAIL | parity | A parity check computed `failed` from the supplied source/target evidence. | Inspect the recorded differences, correct the target or the evidence, and re-run the comparison. |
| `PARITY_NOT_RUN` | WARN | parity | A parity check is applicable but its evidence is missing or malformed, so the result is `not_run`. | Supply valid evidence. `not_run` never means the source and target match. |
| `PERFORMANCE_CLUSTERING_REVIEW` | WARN | performance | A `TABLE`, `EXTERNAL_TABLE`, or `MATERIALIZED_VIEW` at or above `10 GiB` records no clustering fields. | Choose a target clustering or ordering strategy during design review. This is not a measured performance claim. |
| `PERFORMANCE_PARTITION_REVIEW` | WARN | performance | A `TABLE`, `EXTERNAL_TABLE`, or `MATERIALIZED_VIEW` at or above `10 GiB` records no partition field. | Choose a target partitioning strategy during design review. This is not a measured performance claim. |
| `SECURITY_EFFECTIVE_ACCESS_REVIEW` | FAIL | security | A `security_policy` record with `evidence_scope: dataset_access_entry` is present. Dataset ACLs do not establish effective access. | Have a security administrator evaluate project, organization, group, and inherited IAM, then define the Fabric equivalent. |
| `SECURITY_EVIDENCE_MISSING` | FAIL | security | A security-relevant object lacks the policy evidence its kind requires. | Supply the policy evidence or record the control as manually reviewed. |
| `SQL_REDESIGN` | WARN | sql | SQL conversion produced a `redesign` verdict, including non-SQL routine bodies such as JavaScript UDFs. | Rewrite the logic for the target engine. No converted SQL is emitted for a non-SQL body. |
| `STREAMING_DOWNSTREAM_REVIEW` | WARN | streaming | The object is a transitive downstream consumer of a `DATAFLOW_JOB` with `properties.streaming: true`. | Review deduplication, idempotency, and out-of-order delivery for the consumer. |
| `TYPE_REDESIGN` | WARN | type | A source column type has no direct Fabric equivalent and needs a modeled replacement. | Choose the target type and record the conversion rule. The finding lists the affected column paths. |
| `TYPE_UNSUPPORTED` | FAIL | type | A source column type has no supported Fabric mapping. | Decide the representation manually before migrating the object. |

Type findings are attributable: `source_id` is the owning object, not the bare type name. Assessment
emits one finding per distinct type per object and lists the affected column paths, so a `STRUCT`
finding points at the table that uses it rather than at `STRUCT`.

Findings are dry-run review evidence. Their presence does not prove remediation, and their absence
does not prove runtime, security, or deployment readiness.

## SQL fidelity mapping

There is one SQL conversion stack. `sql_assessment` delegates to the `converter/` package
(`SqlConverter`), so assessment and generation cannot disagree about a conversion verdict.

SQL compatibility is the worst of three inputs and never defaults to `direct`:

1. The converter verdict for the target dialect.
2. The detected semantic risks, such as `SAFE_CAST` and `NOT IN`, whose target-dialect translation
   does not prove equivalent null-handling or membership semantics.
3. The mapping decision for the owning object.

A non-SQL routine body, such as a JavaScript UDF, is `redesign` and emits no converted SQL rather
than a best-effort translation.

This contract is validated by `python -m pytest tests/test_sql_converter.py`, which passes in CI.
The test is offline and does not execute source or target SQL, validate official Fabric schemas,
or establish runtime/data parity. Reviewers must run approved parity checks for transformed SQL.

## Composer schedule compatibility

Composer payload normalization stores the DAG schedule in `properties.schedule_interval` and retains
`properties.schedule` for backward compatibility with existing inventories. Pipeline generation
prefers `schedule_interval`, then uses `schedule` when the canonical field is absent. Both paths
map `@daily`, `@hourly`, and `@weekly` to the corresponding Fabric pipeline triggers.

Raw cron expressions are review-required: BQToFabric does not automatically translate them into a
Fabric trigger. Review the source schedule, timezone, start-date, catchup, and retry semantics
before authoring a target trigger. This is deterministic dry-run guidance, not execution or trigger
parity evidence.

This contract is validated by `python -m pytest tests/test_discovery.py
tests/test_artifact_generation.py`, which passes in CI.

Generated schedule triggers use the Fabric expression `@utcNow()` for `startTime` rather than a
stale fixed `2024` date, and `triggers` is a sibling of `properties` rather than a pipeline
property. This behavior is validated by `python -m pytest tests/test_artifact_generation.py`, which
passes in CI. Generated pipeline definitions still require validation against the official
Fabric/ADF schema and deployment validation; this change does not establish deployability or
scheduling parity.

Generated operational activities also receive deterministic resilience defaults: `retry: 3`,
`retryIntervalInSeconds: 30`, `secureInput: true`, and `secureOutput: true`. The failure handler
retains its specialized secure policy. Retry behavior remains open until validated against the
official Fabric/ADF schema and at runtime.

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

This contract is validated by `python -m pytest tests/test_discovery.py tests/test_assessment.py`,
which passes in CI.

Composer connection extraction is independent of dependency extraction. When the DAG dependency
map is empty, normalization still inspects task connection fields and emits `connections: []` when
none are declared; this explicit empty list is complete evidence, while an absent field remains
incomplete evidence.

## Dataflow job discovery deduplication

Regional and paginated Dataflow payloads may repeat a job ID. Normalization emits one canonical
job per ID and resolves repeated records deterministically, so output does not depend on response
page or region ordering. This is a deterministic discovery contract, not evidence of complete
regional coverage or metadata freshness.

This edge-case contract is validated by `python -m pytest tests/test_discovery.py
tests/test_dataflow_discovery.py`, which passes in CI. The checks run offline against fixtures.
Dataflow, Dataproc, Dataform, and Composer all have opt-in live adapters, but none has been
exercised against an authorized live-GCP sandbox, and regional adapters never scan all regions.

## Dataproc adapter evidence

Dataproc job normalization records canonical `properties.language`: PySpark maps to `python`,
Spark SQL and Hive map to `sql`, and Pig maps to `pig`. Unsupported or ambiguous job types map to
`unknown`; the existing `properties.runtime` job classification remains unchanged.

`properties.runtime_version` comes from the referenced cluster's
`config.softwareConfig.imageVersion` when present, otherwise `unknown`. Assessment treats
`unknown` and `not specified` as missing evidence rather than evidence of runtime readiness. Supply
the runtime version or re-discover from a payload containing the referenced cluster's `imageVersion`
before accepting readiness as complete.

This contract is validated by `python -m pytest tests/test_discovery.py tests/test_assessment.py`,
which passes in CI.

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
Measured workload telemetry and runtime benchmarking remain open. This behavior is validated by
`python -m pytest tests/test_assessment.py`, which passes in CI.

## Discovery evidence boundary

The live provider discovers BigQuery core metadata, jobs, scheduled-query transfer configurations,
connections, and dataset GET `access` entries. The `access` entries are redacted, each principal
identity is pseudonymized as a stable non-reversible `principal:<12 hex>` value, and the result
becomes a canonical `security_policy` record with `evidence_scope: dataset_access_entry`.
Assessment emits `FAIL` `SECURITY_EFFECTIVE_ACCESS_REVIEW`: dataset entries do not prove effective
project, organization, group, or inherited IAM access and require manual security review.

Use assessment provenance when reviewing the mapping evidence: `evidence_summary` exposes each
object's `discovered_from`, while `discovery_coverage` gives deterministic counts. The canonical
values are `inventory`, `bigquery_api`, `dataflow_api`, `composer_api`, `dataproc_api`,
`dataform_api`, `external_payload`, and `assisted`. `external_payload` represents supplied
associated-service payloads normalized offline, not live discovery of those services.
`assisted` represents evidence inferred by an agent rather than read from a source system.
No value proves metadata freshness.

If an `external_payload` component lacks required offline evidence, assessment emits exactly one
`FAIL` `EXTERNAL_PAYLOAD_INCOMPLETE_ADAPTER` finding in category `adapter`, explaining that the
evidence must be completed because the component was supplied offline rather than discovered.
Planning marks the component and all direct/transitive dependents `manual_review`. This review
propagation does not create an `unresolved_dependencies` entry; that field is only for missing or
external source IDs and cycles.

## Manual-review decision contract

`manual_review` remains the planner's decision flag. Every flagged `PlanItem` also includes a
deterministic `manual_review_reasons` list that makes the decision actionable. Reasons are recorded
independently, so a single component can carry several codes rather than only the first matching
condition. The 13 codes are:

| Code | Review trigger |
|---|---|
| `cycle_or_unresolved_dependency` | Planning found a dependency cycle or unresolved dependency. |
| `depends_on_incomplete_dataform_compilation` | The item depends on a Dataform workflow with incomplete compilation details. |
| `depends_on_incomplete_external_adapter` | The item depends on an incomplete external-adapter component. |
| `external_dependency` | A required source dependency is external to the planned inventory. |
| `incompatible_mapping` | The selected source-to-target mapping requires compatibility review. |
| `assisted_evidence` | The object's evidence was inferred by an agent rather than read from a source system. |
| `incomplete_dataform_compilation` | A Dataform compilation-result detail request failed, so the workflow graph is incomplete. |
| `incomplete_external_adapter` | An external payload has incomplete evidence and no live adapter covers that service. |
| `missing_required_evidence` | A required evidence field for the object's kind is absent. |
| `parity_failed` | A parity check computed `failed` from the supplied evidence. |
| `security_review` | A security finding requires administrator review before the item can proceed. |
| `sql_incompatibility` | SQL assessment identified a compatibility issue that needs review. |
| `streaming_downstream_review` | A downstream consumer requires streaming delivery review. |

`migration-plan.md` renders `manual_review` and its reason codes. The generated
`fabric/target-manifest.json` exposes the same values as `manualReview` and
`manualReviewReasons`. These fields are deterministic offline review metadata; they do not call
cloud services or change deployment behavior.

## Parity evidence contract

Parity status is recomputed from evidence on every assessment run. A caller-supplied `status` is
never trusted.

- Each check is derived from its own `source` and `target` payload.
- A declared `passed` with no payload resolves to `not_run`.
- When a declared status contradicts the computed result, the check records `declaredStatus`
  alongside the computed status so the disagreement stays visible.
- The `type` check was removed because no comparator backed it. The check set is exactly `schema`,
  `row_count`, `checksum`, `aggregate`, `null_distribution`, `sample`, and `sql_result`.
- Applicability is keyed on data-bearing kind — table, external table, view, materialized view —
  rather than on whether columns happened to be captured.

Every comparison consumes supplied evidence. No source or Fabric query is executed, so `passed`
means "the supplied evidence agrees", not "the data matches at runtime". `not_run` never means
parity succeeded.

## Generated artifact validity

An artifact's `valid` flag in `generated/manifest.json` is derived from a real check of its
content, not asserted by the generator:

| Validator | Rejects |
|---|---|
| `NotebookValidator` | Undefined DataFrame references |
| `TsqlValidator` | A comment-stripped `CREATE TABLE` that does not re-parse, `#` comments, and `CREATE SCHEMA` outside its own batch |
| `PipelineValidator` | Parameters or variables that are not name-keyed, `triggers` as a pipeline property, and secret-bearing expressions |

Generated pipelines carry named connection references bound to managed identity instead of
connection strings, and `triggers` sits beside `properties` because triggers are separate Fabric
resources. Manifest paths use POSIX separators so generated output is byte-identical across
platforms. Validation runs after every artifact is written, so `parity-evidence.json` and
`deployment-manifest.json` are covered by the credential scan and the structural checks.

These validators are structural and offline. A `valid: true` artifact is still a dry-run skeleton
and still requires official Fabric schema validation before deployment.

## Warehouse view conversion boundary

A generated Warehouse view body is translated GoogleSQL → T-SQL. When conversion fails, or when the
converted result uses constructs Fabric Warehouse does not support, the view body is omitted, the
artifact is marked invalid, and the candidate conversion is emitted as `--` comments for review.
Raw GoogleSQL is never presented as T-SQL.

Conversion is static. Result-set equivalence between the source view and the reviewed T-SQL is
unproven and requires parity testing.

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

This behavior is validated by `python -m pytest tests/test_artifact_generation.py`, which passes in
CI. Author the Eventstream against the official Fabric API/schema and provide approved connections
before deployment.

## Semantic-model source-schema boundary

For a table, view, or materialized view whose columns were not discovered, semantic-model
generation returns an invalid review-only scaffold rather than referencing a first source column.
The model reports `valid: false`, `deployable: false`, and
`validationStatus: pending_source_schema`, with no tables, measures, relationships, or connection
placeholders. A `REDESIGN` warning requires source-schema discovery and regeneration. Normal
schema-backed semantic-model output is unchanged.

This behavior is validated by `python -m pytest tests/test_artifact_generation.py`, which passes in
CI. The guard is not official Fabric semantic-model schema/API validation; validate the regenerated
model before deployment.

Discovery makes no IAM API calls. Project/org IAM, connection IAM bindings, distinct row access
policies, BigQuery Data Policies, and policy tags are not extracted. Treat any mapping involving
those controls as security review work, not verified source-rights parity.

Opt-in read-only live adapters exist for Dataflow, Dataproc, Dataform, and Composer in addition to
the BigQuery path. They are enabled only by explicit CLI flags, and the four non-BigQuery adapters
request the `https://www.googleapis.com/auth/cloud-platform.read-only` scope, which is broader than
the BigQuery path's `bigquery.readonly`. None of them has been validated against an authorized GCP
sandbox: the adapter exists, the sandbox verification does not. Workflows, Pub/Sub, GCS, Looker,
Vertex AI, Dataplex, Cloud SQL, and Spanner have no live adapter and remain canonical/offline
assessment inputs until their adapters and permission contracts exist.

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
or access recovery to capture the actual compilation graph. This behavior is validated by
`python -m pytest tests/test_discovery.py tests/test_assessment.py tests/test_dataform_conversion.py`,
which passes in CI.
The complete extraction and permission matrix is in the [migration runbook](MIGRATION_RUNBOOK.md).
