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
python -m pytest -q
python -m pyright
python -m ruff check src tests
```

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
| `component-mapping.csv` | Source kinds, Fabric targets, compatibility, rationale, and actions |
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

Opt into the currently supported offline-normalization adapter paths when payload access is available through the configured client:

```powershell
bqtofabric discover $project `
  --dataproc-region europe-west1 `
  --dataform `
  --dataform-location us-central1 `
  --composer-region us-central1 `
  --output artifacts/$project/inventory.json
```

Discovery is read-only and never writes credentials into the inventory. A discovery failure returns exit code `3`; it is not a deployment result.

Current boundaries:

- BigQuery discovery is live and read-only.
- Dataflow is opt-in by explicit region.
- Dataproc, Dataform, and Composer normalization preserve evidence and review blockers, but broader live-adapter coverage and authorized sandbox validation remain open.
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

### SQL fidelity review

SQL conversion preserves direct compatibility for existing supported GoogleSQL cases. It detects
`SAFE_CAST` and `NOT IN` as semantic-risk patterns, marks the conversion `transform`, and records
semantic warnings and manual parity steps in the conversion result. Review those warnings and
execute source-versus-target parity checks before accepting the generated SQL.

The focused converter contract was validated with:

```powershell
python -m pytest tests/test_sql_converter.py -v
```

The result was `85 passed`. This validation is offline: it does not execute source or target SQL,
validate official Fabric schemas, or establish runtime/data parity.

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

Typical blockers are invalid or incomplete artifacts, unresolved dependencies, unsupported components, credential findings, or manifest tampering.

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

The validated results are `7 passed` and `18 passed`, respectively. These are offline structural
and evidence checks only; they do not validate official Fabric schemas, execute workloads, or
establish runtime/data parity.

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
