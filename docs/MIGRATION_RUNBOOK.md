# Migration runbook

## Test the assessment locally

The committed fixture provides a deterministic offline smoke test for the complete assessment
package. It does not call GCP or Fabric:

```powershell
python -m pip install -e ".[dev]"
python -m pytest
python -m pyright
python -m ruff check src tests

$fixture = "tests/fixtures/gcp_ecosystem_project.json"
$output = "artifacts/assessment-smoke"

bqtofabric validate $fixture
bqtofabric inventory $fixture
bqtofabric assess $fixture
bqtofabric plan $fixture --output "$output/plan"
bqtofabric generate $fixture --output "$output/project"
bqtofabric manifest-verify "$output/project/fabric/deployment-manifest.json"
bqtofabric deployment-check "$output/project/fabric"
```

Review `migration-plan.md`, including its `Assessment summary` and `Findings` sections. Then inspect `assessment.json` for
`findings`, `evidence_summary`, `discovery_coverage`, and `parity_summary`; inspect
`fabric/target-manifest.json` for `stageReadiness`, `manualReview`, `manualReviewReasons`, and
`processingStage`; and inspect `fabric/artifact-validation.json` and
`fabric/deployment-manifest.json`.

Also inspect `assessment-summary.json` when feeding a dashboard or HTML report. `write_reports`
creates this deterministic presentation summary with `projectId`, `score`, `evidenceCoverage`,
`architecture`, `componentCount`, `findingCounts`, `targetSummary`, `compatibilitySummary`,
`paritySummary`, `manualReviewCount`, `manualReviewReasons`, `unresolvedDependencies`, `blockers`,
and `status`. It complements rather than replaces the detailed `assessment.json`.

`FAIL` findings block reliance on the affected recommendation until the evidence or compatibility
issue is resolved or explicitly accepted. `WARN` findings require documented design or manual
review. Discovery exit code `3` means the required read-only ADC, API, or metadata visibility could
not be established; it does not indicate a deployment failure or success.

`python -m pyright` and `python -m ruff check src tests` are local static-quality gates. Their
success validates Python typing and lint checks only; it does not validate generated artifacts
against official Fabric schemas or APIs, establish runtime parity, or authorize deployment.

### Review performance-layout findings

Assessment emits deterministic `WARN` findings for `TABLE`, `EXTERNAL_TABLE`, and
`MATERIALIZED_VIEW` objects at or above `10 GiB` when recorded inventory metadata lacks a
partition field or clustering fields. Review `PERFORMANCE_PARTITION_REVIEW` and
`PERFORMANCE_CLUSTERING_REVIEW` in `assessment.json` and the generated `Findings` section.
These are design-review recommendations based on inventory metadata, not measured performance
claims or automatic tuning decisions. Validate this slice with:

```powershell
python -m pytest tests/test_assessment.py -v
```

The focused test passes with `16 passed`. Measured workload telemetry and runtime benchmarking
remain open and are required before making performance or tuning claims.

### Validate generated artifact packages

`validate_artifact` scans persisted `.json`, `.ipynb`, `.sql`, and `.kql` text with
`CredentialScanner`, and reports credential failures using only the finding type, never the
matched secret value. `validate_directory` applies this scan recursively to the generated package,
including generated subdirectories, alongside notebook, JSON, SQL, KQL, and pipeline predecessor
checks. It also compares target-manifest entries with generated artifact manifest records, verifies
referenced generated paths exist, and blocks non-review targets that reference invalid artifacts.
Invalid artifacts intentionally retained for manual review remain allowed.

Validate this contract with:

```powershell
python -m pytest tests/test_artifact_validation.py tests/test_security.py -v
```

The focused test passes with `10 passed`. The validator performs offline pattern and structural
checks only; pattern scanning is not a substitute for official Fabric schema validation or
deployment validation. The complete suite was validated with `python -m pytest -q` (`306 passed`).
All of these checks are offline-only and non-destructive.

The validator also rejects a non-object JSON root with a deterministic validation error instead of
raising. Parity evidence is hardened separately: negative or boolean row counts, duplicate schema
field names, and malformed nested fields are classified as `not_run`.

Validate both contracts with:

```powershell
python -m pytest tests/test_artifact_validation.py -v
python -m pytest tests/test_parity.py -v
```

