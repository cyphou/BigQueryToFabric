# Development Roadmap

BQToFabric is a non-destructive assessment and planning engine. Assessment, mapping, planning, and
generation are offline; discovery is opt-in, read-only, and credential-redacting. The roadmap moves
it from canonical JSON inventories to evidence-backed live discovery, conversion, validation, and
explicitly approved Fabric deployment.

## Authoritative baseline — v0.1.0

This table is the single source of truth for baseline counts. Other documents link here instead of
restating the numbers. Measured locally on the committed GCP ecosystem fixture and the repository
validation commands.

| Signal | Verified value |
|---|---|
| Supported source taxonomy | 26 `ObjectKind` members |
| Fabric decision surface | 15 primary/supporting target roles |
| Public CLI | 9 commands: `assess`, `deployment-check`, `discover`, `generate`, `inventory`, `manifest-verify`, `map`, `plan`, `validate` |
| Live discovery adapters | BigQuery (core) plus opt-in BigQuery-adjacent adapters for Dataflow, Dataproc, Dataform, and Composer |
| Reference portfolio | 28 assessed components (`tests/fixtures/gcp_ecosystem_project.json`) |
| Reference recommendation | Lakehouse primary · hybrid architecture · Airflow retained |
| Generated package | 9 deterministic dry-run artifacts |
| Assessment finding codes | 18 stable codes (see [mapping reference](MAPPING_REFERENCE.md#assessment-finding-codes)) |
| Manual-review reason codes | 13 stable codes |
| Parity check types | 7: `schema`, `row_count`, `checksum`, `aggregate`, `null_distribution`, `sample`, `sql_result` |
| Test suite | 364 passed |
| Coverage | 89% |
| Static quality | Ruff clean · Pyright clean |
| Agent contracts | 10 agents · exclusive ownership · documentation handoff · 1 skill validated |

Reproduce with:

```powershell
python -m pytest
python -m pyright
python -m ruff check src tests
python scripts/validate_agents.py
```

Focused test-file pass counts are intentionally not documented per command. They drift on every
change and were repeatedly wrong. Cite the command and state that it passes in CI instead.

### Reference-fixture assessment output

Deterministic output of `bqtofabric assess tests/fixtures/gcp_ecosystem_project.json` at this
release:

| Field | Value |
|---|---|
| `score` | 42 |
| `evidenceCoverage` | 61 |
| `componentCount` | 28 |
| `manualReviewCount` | 16 |
| `status` | `blocked` |
| `findingCounts` | `FAIL: 1`, `WARN: 74` |
| `paritySummary` | `not_applicable: 24`, `not_run: 4` |
| `manualReviewReasons` | `incompatible_mapping: 9`, `missing_required_evidence: 12`, `sql_incompatibility: 3`, `streaming_downstream_review: 1` |

The reference score moved from `70` to `42` in this release. This is an intended correction, not a
regression in the fixture: scoring is now computed per component, scaled by evidence coverage, and
forced to zero for any component carrying a `FAIL` blocker. The previous score was inflated because
type and SQL risks were aggregated separately from the components that owned them, schema width
contributed to the score, and missing required evidence did not reduce it. Treat `42` as the honest
readiness of a fixture that deliberately contains incomplete evidence.

## Correctness release — behavior changes

Each item below is implemented and covered by the test suite. None of them establishes runtime
execution, official Fabric schema validity, or deployment readiness.

### Artifact validity is derived, not asserted

- **Expected:** `valid` in `generated/manifest.json` must reflect a real check of the artifact
  content rather than a generator-side assertion.
- **Implemented:** `NotebookValidator` rejects undefined DataFrame references. `TsqlValidator`
  strips comments and re-parses `CREATE TABLE`, rejects `#` comments, and enforces the
  `CREATE SCHEMA` batch rule. `PipelineValidator` requires name-keyed parameters and variables,
  rejects `triggers` as a pipeline property, and rejects secret-bearing expressions.
- **Open:** These validators are structural and offline. They are not official Fabric schema
  validation, and a `valid: true` artifact is still a dry-run skeleton.

### Warehouse views are converted

- **Expected:** A generated Warehouse view must not present raw GoogleSQL as T-SQL.
- **Implemented:** View bodies are translated GoogleSQL → T-SQL. When conversion fails or the
  result uses constructs Fabric Warehouse does not support, the view body is omitted, the artifact
  is marked invalid, and the candidate conversion is emitted as `--` comments for review.
- **Open:** Conversion is static. Result-set equivalence between the source view and the reviewed
  T-SQL is unproven and requires parity testing.

### Pipelines use named connection references

- **Expected:** Generated pipelines must not carry connection strings, and `triggers` must not be
  modeled as a pipeline property.
- **Implemented:** Connection strings are replaced by named connection references bound to managed
  identity. `triggers` moved out of `properties` to a sibling key, because triggers are separate
  Fabric resources.
- **Open:** The connection names and identity bindings are placeholders for review. They are not
  resolved against a workspace and grant no access.

### Deterministic paths across platforms

- **Implemented:** Manifest paths use POSIX separators, so generated output is byte-identical on
  Windows and Linux.

### Artifact validation runs last

- **Implemented:** Validation now runs after every artifact is written, so `parity-evidence.json`
  and `deployment-manifest.json` are covered by the credential scan and the structural checks.
  Previously they were written after validation and escaped both.

### `deployment-check` blocks on more conditions

- **Implemented:** Readiness blocks on `FAIL` findings and blockers, failed parity, `redesign`
  components, and pending manual review, in addition to manifest integrity and unsupported
  components.
- **Open:** `ready_for_review` remains a local gate result. It never means deployable.

### Single SQL conversion stack

- **Expected:** One SQL conversion implementation, and no path that silently reports `direct`.
- **Implemented:** `sql_assessment` delegates to the `converter/` package (`SqlConverter`), so
  `converter/` is no longer dead code. SQL compatibility is the worst of the converter verdict, the
  detected semantic risks, and the mapping decision; it never defaults to `direct`. A non-SQL
  routine body, such as a JavaScript UDF, is `redesign` and emits no converted SQL.
- **Open:** Conversion remains offline. Transformed SQL still requires source-versus-target parity
  evidence.

### Parity is recomputed from evidence

- **Expected:** A caller-declared parity `status` must never be trusted.
- **Implemented:** Every check is derived from its own `source`/`target` payload. A declared
  `passed` with no payload resolves to `not_run`. When a declared status contradicts the evidence,
  the check records `declaredStatus` alongside the computed status. The `type` check was removed
  because it had no comparator. The check set is now exactly `schema`, `row_count`, `checksum`,
  `aggregate`, `null_distribution`, `sample`, and `sql_result`. Applicability is keyed on
  data-bearing kind — table, external table, view, materialized view — not on whether columns
  happened to be captured.
- **Open:** All comparisons consume supplied evidence. No source or Fabric query is executed, so
  runtime data parity remains unestablished.

### Scoring is per component

- **Implemented:** Type risk and SQL risk fold into the owning component. The score is scaled by
  evidence coverage, and a component with a `FAIL` blocker scores zero. Schema width no longer
  affects the score.

### Type findings are attributable

- **Implemented:** A type finding's `source_id` is the owning object rather than the bare type name
  such as `STRUCT`. Assessment emits one finding per distinct type per object and lists the
  affected column paths.

### Evidence rules cover core BigQuery kinds

- **Implemented:** `TABLE` requires `columns` and `size_bytes`; `EXTERNAL_TABLE` requires
  `columns`; `VIEW` requires `sql`; `MATERIALIZED_VIEW` requires `sql` and `columns`; `ROUTINE`
  and `PROCEDURE` require `language` and `sql`; `SQL_SCRIPT` requires `sql`. A recorded boolean
  counts as evidence in either state, so `streaming: false` is no longer reported as missing. The
  full matrix is in [INVENTORY_SCHEMA.md](INVENTORY_SCHEMA.md#required-evidence-by-kind).

### Strategy selection is weighted by compatibility

- **Implemented:** Candidate targets are weighted by compatibility — `direct` 3, `transform` 2,
  `redesign` 1, `unsupported` 0 — rather than by target identity. The data-target preference signal
  is symmetric for Warehouse and Lakehouse. Multi-table transactions pin Warehouse as a hard
  constraint. The tie-break is recorded as an explicit signal, and `scores` reports only the three
  candidate primary targets.

### Discovery pseudonymizes principals

- **Implemented:** Principal identities in access evidence — `userByEmail`, `groupByEmail`,
  `domain`, `iamMember`, and equivalents — are recorded as `principal:<12 hex>`. The value is
  stable across runs and non-reversible. Paging is bounded and rejects repeated page tokens.
- **Open:** Pseudonymization protects the artifact. It does not make dataset access entries an
  effective-access calculation; `SECURITY_EFFECTIVE_ACCESS_REVIEW` still applies.

### Validated canonical inventory contract

- **Expected:** Canonical JSON inventories should reject malformed identifiers, unsupported object
  kinds, duplicate source IDs, invalid column or dependency structures, and negative size evidence
  before model coercion, while preserving explicit `null` as valid optional `size_bytes` evidence.
- **Implemented:** `JsonInventoryProvider` validates `project_id`, dataset/object IDs and names,
  known `ObjectKind` values, duplicate source IDs, column structures, dependency arrays, and
  non-negative integer `size_bytes` before constructing the canonical model. Boolean sizes are
  rejected; explicit `null` remains valid.
- **Validated:** `python -m pytest tests/test_models.py tests/test_cli.py` passes in CI.
- **Open:** These are deterministic offline input checks only. They do not validate official
  BigQuery or Fabric schemas, credentials, runtime behavior, data parity, or deployment readiness.

### Validated static-quality gate closure

- **Expected:** The repository's local typing and lint gates complete without errors while legacy
  callers retain the `MultiStatementConversionResult` compatibility surface and schema comparison
  accepts sequences of mappings.
- **Implemented:** The stale `models_broken.py` backup was removed; source and test typing now
  narrow optional results before use; schema comparison accepts sequence-based mapping input; and
  the legacy conversion-result compatibility surface remains available.
- **Validated:** `python -m pyright` returns 0 errors, and `python -m ruff check src tests` passes.
- **Open:** These local static checks do not validate generated artifacts against official Fabric
  schemas or APIs, establish runtime or data parity, or authorize deployment.

### Validated offline artifact-package validation

- **Expected:** Validation of a generated package should cover generated subdirectories while
  retaining notebook, JSON, and SQL checks, and should add KQL syntax and pipeline predecessor
  guards where those artifact shapes are present.
- **Implemented:** `validate_directory` recursively scans generated subdirectories. It applies KQL
  syntax guards to `.kql` files and predecessor checks to pipeline JSON with `properties.activities`,
  while preserving the existing notebook, JSON, and SQL checks.
- **Validated:** `python -m pytest tests/test_artifact_validation.py` passes in CI.
- **Open:** These are offline structural checks only. They do not validate generated artifacts
  against official Fabric schemas or perform deployment validation.

### Validated cross-artifact consistency

- **Expected:** Package validation should ensure target-manifest entries resolve to generated
  artifact manifest records, referenced generated files exist, and invalid artifacts cannot be
  treated as ready by non-review targets while intentional review-only scaffolds remain available.
- **Implemented:** `validate_directory` compares target entries with category-matched generated
  manifest records, verifies each referenced path, and fails for an invalid artifact referenced by
  a target whose `manualReview` flag is false. Invalid artifacts referenced by review-only targets
  are allowed.
- **Validated:** `python -m pytest` passes in CI (364 passed at this release).
- **Open:** This is deterministic, offline consistency validation only. It does not validate
  official Fabric schemas or APIs, execute workloads, establish runtime/data parity, or authorize
  deployment.

### Validated contract-hardening milestone

- **Expected:** Invalid artifact and parity evidence inputs must fail deterministically without
  raising or implying a successful comparison. A non-object JSON root should produce a validation
  error; negative or boolean row counts, duplicate schema field names, and malformed nested fields
  should produce parity status `not_run`.
- **Implemented:** Artifact validation rejects non-object JSON roots with a deterministic error.
  Parity comparison rejects negative/boolean row counts, duplicate schema field names, and malformed
  nested fields as `not_run`.
- **Validated:** `python -m pytest tests/test_artifact_validation.py tests/test_parity.py` passes
  in CI.
- **Open:** These checks remain offline-only. They do not validate official Fabric schemas, execute
  source or target workloads, establish runtime/data parity, or authorize deployment.

### Validated CLI and deployment-readiness failure paths

- **Expected:** Invalid local inputs and generated artifacts must fail deterministically, and
  deployment readiness must block unsafe or incomplete plans before any cloud operation.
- **Implemented:** A missing inventory returns exit code `2`; malformed inventory returns exit code
  `5`; tampered deployment-manifest verification returns exit code `5`. `deployment-check` blocks
  invalid artifact validation, `FAIL` findings and blockers, failed parity, `redesign` components,
  pending manual review, unresolved dependencies, and unsupported target components.
- **Validated:** `python -m pytest tests/test_cli.py tests/test_deployment_readiness.py` passes in
  CI.
- **Open:** These are offline guards only. They do not validate official Fabric schemas or APIs,
  execute source or target workloads, establish runtime/data parity, or authorize deployment. Cloud
  operations remain outside the default path.

### Validated assessment test guide

- **Expected:** Reviewers can reproduce the offline fixture assessment and understand the live
  BigQuery read-only path, generated evidence, and `WARN`/`FAIL` triage without cloud mutation.
- **Implemented:** README and the migration runbook document the exact install, pytest, validate,
  inventory, assess, plan, generate, manifest, and deployment-check commands. They document
  `findings`, `evidence_summary`, `discovery_coverage`, `parity_summary`, `stageReadiness`,
  `manualReview`, `manualReviewReasons`, `processingStage`, and exit code `3`.
- **Validated:** Documentation commands and artifact names were checked against the current CLI
  workflow and generated-package contract. The static-quality gates pass with `python -m pyright`
  and `python -m ruff check src tests`.
- **Open:** No authorized live-GCP sandbox run is claimed for any adapter, including the BigQuery,
  Dataflow, Dataproc, Dataform, and Composer adapters that exist in code. Workflows, Pub/Sub, GCS,
  Looker, Vertex AI, Dataplex, Cloud SQL, and Spanner have no live adapter and remain offline
  payload normalization and assessment inputs.

### Validated performance-layout assessment

- **Expected:** Assessment should identify large BigQuery objects whose recorded inventory
  metadata has no partitioning or clustering evidence, while keeping the result as a design-review
  recommendation rather than a measured performance conclusion.
- **Implemented:** For `TABLE`, `EXTERNAL_TABLE`, and `MATERIALIZED_VIEW` objects at or above
  `10 GiB`, assessment emits deterministic `WARN` findings for missing recorded partitioning or
  clustering evidence: `PERFORMANCE_PARTITION_REVIEW` and `PERFORMANCE_CLUSTERING_REVIEW`.
- **Validated:** `python -m pytest tests/test_assessment.py` passes in CI.
- **Open:** Measured workload telemetry and runtime benchmarking remain open. The findings do not
  perform automatic tuning and do not establish scan, refresh, or query-performance outcomes.

### What v0.1.0 proves

- One canonical model can represent BigQuery and the surrounding GCP data platform.
- Fabric targets are selected from workload evidence rather than a universal Lakehouse default.
- Lakehouse/Notebook preferences work as advisory signals.
- Existing Composer DAGs remain Airflow candidates when requested.
- GoogleSQL can be parsed and classified through an AST before translation is attempted.
- Dependency waves, component mappings, findings, lineage, and dry-run artifacts are deterministic.

### Validated processing-chain example

- **Expected:** The generated target manifest makes the complete BigQuery/GCP-to-Fabric processing chain reviewable, assigning each known source kind a processing stage and preserving a deterministic dependency order.
- **Implemented:** `fabric/target-manifest.json` includes `processingStage`, `wave`, and `dependencies` for every entry. Known source kinds are categorized as `ingestion`, `storage`, `transformation`, `orchestration`, `consumption`, `governance`, `integration`, or `operational`.
- **Validated:** `python -m pytest tests/test_cli.py` passes in CI.
- **Open:** This is a deterministic dry-run review artifact only. It does not execute processing paths, connect to GCP or Fabric, deploy anything, or establish runtime data parity.

### Validated Composer pipeline schedule compatibility

- **Expected:** Composer DAG schedules should use one canonical inventory field while legacy
  inventories retain preset Fabric pipeline trigger mapping.
- **Implemented:** Composer normalization writes `schedule_interval` and retains `schedule` for
  compatibility. Pipeline generation reads `schedule_interval` first and falls back to `schedule`;
  `@daily`, `@hourly`, and `@weekly` map to the corresponding Fabric pipeline triggers.
- **Validated:** `python -m pytest tests/test_discovery.py tests/test_artifact_generation.py`
  passes in CI.
- **Open:** Raw cron expressions remain review-required and are not automatically mapped. This
  behavior is deterministic dry-run generation only; it does not establish trigger execution,
  scheduling parity, or production readiness.

### Validated schedule-trigger start time

- **Expected:** Generated schedule triggers should start from the current UTC time rather than a
  stale fixed date.
- **Implemented:** Supported generated pipeline schedule triggers use the Fabric expression
  `@utcNow()` for `startTime` instead of the fixed `2024` date.
- **Validated:** `python -m pytest tests/test_artifact_generation.py` passes in CI.
- **Open:** Generated pipeline definitions still require validation against the official Fabric/ADF
  schema and deployment validation. This fix is deterministic dry-run generation behavior and does
  not establish trigger execution, scheduling parity, or production readiness.

### Validated pipeline activity resilience defaults

- **Expected:** Generated operational pipeline activities should receive deterministic retry and
  secure-policy defaults, while the failure handler should retain its specialized secure policy.
- **Implemented:** Operational activities default to `retry: 3`, `retryIntervalInSeconds: 30`,
  `secureInput: true`, and `secureOutput: true`. The failure handler keeps its specialized secure
  policy rather than inheriting the operational-activity defaults.
- **Validated:** `python -m pytest tests/test_artifact_generation.py` passes in CI.
- **Open:** Retry behavior still requires validation against the official Fabric/ADF schema and
  runtime validation. These deterministic dry-run defaults do not establish retry execution,
  failure-handler parity, deployment readiness, or production readiness.

### Validated Composer adapter evidence

- **Expected:** Composer DAG evidence must retain a usable runtime-version signal and declared task
  connection names without serializing connection configuration or secrets. Assessment must treat a
  declared empty connection list as complete evidence while preserving a missing list as incomplete.
- **Implemented:** Normalization sets `runtime_version` from the Composer image version when
  available, otherwise the sanitized environment-version label, otherwise `unknown`. It inventories
  declared names from `conn_id`, `connection_id`, `gcp_conn_id`, and `google_cloud_conn_id` only.
  `connections: []` explicitly records that no task declared a connection; assessment treats this
  as complete Composer evidence, whereas an absent `connections` field remains incomplete.
- **Validated:** `python -m pytest tests/test_discovery.py tests/test_assessment.py` passes in CI.
- **Open:** Connection configuration, secret bindings, and effective runtime access are not
  serialized or inferred. They require manual review. An opt-in read-only Composer adapter exists
  (`--composer-region`), but it has not been exercised against an authorized GCP sandbox and proves
  no runtime access parity.

### Validated Dataproc adapter evidence

- **Expected:** Normalized Dataproc jobs retain canonical language and runtime-version evidence so
  assessment can distinguish supported source detail from absent or ambiguous metadata.
- **Implemented:** Job discovery maps PySpark to `language: python`, Spark SQL and Hive to
  `language: sql`, and Pig to `language: pig`; unsupported or ambiguous job types use `unknown`.
  It preserves the existing `runtime` job classification. `runtime_version` is inherited from the
  referenced cluster's `config.softwareConfig.imageVersion` when present, otherwise `unknown`.
  Assessment treats `unknown` and `not specified` as missing evidence rather than complete
  evidence.
- **Validated:** `python -m pytest tests/test_discovery.py tests/test_assessment.py` passes in CI.
- **Open:** Runtime-version readiness cannot be complete until the value is supplied or Dataproc
  is re-discovered from a payload whose referenced cluster includes `imageVersion`.

### Validated stage-readiness summary

- **Expected:** The generated target manifest provides a deterministic per-stage compatibility
  rollup that helps reviewers prioritize migration work without implying runtime readiness.
- **Implemented:** `fabric/target-manifest.json` has a top-level `stageReadiness` object for every
  `processingStage` represented by entries; absent stages are omitted. Each stage includes `total`,
  counts for `direct`, `transform`, `redesign`, and `unsupported`, `manualReview`, and `readiness`.
  `readiness` is the rounded weighted average of component compatibility with `direct=100`,
  `transform=80`, `redesign=50`, and `unsupported=0`.
- **Validated:** `python -m pytest tests/test_cli.py` passes in CI.
- **Open:** The rollup prioritizes migration review only. It is not proof of execution, parity,
  security remediation, or deployment readiness.

### Validated Eventhouse empty-schema artifact guard

- **Expected:** An Eventhouse artifact whose source schema has no columns is invalid and must not
  produce executable KQL definitions; normal Eventhouse schema generation remains unchanged.
- **Implemented:** The generated Eventhouse artifact emits review comments only, omitting KQL
  `CREATE TABLE`, ingestion mapping, and materialized-view statements. It includes a `REDESIGN`
  warning, and the artifact manifest propagates `valid: false` for the affected artifact.
- **Validated:** `python -m pytest tests/test_artifact_generation.py` passes in CI.
- **Open:** This structural dry-run guard is not official Fabric validation or deployment. An
  approved artifact still requires Fabric schema validation and an explicit deployment workflow.

### Validated Eventstream dry-run review scaffold

- **Expected:** Generated Eventstream output must be clearly non-deployable when BQToFabric cannot
  emit an official Fabric Eventstream definition. It must not invent connection identifiers.
- **Implemented:** The Eventstream artifact sets `deployable: false` and `valid: false`. Its source
  node uses `connectionReference: review_required` instead of a fabricated `connectionId`, and
  includes explicit authoring TODOs. The artifact manifest propagates `valid: false`.
- **Validated:** `python -m pytest tests/test_artifact_generation.py` passes in CI.
- **Open:** This is a deterministic dry-run review scaffold, not an official Fabric Eventstream
  definition. Author it against the official Fabric API/schema and supply approved connections
  before deployment.

### Validated semantic-model empty-schema guard

- **Expected:** A semantic model for a table, view, or materialized view without discovered
  columns must not reference a first column or produce a deployable definition. Schema-backed
  semantic-model generation must remain unchanged.
- **Implemented:** The generator returns an invalid review-only scaffold with `valid: false`,
  `deployable: false`, and `validationStatus: pending_source_schema`. It omits tables, measures,
  relationships, and connection placeholders, and emits a `REDESIGN` warning requiring source
  schema discovery and regeneration.
- **Validated:** `python -m pytest tests/test_artifact_generation.py` passes in CI.
- **Open:** This dry-run guard is not official Fabric semantic-model schema/API validation. Validate
  the regenerated semantic model before deployment.

### Validated semantic-model count-measure fidelity

- **Expected:** Generated numeric `Count of <column>` measures should count populated values, as
  their names imply.
- **Implemented:** Numeric count measures use DAX `COUNT` rather than `COUNTBLANK`.
- **Validated:** `python -m pytest tests/test_artifact_generation.py` passes in CI.
- **Open:** Generated semantic models remain dry-run review artifacts and still require validation
  against the official Fabric semantic-model schema/API before deployment.

### Validated migration-plan findings section

- **Expected:** The human-readable migration plan should make assessment `WARN` and `FAIL` findings
  actionable without requiring reviewers to open `assessment.json` first.
- **Implemented:** Generated `migration-plan.md` includes a `Findings` section. Each finding lists
  `severity`, `code`, `category`, `source`, and `message`, preserving the assessment evidence inside
  the dry-run report.
- **Validated:** `python -m pytest tests/test_cli.py` passes in CI.
- **Open:** Findings in the report are review evidence only. They do not prove remediation,
  deployment readiness, runtime parity, or security parity.

### Validated migration-plan assessment summary

- **Expected:** The human-readable migration plan should provide deterministic rollups that help
  reviewers prioritize findings, processing stages, and manual-review work.
- **Implemented:** Generated `migration-plan.md` includes an `Assessment summary` with a Gate/Value
  table for total, `FAIL`, and `WARN` findings, components requiring manual review, `Parity checks`,
  and `Parity not run` totals. It also includes readiness percentage and manual-review counts by
  processing stage, and deterministic manual-review reason frequencies. `Parity not run` means
  runtime evidence is absent, not that parity succeeded. Existing findings, component, evidence,
  parity, and migration wave sections remain in the report; the detailed `Parity evidence` table
  is unchanged.
- **Validated:** The reporting change was validated with the focused CLI tests and the full test
  suite; Ruff is clean for the changed reporting and CLI test files.
- **Open:** These are deterministic review summaries only. They do not prove deployment readiness,
  runtime parity, security remediation, or finding remediation.

### Validated assessment-report summary

- **Expected:** Report generation should emit a deterministic summary suitable for dashboards and
  HTML reports while retaining the detailed assessment contract.
- **Implemented:** `write_reports` emits `assessment-summary.json` with `projectId`, `score`,
  `evidenceCoverage`, `architecture`, `componentCount`, `findingCounts`, `targetSummary`,
  `compatibilitySummary`, `discoveryCoverage`, `paritySummary`, `manualReviewCount`, `manualReviewReasons`,
  `unresolvedDependencies`, `blockers`, and `status`. The detailed `assessment.json` remains
  available and is not replaced.
- **Validated:** `python -m pytest tests/test_cli.py tests/test_deployment_readiness.py` passes in
  CI.
- **Open:** The summary is an offline presentation artifact. It does not validate official Fabric
  schemas or APIs, execute workloads, establish runtime or data parity, remediate findings, or
  authorize deployment.

### Validated streaming downstream guardrail

- **Expected:** A `DATAFLOW_JOB` whose `properties.streaming` is `true` causes every transitive
  downstream canonical object to be reviewed as a streaming consumer.
- **Implemented:** Assessment adds the `WARN` finding `STREAMING_DOWNSTREAM_REVIEW` to every
  downstream object, requiring review of deduplication, idempotency, and out-of-order delivery.
  Planner output marks those consumers `manual_review`; the source streaming job is already
  `redesign`/`manual_review`.
- **Validated:** `python -m pytest tests/test_assessment.py` passes in CI.
- **Open:** The guardrail evaluates static inventory dependency evidence only. It does not
  execute or monitor live stream processing, validate data, or deploy Fabric artifacts.

### Validated actionable manual-review reasons

- **Expected:** A `PlanItem` marked `manual_review` retains that decision flag and records a
  deterministic reason list so reviewers can act on the specific planning condition. Both the
  human-readable migration plan and generated target manifest expose the decision and reasons.
- **Implemented:** `PlanItem.manual_review_reasons` uses 13 stable codes:
  `assisted_evidence`, `cycle_or_unresolved_dependency`,
  `depends_on_incomplete_dataform_compilation`,
  `depends_on_incomplete_external_adapter`, `external_dependency`, `incompatible_mapping`,
  `incomplete_dataform_compilation`, `incomplete_external_adapter`,
  `missing_required_evidence`, `parity_failed`, `security_review`, `sql_incompatibility`, and
  `streaming_downstream_review`. Reasons are recorded independently, so one component can carry
  several instead of only the first matching condition. `migration-plan.md` renders `manual_review`
  and the reason codes; `fabric/target-manifest.json` exposes the matching `manualReview` and
  `manualReviewReasons` fields. `manual_review` remains the decision flag; reasons make the
  decision actionable.
- **Validated:** `python -m pytest tests/test_assessment.py tests/test_cli.py` passes in CI.
- **Open:** This is deterministic, offline planning metadata only. It does not make cloud calls,
  change deployment behavior, establish runtime compatibility, or resolve the listed review
  conditions automatically.

### Validated dataset access review guardrail

- **Expected:** Live dataset `access` entries provide redacted dataset-level evidence only and
  cannot be treated as proof of effective project, organization, group, or inherited IAM access.
- **Implemented:** Discovery serializes every dataset access entry as a redacted `security_policy`
  record with `evidence_scope: dataset_access_entry`, pseudonymizing each principal identity as a
  stable, non-reversible `principal:<12 hex>` value. Assessment emits `FAIL`
  `SECURITY_EFFECTIVE_ACCESS_REVIEW`, requiring manual security review. Discovery makes no IAM API
  calls and does not extract project/org IAM, connection IAM, BigQuery Data Policies, policy tags,
  or distinct row access policies.
- **Validated:** `python -m pytest tests/test_discovery.py tests/test_assessment.py` passes in CI.
- **Open:** This is not an effective-access calculation and establishes no source-rights or
  Fabric-security parity. Manual security review must account for project, organization, group,
  inherited IAM, and the unextracted governance controls.

### Validated discovery provenance

- **Expected:** Assessment evidence must distinguish objects obtained through the BigQuery and
  explicitly requested regional Dataflow APIs from canonical JSON inventory and supplied external
  GCP payloads, without claiming freshness or live discovery coverage for unimplemented services.
- **Implemented:** `BigQueryObject.discovered_from` defaults imported canonical JSON to `inventory`;
  the live BigQuery provider stamps `bigquery_api`; the Dataflow, Composer, Dataproc, and Dataform
  adapters stamp `dataflow_api`, `composer_api`, `dataproc_api`, and `dataform_api`; and normalized
  external GCP payloads stamp `external_payload`. Assessment exposes provenance per object in
  `evidence_summary` and reports deterministic counts per source in
  `AssessmentReport.discovery_coverage`.
- **Validated:** `python -m pytest tests/test_models.py tests/test_discovery.py
  tests/test_gcp_components.py tests/test_assessment.py` passes in CI.
- **Open:** Provenance distinguishes collection paths only. It does not validate metadata freshness.
  The canonical `discovered_from` values are `inventory`, `bigquery_api`, `dataflow_api`,
  `composer_api`, `dataproc_api`, `dataform_api`, and `external_payload`. Workflows, Pub/Sub, GCS,
  Looker, Vertex AI, Dataplex, Cloud SQL, and Spanner have no live adapter and therefore never
  produce an API provenance value.

### Validated incomplete external-payload guardrail

- **Expected:** An externally supplied component marked `discovered_from: external_payload` that
  lacks required offline evidence must fail closed without implying a live adapter, and its complete
  downstream dependency chain must require review.
- **Implemented:** Assessment emits exactly one `FAIL` `EXTERNAL_PAYLOAD_INCOMPLETE_ADAPTER`
  finding in category `adapter`, explaining that offline evidence must be completed because no live
  adapter is implemented. The planner marks the component and all direct/transitive dependents
  `manual_review`. These review states are not unresolved dependencies:
  `unresolved_dependencies` remains for missing or external source IDs and dependency cycles.
- **Validated:** `python -m pytest tests/test_assessment.py` passes in CI.
- **Open:** The behavior is offline and non-destructive. It makes no cloud calls and does not
  implement external GCP live adapters; users must supply complete offline evidence before a
  reviewed migration decision can rely on the affected component.

### Validated Dataform adapter evidence

- **Expected:** Successfully discovered Dataform compilation targets must aggregate deterministic
  evidence on the corresponding repository and workflow records. Explicitly empty or false evidence
  must remain known, while a failed compilation-detail request must stay incomplete and block
  assessment rather than being mistaken for a successful empty result.
- **Implemented:** Repository and workflow records receive `models`, `assertions`, and
  `incremental` evidence from successful compiled targets and edges. `models` is the sorted list of
  compiled table/view target names; `assertions` and `incremental` are booleans. `models: []`,
  `assertions: false`, and `incremental: false` remain complete evidence. A failed detail request
  emits a `dataform_workflow` fallback with `discovered_from: dataform_api`,
  `discovery_incomplete: true`, and `lineage_status: unavailable`; assessment emits `FAIL`
  `DATAFORM_COMPILATION_DETAILS_UNAVAILABLE`, and planning applies
  `incomplete_dataform_compilation` to the fallback and
  `depends_on_incomplete_dataform_compilation` to downstream objects.
- **Validated:** `python -m pytest tests/test_discovery.py tests/test_assessment.py
  tests/test_dataform_conversion.py` passes in CI.
- **Open:** A fallback does not recover the compilation graph. Re-run discovery after Dataform API
  or access recovery before relying on lineage-dependent migration decisions.

### What v0.1.0 does not prove

- Completeness against a live GCP organization or project.
- Executable equivalence of generated SQL, Spark, Airflow, pipeline, or Fabric definitions.
- Data parity, performance parity, security parity, refresh success, or deployment success.
- Production readiness of generated notebook and pipeline skeletons.

## Delivery principles

1. **Evidence before automation.** A stage cannot claim success without a check that proves it.
2. **Dry-run first.** Discovery is read-only; deployment remains explicit and opt-in.
3. **Native connectors first.** Use Fabric's BigQuery connector and OneLake capabilities before introducing custom movement code.
4. **Preserve source intent.** Airflow remains Airflow when that reduces migration risk; each workload retains an appropriate target.
5. **Fail closed on security.** Missing policy equivalence is a blocker, not a warning to ignore.
6. **Deterministic artifacts.** The same inventory and configuration must produce byte-stable output.

### Validated artifact-order determinism

- **Expected:** Equivalent inventories must generate the same artifact paths and bytes regardless
  of component ordering, and distinct source IDs must never overwrite each other's artifacts.
- **Implemented:** `ArtifactGenerator` writes each artifact category in sorted source-ID order,
  serializes JSON artifacts, manifests, and notebooks with sorted keys, and aggregates warnings in
  source-ID order. Every artifact filename combines a filesystem-safe source ID with the first 12
  hexadecimal characters of that source ID's SHA-256 digest; generated manifest paths use those
  filenames.
- **Validated:** `python -m pytest tests/test_artifact_generation.py` passes in CI. The test covers
  reversed component ordering, same-name source objects, and source IDs that normalize to the same
  safe text. Manifest paths use POSIX separators, so output is byte-identical across platforms.
- **Open:** This deterministic filename contract does not validate generated definitions against
  Fabric schemas or deploy them.

## Release tracks

### v0.2 — Live GCP discovery *(in progress)*

**Goal:** replace hand-authored inventories with reproducible, read-only discovery.

- **Expected:** An authenticated user can produce a deterministic, credential-safe canonical
  inventory from the supported BigQuery metadata surface, then use the existing offline assessment
  workflow without claiming IAM or governance-policy completeness.
- **Implemented:** `bqtofabric discover` uses user Application Default Credentials with
  `https://www.googleapis.com/auth/bigquery.readonly`. It discovers datasets, tables, views,
  materialized views, external tables, routines, procedures, BQML models, jobs, scheduled-query
  transfer configurations, connections, and dataset GET `access` entries. Access entries are
  redacted into canonical `security_policy` records with `evidence_scope:
  dataset_access_entry`. Assessment emits `FAIL` `SECURITY_EFFECTIVE_ACCESS_REVIEW`, requiring
  manual security review because this evidence does not establish effective project, organization,
  group, or inherited IAM access. It makes no IAM API calls and does not extract project/org IAM,
  connection IAM, BigQuery Data Policies, policy tags, or distinct row access policies. Discovery
  failures return exit code `3` without printing provider response bodies. When one or more
  `--dataflow-region` values are explicitly supplied, it also lists regional Dataflow jobs with
  pagination, redaction, deterministic mapping, and `discovered_from: dataflow_api`. A job's
  `type` maps to `properties.streaming`; `portable` and `connector_compatible` are preserved only
  when present in the payload, never inferred. Opt-in read-only live adapters also exist for
  Dataproc (`--dataproc-region`), Dataform (`--dataform`, `--dataform-location`), and Composer
  (`--composer-region`). Those four non-BigQuery adapters request the
  `https://www.googleapis.com/auth/cloud-platform.read-only` scope, which is broader than the
  BigQuery path's `bigquery.readonly`. Without an adapter flag, discovery remains BigQuery-only.
  Principal identities in access evidence are pseudonymized as `principal:<12 hex>`; paging is
  bounded and rejects repeated page tokens. Workflows, Pub/Sub, GCS, Looker, Vertex AI, Dataplex,
  Cloud SQL, and Spanner remain offline normalization/assessment only.
- **Validated:** Discovery mapping, deterministic serialization, redaction, pseudonymization,
  pagination, and provider-failure body suppression are covered by offline fixture tests.
- **Open:** No authorized live-GCP sandbox test has run for any adapter. The adapters exist; the
  sandbox verification does not. Required API enablement, dataset metadata visibility,
  project-level job-history visibility, and per-region Dataflow, Dataproc, and Composer visibility
  must be verified in an authorized project before any live metadata parity claim. The broader
  `cloud-platform.read-only` scope requested by the non-BigQuery adapters must be reviewed and
  approved by a security administrator before first use. Project/org IAM, connection IAM, distinct
  row access policies, data policies, policy tags, and the remaining external-family adapters
  remain unimplemented and require security review where they affect migration decisions.

- **Implement `GoogleCloudInventoryProvider` behind an optional `gcp` dependency group.** *Done.*
  The provider consumes BigQuery REST resources through a `BigQueryMetadataClient` protocol, so
  discovery is exercised offline against committed API payloads and needs no credentials to test.
- **Redact credential-like metadata by construction.** *Done.* Labels and properties pass through
  `redact`, which replaces secret-like keys and values with `[redacted]`. Failed requests raise
  `DiscoveryError` carrying only a status code, because response bodies can echo request headers.
- **Discover BigQuery datasets, schemas, views, routines, partitioning, sizes, labels, locations.**
  *Done.* Tables, views, materialized views, external tables, routines, procedures, and BQML models
  map to canonical objects. Legacy REST type names (`INTEGER`, `FLOAT`, `BOOLEAN`, `RECORD`) are
  normalized to `INT64`, `FLOAT64`, `BOOL`, and `STRUCT`; without that the type mapper would treat
  every discovered column as an unknown type.
- **Capture cross-project dependencies and unresolved references explicitly.** *Done.* View and
  routine bodies are parsed with `sqlglot`; two-part and bare references are completed with the
  owning project and dataset. Bodies that do not parse — JavaScript UDFs, for example — record an
  `unresolved_references` note instead of a guessed dependency.
- **Add a CLI command for live discovery and sanitized export.** *Done.* `bqtofabric discover`
  writes a deterministic canonical inventory and returns a dedicated exit code when credentials
  are unavailable.
- **Discover BigQuery jobs, scheduled queries, connections, and access policies.** *Done.*
  Jobs preserve type, SQL dependencies, location, state, priority, and write dispositions;
  scheduled queries preserve schedule, owner, parameters, and transfer identity; connections and
  dataset access policies are sanitized into canonical components.
- **Normalize external GCP adapter payloads into canonical `components`.** *Done.* The shared
  normalizer redacts metadata, preserves dependencies, sorts output deterministically, and ignores
  unknown kinds without inventing a source type.
- **Add the first live external adapter for regional Dataflow jobs.** *Done and validated.*
  Repeatable `--dataflow-region` values opt into read-only regional listing with pagination,
  redaction, deterministic mapping, and `discovered_from: dataflow_api`. Streaming classification
  comes from the payload `type`; portability and connector compatibility are never inferred when
  evidence is absent. Offline tests cover mapping, pagination, redaction, deterministic output,
  missing-evidence assessment, CLI merge, and BigQuery-only backward compatibility.
- **Add live adapters for Dataproc, Dataform, and Composer.** *Implemented; sandbox verification
  open.* Each is opt-in through an explicit CLI flag, read-only, redacting, and pseudonymizing, and
  each requests the `cloud-platform.read-only` scope. None has been exercised against an authorized
  GCP sandbox.
- **Add live adapters for Workflows, Pub/Sub, GCS, Looker, Vertex AI, Dataplex, Cloud SQL, and
  Spanner.** *Open.* Endpoint coverage, permissions, and an authorized sandbox are still required;
  normalization alone does not claim live discovery.

**Exit gate**

- A read-only integration test against an authorized sandbox inventories all enabled adapters.
  *`not_run`.* The BigQuery, Dataflow, Dataproc, Dataform, and Composer adapters are validated by
  offline fixture tests only. No authorized live sandbox run has verified them individually or
  together, and no local check can promote this gate.
- No secret value appears in logs, JSON, snapshots, or exception messages. *Proven* by redaction
  tests over secret keys, nested private keys, bearer values, and a failing request.
- Repeated discovery of an unchanged project produces equivalent canonical inventories. *Proven*
  by a determinism test and a committed snapshot of the serialized inventory.

### v0.3 — Conversion workbench *(completed)*

**Goal:** turn assessment recipes into reviewable source conversions.

#### v0.3.0 — SQL Conversion Framework *(completed)*

- **Implemented:** GoogleSQL AST analysis and transpilation to Spark SQL, Spark SQL (Lakehouse), and Fabric Warehouse T-SQL using sqlglot.
- **Implemented:** Intelligent target routing based on object kind, SQL complexity, and workload classification.
- **Implemented:** 30+ SQL pattern detection covering structural (SELECT, CTEs, UNION), joins, aggregation, array/struct, functions, and DML/DDL.
- **Implemented:** Four-level compatibility tracking: DIRECT, TRANSFORM, REDESIGN, UNSUPPORTED.
- **Implemented:** Actionable warnings with line/column or AST node location.
- **Implemented:** Prioritized manual steps with rationale and affected patterns.
- **Implemented:** Negative controls for unsupported constructs (script blocks, JavaScript UDFs, DML in routines, federated queries).
- **Implemented:** 80 golden tests covering all patterns, dialects, and edge cases.
- **Verified:** Ruff clean · Pyright clean · deterministic output. See the authoritative baseline
  above for current suite and coverage figures.

#### Validated SQL semantic-fidelity handling

- **Expected:** Existing supported SQL cases must remain direct, while constructs whose translated
  semantics require review must be identified and downgraded rather than treated as equivalent.
- **Implemented:** The converter detects `SAFE_CAST` and `NOT IN`, assigns `TRANSFORM`
  compatibility, and emits semantic warnings and manual parity steps. Existing supported direct
  cases retain their prior behavior.
- **Validated:** `python -m pytest tests/test_sql_converter.py` passes in CI.
- **Open:** The milestone validates offline conversion behavior only. Source/target SQL execution,
  official Fabric schema validation, and runtime/data parity remain open; transformed SQL requires
  manual parity evidence.

**Conversion Example:**
```python
from bqtofabric.converter import SqlConverter, TargetDialect

converter = SqlConverter()
result = converter.convert(bigquery_obj, TargetDialect.SPARK_SQL)

# result.target_text: converted SQL
# result.compatibility_level: DIRECT/TRANSFORM/REDESIGN/UNSUPPORTED
# result.warnings: specific issues with location
# result.manual_steps: actionable remediation tasks
```

**Compatibility Matrix:**
| Pattern | T-SQL | Spark SQL | PySpark |
|---------|-------|-----------|---------|
| SELECT | ✓ Direct | ✓ Direct | ✓ Direct |
| JOINs | ✓ Direct | ✓ Direct | ✓ Direct |
| Window Functions | ✓ Direct | ✓ Direct | ⚠ Transform |
| UNNEST | ⚠ Transform | ⚠ Transform | ✓ Transform |
| Struct Types | ⚠ Transform | ✓ Transform | ✓ Direct |
| QUALIFY | ⚠ Transform | ⚠ Transform | ⚠ Transform |
| Script Blocks | ✗ Unsupported | ✗ Unsupported | ✗ Unsupported |
| JavaScript UDF | ✗ Unsupported | ✗ Unsupported | ✗ Unsupported |

### v0.3.1 — Spark/Dataproc and Dataform Conversion *(implemented; offline-validated)*

- **Implemented:** Convert Spark/Dataproc code to Fabric notebook review records, including GCS
  path mapping, credential redaction, language/runtime evidence, and manual compatibility steps.
- **Implemented:** Translate Dataform graph evidence, assertions, and incremental-model requirements
  into reviewable Fabric pipeline recipes with deterministic incomplete-lineage blockers.
- **Validated:** Spark, Dataform, and adapter contract tests pass in the full suite.
- **Open:** These conversions remain offline review artifacts; runtime execution and parity are not
  established. `SparkConverter` performs no real Spark code transformation, and generated notebooks
  do not carry over source Dataproc/Spark logic.

#### v0.3.2 — Composer/Airflow Compatibility *(planned)*

- Produce Composer/Airflow compatibility reports for operators, providers, sensors, pools, connections, SLAs, and plugins.

**Exit gates (v0.3 completed)**

- Every conversion records source, target dialect/runtime, compatibility, warnings, and manual steps. ✓
- Golden tests cover representative SQL patterns. ✓
- No regex-only SQL rewriting enters the production conversion path. ✓

### v0.4 — Fabric project generation

**Goal:** generate structurally valid, importable Fabric project definitions.

- **Expected:** Generated Warehouse DDL must preserve existing target objects during dry-run
  generation; it must never emit destructive `DROP TABLE` or `DROP VIEW` statements, and it must
  not present raw GoogleSQL as T-SQL.
- **Implemented:** Warehouse table and scheduled-query targets use create-if-absent behavior and
  explicitly preserve existing objects. Warehouse views are created only when absent through a
  guarded dynamic statement, preserving an existing view definition. View bodies are converted
  GoogleSQL → T-SQL; when conversion fails or produces constructs Fabric Warehouse does not
  support, the body is omitted, the artifact is marked invalid, and the candidate conversion is
  emitted as `--` comments for review.
- **Validated:** `python -m pytest tests/test_artifact_generation.py` passes in CI.
- **Open:** The generated dry-run Warehouse output still requires official Fabric schema and
  deployment validation; this test result does not establish that validation or deployment
  readiness.

- Generate Lakehouse metadata and Delta DDL with Bronze/Silver/Gold layouts.
- Generate Fabric notebooks with valid metadata, parameters, lakehouse bindings, outputs, and dependencies.
- Generate Warehouse schemas, tables, views, procedures, and load scripts.
- Generate Data Pipelines using native BigQuery Copy/Lookup activities and parameterized schedules.
- Generate Eventstream/Eventhouse definitions for supported streaming patterns.
- Generate Airflow Job packages for compatible Composer DAGs.
- Generate semantic-model and Data Science scaffolds for Looker, BQML, and Vertex AI.

**Exit gate**

- Every generated JSON, notebook, SQL file, and item definition passes a format-specific validator.
  *Partially met.* `NotebookValidator`, `TsqlValidator`, and `PipelineValidator` now derive each
  artifact's `valid` flag from real content checks, so validity is no longer asserted by the
  generator. These are structural validators, not the official Fabric schemas, so the gate stays
  open.
- Generated bundles are deterministic and contain no environment-specific secret. *Met offline.*
  Manifest paths use POSIX separators, so output is byte-identical across platforms.
- Unsupported operational bindings remain explicit placeholders rather than fabricated IDs. *Met.*
  Pipelines carry named connection references bound to managed identity instead of connection
  strings, and `triggers` is a sibling key rather than a pipeline property.

### v0.5 — Parity and migration evidence

**Goal:** prove behavior instead of only proving structure.

- **Implemented:** Parity status is recomputed from evidence on every run. A caller-supplied
  `status` is never trusted; each check is derived from its own `source`/`target` payload, a
  declared `passed` with no payload resolves to `not_run`, and a declared status that contradicts
  the evidence is preserved as `declaredStatus` beside the computed status. The `type` check was
  removed because no comparator backed it. The check set is `schema`, `row_count`, `checksum`,
  `aggregate`, `null_distribution`, `sample`, and `sql_result`. Applicability is keyed on
  data-bearing kind — table, external table, view, materialized view — rather than on whether
  columns happened to be captured.
- **Implemented:** Offline source/target schema comparison covers field presence, types,
  nullability, modes, and nested fields with deterministic differences; precision-specific
  extension rules remain open.
- **Implemented:** Offline per-column null-distribution comparison requires valid, non-negative
  `null_count` and `row_count` evidence on each side, with `null_count <= row_count`. It returns
  `passed` only when column sets and values match, `failed` with deterministic differences for
  missing columns or value mismatches, and `not_run` for missing or invalid evidence. Live query
  execution remains open.
- **Implemented:** Offline row-count comparison returns `passed`, `failed`, or `not_run` from
  supplied evidence; live query execution remains open.
- **Implemented:** Offline named aggregate comparison reports deterministic metric differences;
  live aggregate query execution remains open.
- **Implemented:** Offline checksum evidence comparison returns `passed` only when source and
  target provide complete matching algorithm, canonical ordering, and digest; it returns
  `failed` for any difference and `not_run` for missing evidence. Live checksum query
  execution remains open.
- **Implemented:** Offline sample comparison requires each source and target to provide a
  method, ordering, and rows list. It returns `passed` only when all three values match,
  `failed` with deterministic field differences otherwise, and `not_run` when evidence is
  missing or malformed. Live sample query execution remains open.
- **Implemented:** Offline SQL-result comparison requires source and target evidence with an
  approved `query_id`, ordering, and rows list. It returns `passed` only when all three values
  match, `failed` with deterministic field differences otherwise, and `not_run` when evidence
  is missing or malformed. The parity summary includes `sql_result`. Live source/Fabric SQL
  query execution remains open. *Validated by `python -m pytest tests/test_parity.py`, which
  passes in CI.*
- **Implemented:** Add deterministic partitioning and clustering design-review findings from
  recorded inventory size and layout metadata for large table-like objects.
- Add file-size and performance recommendations from measured workloads; measured workload
  telemetry and runtime benchmarking remain open.
- Add security matrices for IAM, policy tags, authorized views, Fabric permissions, and RLS.
- Produce a portable evidence package for architecture review and migration sign-off.

**Exit gate**

- Each migrated object has a parity status: `passed`, `failed`, `not_run`, or `not_applicable`.
- Missing runtime evidence can never be rendered as success.
- Security blockers prevent a production-ready verdict.

### v0.6 — Controlled deployment

**Goal:** deploy reviewed artifacts safely into Microsoft Fabric.

- Add Entra authentication through environment or managed identity boundaries.
- Discover workspaces and capacities without hardcoded IDs.
- Implement plan/apply separation with an immutable deployment manifest.
- **Implemented:** Generate and verify an immutable dry-run manifest with `manifest-verify`;
  authenticated Fabric apply, identity, retries, and rollback remain open.
- **Implemented:** `deployment-check` blocks tampered manifests, invalid artifacts, unresolved
  dependencies, and unsupported components; it returns `ready_for_review`, never `apply`.
- Create and update supported Fabric items through documented APIs.
- Add idempotency, retries, long-running-operation handling, rollback guidance, and audit logs.
- Require explicit confirmation for every mutating operation.

**Exit gate**

- Dry-run and apply produce matching manifests.
- Integration tests deploy to and remove from an isolated Fabric sandbox.
- Reapplying an unchanged bundle is idempotent.
- No credentials or bearer tokens appear in logs or artifacts.

### v1.0 — Production migration program

**Goal:** support repeatable portfolio migration with governance and operational evidence.

- Portfolio dashboards, wave planning, ownership, effort estimates, dependencies, and blockers.
- Incremental migration and change detection for source schema and code evolution.
- Environment promotion across development, test, and production workspaces.
- Plugin contracts for organization-specific mappings and policy controls.
- Versioned inventory, plan, artifact, and evidence schemas with upgrade tooling.
- Release packaging, upgrade notes, support matrix, and operational runbooks.

**Exit gate**

- Two representative migrations complete discovery, conversion, generation, validation, deployment, and parity evidence.
- Backward compatibility is documented and tested for public schemas and CLI commands.
- Production readiness requires runtime evidence; static checks alone cannot grant it.

## Cross-cutting backlog

### Quality and contracts

- JSON Schema for inventory, assessment, plan, and deployment manifests.
- Producer/consumer contract tests between every pipeline stage.
- Stable finding codes and remediation categories rather than message-text coupling.
- Corpus gate over sanitized real-world inventories.
- One owner per implementation path, validated by `scripts/validate_agents.py`.
- Every validated implementation change is followed by a Documentation-agent update comparing
  expected, implemented, validated, and open behavior.

### Security and governance

- Credential-redaction tests for every provider and deployment error path.
- Least-privilege role matrix for GCP discovery and Fabric deployment.
- Data residency and region compatibility checks.
- Purview glossary, classification, lineage, and ownership mapping.

### Developer experience

- Example inventory generator and schema documentation.
- Machine-readable CLI output and CI-friendly exit policies.
- Windows, Linux, and container development instructions.
- Release automation, changelog, contribution guide, and issue templates.

### Performance and scale

- Streaming inventory readers for large estates.
- Cached SQL parsing and parallel assessment with deterministic ordering.
- Portfolio benchmarks for 1K, 10K, and 100K components.
- Memory and runtime budgets enforced in CI.

## Blocked on cloud access

These items cannot be advanced by any local change. Each requires an authorized environment that
this repository does not have.

| Open item | What unblocks it |
|---|---|
| Live-discovery exit gate for BigQuery, Dataflow, Dataproc, Dataform, and Composer | An authorized, read-only GCP sandbox with the required APIs, per-region visibility, and an approved `cloud-platform.read-only` grant |
| Official Fabric schema and API validation of generated artifacts | Access to the official Fabric item schemas/APIs for notebooks, Warehouse SQL, pipelines, Eventstream/Eventhouse, and semantic models |
| Deployment, rollback, and Entra authentication | An isolated Fabric workspace, capacity, and an approved mutating-operation workflow |
| Runtime and data parity | Executed source and target queries against real data; all current parity comparisons consume supplied evidence only |
| Performance benchmarking | Measured workload telemetry; inventory size and layout metadata cannot establish performance |
| Effective IAM parity | Project/org IAM, connection IAM, data policies, policy tags, and row access policies, none of which are extracted |

## Priority now

**Next development priority: close the v0.2 live-discovery exit gate.** Build an authorized,
read-only sandbox integration harness that verifies the BigQuery, Dataflow, Dataproc, Dataform, and
Composer paths together, including API enablement, permissions and the broader
`cloud-platform.read-only` scope, pagination, redaction, principal pseudonymization, deterministic
serialization, and safe provider failures. Do not claim live coverage for Workflows, Pub/Sub, GCS,
Looker, Vertex AI, Dataplex, Cloud SQL, or Spanner until their adapters and sandbox permissions
exist.

After the live-discovery gate, prioritize official format-specific validation for generated Fabric
artifacts, then v0.5 runtime parity evidence. The current offline contracts and the 364-test suite
are strong foundations, but neither static checks nor dry-run generation proves cloud execution,
semantic parity, or deployment readiness.

## Non-goals

- A proprietary BigQuery-to-OneLake data mover when native Fabric connectors meet the need.
- Automatic conversion of unsupported security semantics without human approval.
- Treating DAX as an ETL language.
- Declaring deployment or data parity from static validation alone.
- Forcing every workload into Lakehouse when another Fabric service or Airflow is a better fit.