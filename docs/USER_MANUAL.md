# BQToFabric User Manual

BQToFabric is an offline-first assessment and migration-planning tool for BigQuery and related GCP data workloads moving to Microsoft Fabric. It reads canonical inventory JSON, assesses compatibility, builds dependency-ordered plans, and generates deterministic dry-run artifacts.

It does not deploy to Fabric. Treat generated files as review material until they pass the appropriate official Fabric validation and a separate approved deployment process.

## 1. Install

Requirements:

- Python 3.12 or later
- PowerShell, Bash, or another shell
- Optional GCP dependencies for read-only discovery

Install the development package from the repository root:

```powershell
python -m pip install -e ".[dev]"
```

For BigQuery discovery, install the optional GCP dependencies:

```powershell
python -m pip install -e ".[dev,gcp]"
```

Check the installation:

```powershell
bqtofabric --help
python -m pytest
python -m pyright
python -m ruff check src tests
```

For the authoritative baseline counts — suite size, coverage, supported kinds, target roles, CLI
commands, and the reference-fixture assessment output — see
[ROADMAP.md](ROADMAP.md#authoritative-baseline--v010).

## 2. Recommended Offline Workflow

Start with a canonical inventory. The repository includes sanitized fixtures under `tests/fixtures`.
For the field-by-field contract and a minimal JSON example, see [INVENTORY_SCHEMA.md](INVENTORY_SCHEMA.md).

```powershell
$inventory = "tests/fixtures/gcp_ecosystem_project.json"
$output = "artifacts/my-project"

bqtofabric validate $inventory
bqtofabric inventory $inventory
bqtofabric assess $inventory
bqtofabric map $inventory
bqtofabric plan $inventory --output "$output/plan"
bqtofabric generate $inventory --output "$output/project"
bqtofabric manifest-verify "$output/project/fabric/deployment-manifest.json"
bqtofabric deployment-check "$output/project/fabric"
```

The commands are read-only with respect to cloud services. `generate` writes local review artifacts only.

Run the same workflow from PowerShell with the repository smoke-test script:

```powershell
.\scripts\smoke_test.ps1
.\scripts\smoke_test.ps1 tests/fixtures/mixed_project.json artifacts/mixed-smoke
```

The script expects the `bqtofabric` command to be installed with `python -m pip install -e ".[dev]"`.

### Command sequence

1. `validate` checks the canonical inventory contract before model coercion, including identifiers,
   known object kinds, duplicate source IDs, column/dependency structures, and `size_bytes` rules.
2. `inventory` prints a compact object and component summary.
3. `assess` produces compatibility, evidence, parity, findings, and target summaries.
4. `map` prints the target decision for each source object.
5. `plan` creates dependency-ordered migration waves and manual-review reasons.
6. `generate` writes the migration reports and, when requested, Fabric dry-run artifacts.
7. `manifest-verify` verifies the deployment-manifest integrity hash.
8. `deployment-check` checks whether the local package is ready for review. It never applies changes.

### Command reference

| Command | Input | Output | Typical use |
|---|---|---|---|
| `inventory` | Inventory JSON | Summary JSON | Count objects and component kinds |
| `validate` | Inventory JSON | PASS/FAIL text | Check inventory structure |
| `assess` | Inventory JSON | Assessment JSON | Review compatibility and evidence |
| `map` | Inventory JSON | Mapping JSON | Inspect Fabric target decisions |
| `plan` | Inventory JSON + `--output` | Plan package | Build dependency waves |
| `generate` | Inventory JSON + `--output` | Reports and dry-run artifacts | Prepare review materials |
| `discover` | GCP project + `--output` | Canonical inventory JSON | Read-only metadata discovery |
| `manifest-verify` | Deployment manifest | PASS/FAIL text | Check manifest integrity |
| `deployment-check` | Artifact directory | Readiness JSON | Run offline pre-deployment checks |

All commands are deterministic for the same inputs and configuration. No command performs a
Fabric apply operation.

The JSON provider accepts explicit `null` for optional `size_bytes`; supplied sizes must be
non-negative integers. Invalid inventory documents fail locally before they are coerced into the
canonical model. These checks do not validate cloud schemas, runtime behavior, data parity, or
deployment readiness.

## 3. Inspect the Outputs

A generated package commonly contains:

| File | Purpose |
|---|---|
| `assessment.json` | Scores, findings, evidence coverage, SQL assessments, and parity status |
| `assessment-summary.json` | Deterministic dashboard/HTML summary of project, score, evidence, architecture, findings, targets, compatibility, parity, review, blockers, and status; it does not replace `assessment.json` |
| `component-mapping.csv` | Source kinds, Fabric targets, compatibility, rationale, and actions |
| `connection-transcode.json` | Secret-free, deterministic connection candidates and review findings |
| `migration-plan.md` | Human-readable waves, findings, assessment summary, and manual-review reasons |
| `migration-plan.json` | Machine-readable migration plan |
| `lineage.mmd` | Dependency graph for review |
| `fabric/target-manifest.json` | Target entries, waves, stages, dependencies, and review flags |
| `fabric/deployment-manifest.json` | Immutable dry-run payload with integrity hash |
| `fabric/artifact-validation.json` | Recursive offline validation of generated files |
| `fabric/` generated artifacts | Notebooks, Warehouse SQL, pipelines, Eventstream/Eventhouse scaffolds, and semantic models |

Prioritize these fields during review:

- `findings`: `WARN` and `FAIL` conditions requiring action.
- `evidence_summary`: required, present, missing, and coverage fields by component.
- `manualReviewReasons`: deterministic reasons a plan item cannot be treated as ready.
- `processingStage` and `stageReadiness`: stage-level migration prioritization.
- `parity_summary`: `passed`, `failed`, `not_run`, or `not_applicable` evidence status.
- `valid`: whether an individual generated artifact passed local structural checks.

Connection candidates are review records only. `connection-transcode.json` never creates a Fabric
connection, resolves an identity binding, or claims access. Embedded credential material and
unsupported backends produce `manual_review` with the finding type retained but the value omitted.

The optional repair contract applies named deterministic rules to a defensive copy and validates
the result. Current rules repair misplaced pipeline `triggers` and remove exact duplicate schema
fields. Conflicting duplicate definitions remain manual review; no persisted source file is changed
automatically.

### Assessment report summary

`write_reports` emits `assessment-summary.json` for dashboard and HTML report consumers. Its
deterministic fields are `projectId`, `score`, `evidenceCoverage`, `architecture`,
`componentCount`, `findingCounts`, `targetSummary`, `compatibilitySummary`, `discoveryCoverage`, `paritySummary`,
`manualReviewCount`, `manualReviewReasons`, `unresolvedDependencies`, `blockers`, and `status`.
Use `assessment.json` for the detailed assessment; the summary is a presentation-oriented sibling,
not a replacement.

The report milestone is validated by `python -m pytest tests/test_cli.py
tests/test_deployment_readiness.py`, which passes in CI. This is offline-only report generation from
local assessment inputs. It does not validate official Fabric schemas, execute workloads, establish
runtime or data parity, or authorize deployment.

A `ready_for_review` result from `deployment-check` is not a deployment approval. It means the local dry-run package passed the available offline gates.

The package validator also checks cross-artifact consistency: every target-manifest entry with a
known generated artifact kind must match a generated manifest record, its generated path must
exist, and a non-review target must not reference an artifact with `valid: false`. Invalid
review-only scaffolds are intentionally permitted so they can be inspected and completed later.
This is a local offline consistency check, not official Fabric schema or deployment validation.

## 4. Live Read-Only Discovery

Authenticate with Google Application Default Credentials (ADC):

```powershell
python -m pip install -e ".[dev,gcp]"
gcloud auth application-default login
```

Discover the BigQuery metadata surface:

```powershell
$project = "my-gcp-project"
bqtofabric discover $project --output artifacts/$project/inventory.json
```

Opt into regional Dataflow job discovery:

```powershell
bqtofabric discover $project `
  --dataflow-region europe-west1 `
  --output artifacts/$project/inventory.json
```

> [!WARNING]
> The Dataflow, Dataproc, Dataform, and Composer adapters below are **live, credentialed, read-only
> Google API calls**, not offline payload normalization. They are opt-in: nothing contacts those
> services unless you pass the corresponding flag. All four request the
> `https://www.googleapis.com/auth/cloud-platform.read-only` scope, which is **broader** than the
> BigQuery path's `https://www.googleapis.com/auth/bigquery.readonly`. Have a security
> administrator review and approve that scope before first use.

Opt into the additional read-only live adapters:

```powershell
bqtofabric discover $project `
  --dataproc-region europe-west1 `
  --dataform `
  --dataform-location us-central1 `
  --composer-region us-central1 `
  --output artifacts/$project/inventory.json
```

Discovery is read-only and never writes credentials into the inventory. Principal identities in
access evidence are pseudonymized as stable, non-reversible `principal:<12 hex>` values. Paging is
bounded and rejects repeated page tokens. A discovery failure returns exit code `3`; it is not a
deployment result.

Current boundaries:

- BigQuery discovery is live and read-only, and uses the narrower `bigquery.readonly` scope.
- Dataflow and Dataproc are opt-in by explicit region and never scan all regions. Dataform and
  Composer are opt-in by explicit flag.
- **No adapter has been validated against an authorized GCP sandbox.** The adapter code exists and
  is covered by offline fixture tests; the live verification does not exist. Treat a first live run
  as an unverified operation and review its output before relying on it.
- Workflows, Pub/Sub, GCS, Looker, Vertex AI, Dataplex, Cloud SQL, and Spanner have **no** live
  adapter. They remain offline payload normalization and assessment inputs only.
- IAM effectiveness, secret bindings, policy-tag parity, and runtime execution are not inferred.

## 5. Understanding Compatibility

BQToFabric uses four compatibility levels:

| Level | Meaning |
|---|---|
| `direct` | Evidence supports a close mapping with no known redesign requirement |
| `transform` | A translation is plausible but must be tested and reviewed |
| `redesign` | Target behavior or operating model needs manual redesign |
| `unsupported` | No safe automatic translation is claimed |

Treat `WARN` and `FAIL` findings as review work. In particular, do not promote an object because its mapping is `transform` if required evidence, credentials, schema, or runtime parity is missing.

For the complete list of the 16 assessment finding codes with their severity, trigger, and the
reviewer action each one expects, see the
[finding-code reference](MAPPING_REFERENCE.md#assessment-finding-codes).

### SQL fidelity review

Assessment and generation share one SQL conversion stack: `sql_assessment` delegates to the
`converter/` package (`SqlConverter`). SQL compatibility is the worst of the converter verdict, the
detected semantic risks, and the mapping decision, and it **never defaults to `direct`**.

Semantic-risk patterns such as `SAFE_CAST` and `NOT IN` are marked `transform`, with semantic
warnings and manual parity steps recorded in the conversion result. A non-SQL routine body, such as
a JavaScript UDF, is `redesign` and emits **no** converted SQL, so there is nothing to mistake for
a translation.

Review those warnings and execute source-versus-target parity checks before accepting generated
SQL. The converter contract is validated by `python -m pytest tests/test_sql_converter.py`, which
passes in CI. That validation is offline: it does not execute source or target SQL, validate
official Fabric schemas, or establish runtime/data parity.

### Generated artifact validity

An artifact's `valid` flag is derived from a real check of its content rather than asserted by the
generator. `NotebookValidator` rejects undefined DataFrame references. `TsqlValidator` strips
comments and re-parses `CREATE TABLE`, rejects `#` comments, and enforces the `CREATE SCHEMA` batch
rule. `PipelineValidator` requires name-keyed parameters and variables, rejects `triggers` as a
pipeline property, and rejects secret-bearing expressions.

A generated Warehouse view body is converted GoogleSQL → T-SQL. If conversion fails or produces
constructs Fabric Warehouse does not support, the body is omitted, the artifact is marked invalid,
and the candidate conversion appears as `--` comments for review.

Generated pipelines carry named connection references bound to managed identity rather than
connection strings. `valid: true` still means "passed the local structural checks", not
"deployable".

### Parity results

Parity status is recomputed from evidence on every run; a `status` you supply is never trusted.
Each check is derived from its own `source`/`target` payload, a declared `passed` with no payload
resolves to `not_run`, and a declared status that contradicts the evidence is preserved as
`declaredStatus`. The check set is `schema`, `row_count`, `checksum`, `aggregate`,
`null_distribution`, `sample`, and `sql_result`; the former `type` check was removed because no
comparator backed it.

No source or Fabric query is executed, so `passed` means the supplied evidence agrees — not that
the data matches at runtime.

## 6. Security Rules

Never place these in inventories, source snippets, generated artifacts, logs, or issue attachments:

- Service-account JSON or key-file paths
- API keys, OAuth tokens, bearer tokens, or private keys
- Connection-string passwords
- Tenant IDs, workspace secrets, or other deployment credentials

Conversion records and generated package validation use credential detection and redaction. The package validator reports only a finding type, never the matched secret value. A detected credential blocks local artifact validation.

## 7. Troubleshooting

### `Invalid inventory`

Confirm that the file is valid JSON and contains a `project_id`, datasets, or canonical `components`. Run:

```powershell
bqtofabric validate path/to/inventory.json
```

### Exit code `3` during discovery

ADC, API access, permissions, or metadata visibility could not be established. Check the active account and requested project, then retry without broadening permissions unnecessarily.

### `deployment-check` returns `blocked`

Open the returned `errors` list and inspect:

- `fabric/artifact-validation.json`
- `fabric/deployment-manifest.json`
- `migration-plan.md`
- `assessment.json`

`deployment-check` blocks on any of the following:

| Blocking condition | Where to look |
|---|---|
| Invalid or incomplete artifact validation | `fabric/artifact-validation.json` |
| Manifest tampering or integrity failure | `fabric/deployment-manifest.json` |
| `FAIL` findings or recorded blockers | `assessment.json` → `findings`, `blockers` |
| Failed parity | `assessment.json` → `parity_summary` |
| A component mapped `redesign` | `component-mapping.csv` |
| A component mapped `unsupported` | `component-mapping.csv` |
| Pending manual review | `migration-plan.md` → `manual_review_reasons` |
| Unresolved dependencies | `migration-plan.json` → `unresolved_dependencies` |
| A detected credential | `fabric/artifact-validation.json` (type only, never the value) |

Cross-artifact consistency errors identify a missing generated manifest match, a missing generated
path, or an invalid artifact referenced by a non-review target. A target explicitly marked for
manual review may continue to reference an invalid scaffold.

### An artifact has `valid: false`

Treat it as review-only. Common causes include missing source schema, unsupported KQL/T-SQL, incomplete Dataform lineage, unavailable connections, or an Eventstream scaffold that still needs official Fabric authoring.

### A parity result is `not_run`

Runtime evidence was not supplied. `not_run` does not mean the source and target match.

### Contract-hardening checks

The offline artifact validator rejects a non-object JSON root with a deterministic validation error
instead of raising. Offline parity comparison treats negative or boolean row counts, duplicate
schema field names, and malformed nested fields as `not_run`, so invalid evidence cannot be
reported as a successful comparison.

Validate these contracts with:

```powershell
python -m pytest tests/test_artifact_validation.py -v
python -m pytest tests/test_parity.py -v
```

The validated contracts are offline structural and evidence checks only; they do not validate
official Fabric schemas, execute workloads, or establish runtime/data parity. Artifact validation
now runs after every artifact is written, so `parity-evidence.json` and `deployment-manifest.json`
are also covered by the credential scan and the structural checks.

## 8. Development Validation

Before contributing changes, run:

```powershell
python -m ruff check src tests
python -m pyright
python -m pytest -q
```

The project requires deterministic output, focused regression tests, credential-safe persistence, and documentation updates describing expected, implemented, validated, and open behavior.

## 9. What This Tool Does Not Do

BQToFabric does not currently claim to:

- Deploy or mutate Fabric resources.
- Prove SQL, Spark, notebook, pipeline, KQL, or semantic-model runtime equivalence.
- Prove effective IAM or security-policy equivalence.
- Replace official Fabric schema validation or deployment rehearsals.
- Establish measured performance parity from inventory metadata alone.

Use the generated package to structure migration review and prepare an approved implementation plan.