The results are `7 passed` and `18 passed`, respectively. These checks are offline-only and do not
replace official Fabric schema validation, workload execution, or runtime/data parity evidence.

### Verify CLI and deployment-readiness failure paths

The local contract fails closed for invalid inputs and incomplete generated packages:

| Failure path | Expected result |
|---|---|
| Missing inventory | CLI exit code `2` |
| Malformed inventory | CLI exit code `5` |
| Tampered deployment manifest | Manifest verification exit code `5` |
| Invalid artifact validation | `deployment-check` blocks |
| Unresolved dependencies | Readiness blocks |
| Unsupported target component | Readiness blocks |

Validate the complete failure-path contract with:

```powershell
python -m pytest tests/test_cli.py tests/test_deployment_readiness.py -v
```

The focused suite passes with `14 passed`. These are offline, deterministic guards before any
future deployment phase; they do not validate official Fabric schemas or APIs, execute workloads,
establish runtime or data parity, or perform cloud operations.

### Validate the canonical inventory contract

The JSON provider validates `project_id`, dataset/object IDs and names, known object kinds,
duplicate source IDs, column structures, dependency arrays, and non-negative `size_bytes` before
model coercion. Explicit `null` `size_bytes` remains valid optional evidence. This validation is
offline and non-destructive; it does not validate cloud schemas, runtime behavior, data parity, or
deployment readiness.

Validate the focused provider and CLI contract with:

```powershell
python -m pytest tests/test_models.py tests/test_cli.py -v
```

The validated result is `15 passed`.

### Validate adapter contract edge cases

Composer normalization extracts task connection names even when the DAG dependency map is empty.
If no task declares a connection, it emits explicit `connections: []`, which is distinct from
missing evidence. Dataflow discovery deduplicates repeated job IDs across regional and paginated
payloads deterministically.

Run the focused offline contract tests with:

```powershell
python -m pytest tests/test_discovery.py tests/test_dataflow_discovery.py -v
```

The validated result is `50 passed`. These fixtures do not validate official GCP API behavior,
live permissions, metadata freshness, runtime or data parity, or an authorized live-GCP sandbox.
Composer remains offline normalization/assessment only; Dataflow discovery is live only when
explicit regions are requested and does not scan all regions.

## Assess a live GCP project

1. Install the optional dependencies and enable the **BigQuery API**, **BigQuery Data Transfer API**,
    and **BigQuery Connection API** for the target project.

    ```powershell
    python -m pip install -e ".[dev,gcp]"
    ```

2. Authenticate with user Application Default Credentials (ADC). Do not use or store service-account JSON.
    Follow Google's [ADC guidance](https://docs.cloud.google.com/docs/authentication/provide-credentials-adc).

    ```powershell
    gcloud auth application-default login
    ```

