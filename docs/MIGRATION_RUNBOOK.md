# Migration runbook

## Test the assessment locally

The committed fixture provides a deterministic offline smoke test for the complete assessment
package. It does not call GCP or Fabric:

```powershell
python -m pip install -e ".[dev]"
python -m pytest

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

Review `migration-plan.md` and its `Findings` section. Then inspect `assessment.json` for
`findings`, `evidence_summary`, `discovery_coverage`, and `parity_summary`; inspect
`fabric/target-manifest.json` for `stageReadiness`, `manualReview`, `manualReviewReasons`, and
`processingStage`; and inspect `fabric/artifact-validation.json` and
`fabric/deployment-manifest.json`.

`FAIL` findings block reliance on the affected recommendation until the evidence or compatibility
issue is resolved or explicitly accepted. `WARN` findings require documented design or manual
review. Discovery exit code `3` means the required read-only ADC, API, or metadata visibility could
not be established; it does not indicate a deployment failure or success.

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
| Dataflow | No | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |
| Composer | No | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |
| Dataproc | No | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |
| Dataform | No | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |
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

Dataflow, Composer, Dataproc, Dataform, Pub/Sub, GCS, Looker, Vertex AI, Dataplex, Cloud SQL, and
Spanner have offline normalization and assessment support only; they do not have live adapters.

### Discovery provenance

Canonical components carry a `discovered_from` value so review can distinguish acquisition paths:
imported canonical JSON defaults to `inventory`, the live BigQuery provider sets `bigquery_api`, and
normalized external GCP payloads set `external_payload`. Assessment repeats the value for each object
in `evidence_summary` and reports deterministic counts by source in `discovery_coverage`.

`external_payload` means that associated-service inventory was supplied for offline normalization; it
does not mean BQToFabric called that service's API. Provenance is not a freshness assertion and does
not validate when the source metadata was collected.

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
`depends_on_incomplete_external_adapter`, `sql_incompatibility`, and
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

The section is not proof that a finding has been remediated, that Fabric deployment is ready, or
that runtime parity has been established. Use `assessment.json`, mapping output, generated artifacts,
and independent parity/security checks for deeper review.

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
3. Generate the migration plan, review its `Findings` section, verify dependency waves and
    `stageReadiness`, and resolve or explicitly accept every `manual_review_reasons` code.
4. Generate dry-run Fabric artifacts and review SQL, notebooks, pipelines, identities, and names.
5. Design parity checks for row counts, schemas, nulls, aggregates, samples, and security behavior.
6. Use the native Fabric BigQuery connector for Dataflow Gen2, Pipeline Copy/Lookup, or Copy Job.
7. Pilot one representative dataset before scaling by migration wave.
8. Add live deployment only after explicit approval, credentials, rollback, and audit controls.