3. Ask a security administrator to grant least-privilege read access for the required APIs and
    resources. The matrix below is the implemented discovery contract; consult Google's
    [BigQuery access-control reference](https://docs.cloud.google.com/bigquery/docs/access-control)
    when assigning roles.
4. Discover and process the local inventory:

    ```powershell
    bqtofabric discover <project-id> --output artifacts/<project-id>/inventory.json
    # Optional, repeatable regional Dataflow discovery:
    bqtofabric discover <project-id> --dataflow-region europe-west1 --output artifacts/<project-id>/inventory.json
    bqtofabric validate artifacts/<project-id>/inventory.json
    bqtofabric inventory artifacts/<project-id>/inventory.json
    bqtofabric assess artifacts/<project-id>/inventory.json
    bqtofabric map artifacts/<project-id>/inventory.json
    bqtofabric plan artifacts/<project-id>/inventory.json --output artifacts/<project-id>/plan
    bqtofabric generate artifacts/<project-id>/inventory.json --output artifacts/<project-id>/project
    bqtofabric deployment-check artifacts/<project-id>/project/fabric
    ```

## Discovery capability and permissions

Discovery uses ADC with the `https://www.googleapis.com/auth/bigquery.readonly` scope. Required APIs
are BigQuery API, BigQuery Data Transfer API, and BigQuery Connection API. The tool is read-only,
redacts credential-like metadata, and does not print provider response bodies.

| Source family | Extracted today? | Rights extracted? | Minimum discovery permission/role guidance | Assessment status |
|---|---|---|---|---|
| BigQuery core: datasets, tables, views, materialized/external tables, routines, procedures, BQML models | Yes | No Cloud IAM bindings | Dataset-level metadata visibility, such as `roles/bigquery.metadataViewer`, for every dataset in scope | Live metadata extraction; assessed and mapped offline |
| BigQuery jobs | Yes | No | For estate-wide history, use project-level `roles/bigquery.resourceViewer`, which supplies `bigquery.jobs.listAll`; do not grant broad administrative roles for discovery | Live metadata extraction; assessed and mapped offline |
| Scheduled queries (BigQuery Data Transfer transfer configurations) | Yes | No | Grant only the Data Transfer visibility required for the transfer configurations in scope; validate the exact role with the security administrator | Live metadata extraction; assessed and mapped offline |
| BigQuery connections | Yes | Connection IAM bindings are not extracted | Grant `bigquery.connections.get` and `bigquery.connections.list`, for example through a suitable role such as `roles/bigquery.connectionUser` where appropriate | Live metadata extraction; assessed and mapped offline |
| Dataset ACLs (`datasets.get` payload `access` entries) | Yes | Redacted dataset access entries only, with `evidence_scope: dataset_access_entry`; they do not prove effective project, organization, group, or inherited IAM access | Dataset metadata visibility, such as `roles/bigquery.metadataViewer`, for every dataset in scope | Assessment emits `FAIL` `SECURITY_EFFECTIVE_ACCESS_REVIEW`; manual security review required |
| Project/org IAM | No | No | No IAM API calls; live adapter and permission contract not implemented | Not extracted; manual security review required |
| Connection IAM | No | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |
| Distinct row access policies, BigQuery Data Policies, and policy tags | No | No | Live adapter and permission contract not yet implemented; security review required | Canonical/offline assessment type only |
| Dataflow regional jobs | Yes, only for explicitly requested `--dataflow-region` values | No | Security-administrator-validated, read-only Dataflow job visibility for each requested region; use least-privilege viewer guidance rather than broad administrative access | Live identity, state, type, labels, timestamps, and present environment/pipeline metadata; missing compatibility evidence remains a finding |
| Composer | No | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |
| Dataproc | No | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |
| Dataform compilation results | Partial | No | Read-only Dataform compilation-result visibility; validate the least-privilege role with the security administrator | Successful details aggregate models/assertions/incremental evidence; a detail-request failure emits an incomplete fallback workflow and requires manual review |
| Workflows | No | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |
| Pub/Sub | No | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |
| Cloud Storage (GCS) | No | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |
| Looker | No | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |
| Vertex AI | No | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |
| Dataplex | No | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |
| Cloud SQL | No | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |
| Spanner | No | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |

### Exit code 3

Exit code `3` means discovery could not establish the required read-only access. Re-run
`gcloud auth application-default login`, confirm the BigQuery API, BigQuery Data Transfer API, and
BigQuery Connection API are enabled, then have a security administrator verify the relevant
least-privilege visibility in the matrix. Do not add credentials, tokens, or service-account keys to
the inventory or command line.

Composer, Dataproc, Dataform, Pub/Sub, GCS, Looker, Vertex AI, Dataplex, Cloud SQL, and Spanner
have offline normalization and assessment support only; they do not have live adapters. Dataflow
discovery is regional and opt-in; it never scans all regions. Without `--dataflow-region`, the
path remains BigQuery-only. Each requested region must have separately validated read-only
Dataflow visibility; extraction triggers no deployment behavior.

### Discovery provenance

Canonical components carry a `discovered_from` value so review can distinguish acquisition paths:
imported canonical JSON defaults to `inventory`, the live BigQuery provider sets `bigquery_api`, the
Dataflow adapter sets `dataflow_api`, and normalized external GCP payloads set `external_payload`.
Assessment repeats the value for each object
in `evidence_summary` and reports deterministic counts by source in `discovery_coverage`.

`external_payload` means that associated-service inventory was supplied for offline normalization; it
does not mean BQToFabric called that service's API. Provenance is not a freshness assertion and does
not validate when the source metadata was collected.

For live Dataflow jobs, `properties.streaming` reflects the payload `type`. The adapter preserves
`portable` and `connector_compatible` only when those fields are explicitly present; absent
evidence remains visible to assessment and is never inferred.

For each successfully fetched Dataform compilation result, discovery aggregates `models`,
`assertions`, and `incremental` evidence on the canonical repository and workflow records. `models`
is the sorted list of compiled table/view target names; `assertions` and `incremental` are booleans
derived from compiled targets and edges. `models: []`, `assertions: false`, and
`incremental: false` are known evidence, so they do not block assessment.

When a Dataform compilation-result detail request fails, discovery instead emits a deterministic
`dataform_workflow` fallback rather than silently dropping the workflow's lineage. It is marked
`discovered_from: dataform_api`, `discovery_incomplete: true`, and `lineage_status: unavailable`.
Assessment emits `FAIL` `DATAFORM_COMPILATION_DETAILS_UNAVAILABLE`, which blocks reliance on the
affected assessment. The planner marks the fallback with `incomplete_dataform_compilation` and each
downstream object with `depends_on_incomplete_dataform_compilation`. Re-run discovery after Dataform
API or access recovery to obtain the actual compilation graph; the fallback is not evidence of the
graph's completeness. This behavior was validated with `python -m pytest tests/test_discovery.py
tests/test_assessment.py tests/test_dataform_conversion.py -v` (`56 passed`).

### Composer schedule review

Composer remains an offline normalized input; its live adapter is not implemented. Normalization
writes `properties.schedule_interval` as the canonical schedule field and retains
`properties.schedule` for compatibility. Generated pipelines read `schedule_interval` first and
fall back to `schedule`, preserving `@daily`, `@hourly`, and `@weekly` trigger mapping for legacy
inventories.

Raw cron expressions are not automatically mapped. They remain review-required until the source
cron, timezone, start-date, catchup, retries, and equivalent Fabric trigger semantics are reviewed.
This limitation does not imply trigger execution or schedule parity. The behavior was validated by
`python -m pytest tests/test_discovery.py tests/test_artifact_generation.py -v` (`79 passed`).

### Composer adapter-evidence review

For each normalized Composer DAG, `properties.runtime_version` uses the Composer image version when
present, then a sanitized environment-version label, then `unknown`. `properties.connections`
contains only declared task connection names found in `conn_id`, `connection_id`, `gcp_conn_id`, or
`google_cloud_conn_id`. No connection configuration, secret, or credential data is serialized.

An explicit `connections: []` is complete evidence that no task declared a connection, while a
missing `connections` field remains incomplete evidence during assessment. In either case, inspect
connection configuration, secret bindings, and effective runtime access manually before accepting a
migration recommendation.

This behavior was validated with `python -m pytest tests/test_discovery.py tests/test_assessment.py
-v` (`53 passed`). Composer remains offline normalization and assessment input; this contract does
not add a live Composer adapter or establish runtime access parity.

### Dataproc adapter-evidence review

Dataproc job normalization writes canonical `properties.language`: PySpark maps to `python`, Spark
SQL and Hive map to `sql`, and Pig maps to `pig`. Unsupported or ambiguous job types map to
`unknown`; the existing `properties.runtime` job classification remains unchanged.

`properties.runtime_version` is inherited from the referenced cluster's
`config.softwareConfig.imageVersion` when present, otherwise `unknown`. Assessment treats
`unknown` and `not specified` as missing evidence, not as complete readiness evidence. Supply the
runtime version or re-discover from a payload whose referenced cluster contains `imageVersion`
before accepting readiness as complete.

This behavior was validated with `python -m pytest tests/test_discovery.py tests/test_assessment.py
-v` (`54 passed`). This evidence contract does not add a live Dataproc adapter or establish runtime
execution or parity.

### Incomplete external payloads

An `external_payload` component without required offline evidence receives exactly one assessment
finding: `FAIL` `EXTERNAL_PAYLOAD_INCOMPLETE_ADAPTER` in category `adapter`. It states that the
offline evidence must be completed because no live adapter is implemented. Resolve the evidence
gap before relying on its target recommendation or migration wave.

The planner marks the incomplete component and all direct and transitive dependents
`manual_review`. This propagation is a review requirement, not an unresolved dependency:
`unresolved_dependencies` remains for missing or external source IDs and dependency cycles. The
workflow stays offline and does not call external GCP services or add live adapters.

### Manual-review reasons

`manual_review` remains the planner's decision flag. A flagged `PlanItem` also carries a
deterministic `manual_review_reasons` list so reviewers can identify why action is needed. Review
the following codes before approving a migration wave: `external_dependency`,
`incompatible_mapping`, `streaming_downstream_review`, `incomplete_external_adapter`,
`depends_on_incomplete_external_adapter`, `incomplete_dataform_compilation`,
`depends_on_incomplete_dataform_compilation`, `sql_incompatibility`, and
`cycle_or_unresolved_dependency`.

`migration-plan.md` renders the decision flag and codes. The generated
`fabric/target-manifest.json` renders the corresponding `manualReview` and
`manualReviewReasons` fields for target-level review. These are deterministic dry-run planning
metadata and introduce no cloud calls or deployment behavior.

### Migration-plan findings

The generated `migration-plan.md` includes a `Findings` section copied from assessment output. Each
entry lists `severity`, `code`, `category`, `source`, and `message`, making `WARN` and `FAIL`
conditions visible in the human review report. Treat these entries as actionable review evidence:
resolve, document, or explicitly accept each relevant finding before relying on a migration wave.

### Review SQL fidelity

The converter preserves `DIRECT` compatibility for existing supported GoogleSQL cases. It detects
`SAFE_CAST` and `NOT IN`, downgrades affected conversions to `TRANSFORM`, and emits semantic
warnings and manual parity steps. Inspect those warnings and steps in the conversion output, then
design source-versus-target checks for the affected null-handling and membership semantics.

Validate the focused conversion contract with:

```powershell
python -m pytest tests/test_sql_converter.py -v
```

The validated result is `85 passed`. This is an offline conversion check only; it does not execute
source or target SQL, validate official Fabric schemas, or establish runtime/data parity. Do not
approve transformed SQL without separate parity evidence.

The section is not proof that a finding has been remediated, that Fabric deployment is ready, or
that runtime parity has been established. Use `assessment.json`, mapping output, generated artifacts,
and independent parity/security checks for deeper review.

### Schedule-trigger start time

Generated schedule triggers use `@utcNow()` for `startTime` instead of retaining the stale fixed
`2024` date. This keeps the generated trigger start time current for the supported preset schedule
mappings while preserving deterministic, offline artifact generation.

This behavior was validated with `python -m pytest tests/test_artifact_generation.py -v` (`44
passed`). Generated pipeline definitions remain review artifacts: validate them against the official
Fabric/ADF schema and complete deployment validation before deployment.

### Pipeline activity resilience defaults

Generated operational activities use deterministic policy defaults: `retry: 3`,
`retryIntervalInSeconds: 30`, `secureInput: true`, and `secureOutput: true`. The failure handler
retains its specialized secure policy. Validate the generated definition and its retry behavior
against the official Fabric/ADF schema and runtime before treating it as deployable. This behavior
was validated with `python -m pytest tests/test_artifact_generation.py -v` (`44 passed`).

### Assessment summary

The generated `migration-plan.md` starts its review detail with an `Assessment summary`. The
Gate/Value table reports total findings, `FAIL` findings, `WARN` findings, and components requiring
manual review. `Readiness by processing stage` reports each represented stage, its component count,
deterministic readiness percentage, and manual-review count. `Manual-review reason counts` reports
deterministic frequencies for the reasons attached to planned review items. The Gate/Value table
also reports `Parity checks` and `Parity not run` totals. `Parity not run` means runtime evidence
is absent; it does not mean that parity succeeded. The detailed `Parity evidence` table is
unchanged.

Use these tables to prioritize review and compare the evidence in the detailed sections. They are
deterministic review summaries only: they do not prove deployment readiness, runtime parity,
security remediation, or finding remediation.

### Assessment report summary artifact

The validated assessment-report milestone adds `assessment-summary.json` to the generated report
set. Use it for deterministic dashboard and HTML report inputs; use `assessment.json` for detailed
findings, evidence, and assessment inspection. The summary contains project identity, score,
evidence coverage, architecture, component count, finding counts, target and compatibility
summaries, parity summary, manual-review count and reasons, unresolved dependencies, blockers, and
status.

Validate the report-generation contract with:

```powershell
python -m pytest tests/test_cli.py tests/test_deployment_readiness.py -v
```

The focused suite passes with `15 passed`. This artifact is generated from local inputs and is
offline-only. It does not validate official Fabric schemas, execute workloads, establish runtime
or data parity, or authorize deployment.

### Stage-readiness summary

The generated `fabric/target-manifest.json` has a top-level `stageReadiness` object for each
`processingStage` represented by an entry; stages without entries are omitted. Each stage summary
contains `total`, counts for `direct`, `transform`, `redesign`, and `unsupported`, `manualReview`,
and `readiness`. `readiness` is the deterministic rounded weighted average of component
compatibility: `direct=100`, `transform=80`, `redesign=50`, and `unsupported=0`.

Use this rollup to prioritize migration review. It is not evidence of executed workloads, parity,
security remediation, or deployment readiness.

### Dataset access evidence

Dataset GET `access` entries are inventory evidence, not an effective-access calculation. Each
redacted canonical `security_policy` record has `evidence_scope: dataset_access_entry`. Assessment
emits `FAIL` `SECURITY_EFFECTIVE_ACCESS_REVIEW`, requiring manual review because the evidence does
not establish project, organization, group, or inherited IAM access. The live workflow makes no IAM
API calls and does not extract project/org IAM, connection IAM, BigQuery Data Policies, policy tags,
or distinct row access policies.

## Review and migration preparation

1. Run `bqtofabric assess` and resolve FAIL findings.
2. Review target and type mappings, especially ARRAY, STRUCT, GEOGRAPHY, BIGNUMERIC, policies,
    UDFs, procedures, and external dependencies.
3. Generate the migration plan, review its `Assessment summary` and `Findings` sections, verify dependency waves and
    `stageReadiness`, and resolve or explicitly accept every `manual_review_reasons` code.
4. Generate dry-run Fabric artifacts and review SQL, notebooks, pipelines, identities, and names.
    Generated Warehouse SQL never emits `DROP TABLE` or `DROP VIEW`: table and scheduled-query
    targets are created only when absent and preserve existing objects; views use a guarded dynamic
    create-only-when-absent statement and preserve existing definitions. This behavior was validated
    by `python -m pytest tests/test_artifact_generation.py -v` with `40 passed`. An Eventhouse
    schema with no source columns is marked invalid: its artifact contains review comments and a
    `REDESIGN` warning only, with no KQL create, ingestion-mapping, or materialized-view statements;
    the artifact manifest records `valid: false`. Normal Eventhouse schema generation is unchanged.
    Generated Eventstream output is likewise a non-deployable review scaffold: it sets
    `deployable: false` and artifact `valid: false`, and its source node uses
    `connectionReference: review_required` rather than an invented `connectionId`. It includes
    authoring TODOs and the artifact manifest propagates `valid: false`. This behavior was
    validated by `python -m pytest tests/test_artifact_generation.py -v` with `40 passed`.
    For a table, view, or materialized view with no discovered columns, semantic-model generation
    instead returns an invalid review-only scaffold: `valid: false`, `deployable: false`, and
    `validationStatus: pending_source_schema`, with no tables, measures, relationships, or
    connection placeholders. It emits a `REDESIGN` warning requiring source-schema discovery and
    regeneration; normal schema-backed output is unchanged. This behavior was validated by
    `python -m pytest tests/test_artifact_generation.py -v` with `42 passed`.
    These structural dry-run guards are not official Fabric validation or deployment; author the
    Eventstream against the official Fabric API/schema and supply approved connections before
    deployment. Regenerated semantic models still require official Fabric semantic-model
    schema/API validation. All generated output requires validation and an explicit deployment
    workflow before it can be treated as deployable. Artifact generation processes each category
    in sorted source-ID order, serializes JSON artifacts, manifests, and notebooks with sorted
    keys, and aggregates warnings in source-ID order. Equivalent inventories therefore produce
    identical artifact paths and bytes even when input component order differs. This behavior was
    validated by `python -m pytest tests/test_artifact_generation.py -v` with `42 passed`.
    Distinct source IDs that produce the same generated filename remain an open collision-handling
    case.
    Numeric `Count of <column>` measures use DAX `COUNT`, so the generated measure counts populated
    values as its name implies. This behavior was validated with
    `python -m pytest tests/test_artifact_generation.py -v` (`44 passed`). Generated semantic
    models remain dry-run review artifacts and still require official Fabric semantic-model
    schema/API validation before deployment.
5. Design parity checks for row counts, schemas, nulls, aggregates, samples, and security behavior.
6. Use the native Fabric BigQuery connector for Dataflow Gen2, Pipeline Copy/Lookup, or Copy Job.
7. Pilot one representative dataset before scaling by migration wave.
8. Add live deployment only after explicit approval, credentials, rollback, and audit controls.
