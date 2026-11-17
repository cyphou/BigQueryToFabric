# Migration runbook

## Offline LookML-derived metadata normalizer

`normalize_looker_lookml_export` accepts a caller-prepared JSON object using the explicit
`bqtofabric.looker-lookml-export/1.0` contract. The root contains exactly `schema_version`
(`"1.0"`), `project_id`, `explores` and `dashboards`. Both collections are arrays. This is
already-parsed metadata; the normalizer and CLI do not parse raw LookML or call cloud APIs.

Import the versioned export into a canonical inventory with:

```text
bqtofabric import-looker-lookml INVENTORY --payload VERSIONED_EXPORT --output NEW_INVENTORY
```

The payload must be accepted `bqtofabric.looker-lookml-export/1.0` offline JSON, and its
`project_id` must match the canonical inventory. The command deterministically appends one Looker
asset with `external_payload` provenance. It never overwrites the output or mutates either input;
use a new output path.

Each Explore requires `source_id` and `name`; it may include `sql_table_name`, `dimensions` and
`measures`. Each field requires `source_id`, `name` and `type`; dimensions use `string`, `number`,
`yesno` or `date`, while measures use `count`, `sum`, `average`, `min`, `max` or
`count_distinct`. Fields use direct `${TABLE}.column` expressions; a `count` measure may omit
`sql`. Dashboard records require `source_id`, `title` and `elements`. Elements require
`source_id`, `title`, `explore_source_id`, `field_source_ids` and a visual `type` of `table`,
`bar`, `column`, `line` or `card`.

All four record kinds require caller-supplied, stable, project-scoped IDs in this form:
`<project_id>.looker_lookml.<kind>.<stable-id>`, where `<kind>` is `explore`, `field`,
`dashboard` or `element`. IDs are not derived from names, titles or order. Dashboard explore
and field references resolve by exact source ID only; matching names do not resolve references.
Malformed or unsupported records are omitted and diagnosed rather than inferred.

**Expected:** Unknown semantic properties fail closed without losing unrelated safe metadata.

**Implemented:** The v1 contract is unchanged. Unknown semantic properties on an explore, field,
dashboard or element emit value-free `unsupported_input_property` diagnostics; neither the unknown
key nor its value is copied. A field with unknown properties is omitted from candidate metadata,
and affected elements are marked unsupported, while unrelated safe views and elements remain.
Existing `external_payload` provenance and security/model-context markers are preserved. This
normalization does not generate visuals.

For example, invoke the normalizer from Python with the export loaded from a JSON file:

```python
import json
from pathlib import Path

from bqtofabric.looker_lookml_export import normalize_looker_lookml_export

payload = json.loads(Path("lookml-export.json").read_text(encoding="utf-8"))
asset = normalize_looker_lookml_export(payload)
```

The returned `LOOKER_ASSET` has `external_payload` provenance. Its
`looker_lookml_ingestion_report` contains value-free diagnostics with fixed paths and codes;
validated IDs, provenance and resolved dependency edges are recorded separately for traceability.
Omitted metadata is not evidence that the corresponding source semantics are absent. Joins,
filters, access controls and security remain unverified, as do runtime, refresh and source/target
parity. Any downstream generation is review-only, not a deployment or correctness claim.

Saved Looker API responses use the distinct `bqtofabric import-looker-api` command and its existing
API-response envelope; this does not change that import contract.

**Validated:** 223 passed, 0 skipped across `test_looker_lookml_export.py`,
`test_looker_api_export.py`, `test_looker_powerbi.py`, `test_cli_import_looker.py` and
`test_cli_looker_powerbi.py`; Ruff passed; Pyright reported 0 diagnostics; agent validation passed
(13 agents, 5 skills); `git diff --check` passed.

**Open:** The broader join, filter and access-control work remains open; security and source/target
parity have not been proved. Runtime and refresh validation, as well as the overall Looker exit
gate, remain open.

## Offline Looker API to Power BI review project

This workflow consumes **saved API 4.0 responses** from `lookml_model_explore` and `dashboard`,
wrapped in one JSON object. These are computed Explore fields and dashboard queries, not raw
LookML files or a live discovery call. The envelope must contain exactly `explores` and
`dashboards`, both arrays. Missing fields are not evidence that joins, filters or security are
absent. Never put credentials or sensitive values in the input files.

**Expected:** A bounded review project from saved responses, without cloud calls.

**Implemented:** The exact visual mappings and field limits below use the external
TableauToPowerBI 44.0.0 PBIP/TMDL writers and PBIR projection finalizer. Missing, invalid or
nonempty `sql_always_where`, `access_grants` or `required_access_grants`, and unknown nonempty
Explore properties, are recorded as unresolved context and block visual conversion. Recognized
descriptive Explore metadata is ignored.

**Validated:** 223 passed, 0 skipped across `test_looker_lookml_export.py`,
`test_looker_api_export.py`, `test_looker_powerbi.py`, `test_cli_import_looker.py` and
`test_cli_looker_powerbi.py`; Ruff passed; Pyright reported 0 diagnostics; agent validation passed
(13 agents, 5 skills); `git diff --check` passed.
An offline synthetic envelope produced three visuals with checked role/reference bindings and
byte-identical repeat output. TableauToPowerBI's static structure/openability checks passed
including all three; `powerbi-report-author` 0.5.0 `validate --no-schema` reported 0 errors and
0 warnings with Node network access blocked. An earlier full-suite run reported 767 passed and
1 skipped; `validate_agents` passed. The [public offline examples](../examples/looker/README.md)
document separate FAA and assisted LookML-derived runs, their measured results and provenance.

**Open:** Remote JSON Schema validation was explicitly skipped. No Desktop opening, runtime or
refresh tests, deployed-security checks, real-data or visual parity checks, deployment or cloud
calls were performed.

The three security fields in the example are conservative envelope extensions, not necessarily
returned by the Explore API. Supply the empty string for `sql_always_where` and empty arrays for
the grants only when independent evidence supports them. Missing, null, invalid or nonempty
values do not establish absence of security. Do not infer empty evidence for real responses.

Create `inventory.json` with this synthetic canonical inventory:

```json
{
  "project_id": "demo-project",
  "schema_version": "1.1",
  "datasets": [],
  "components": [],
  "metadata": {}
}
```

Create `looker.json` with this synthetic envelope. The empty lists and nulls are explicit
evidence for this example, not defaults to invent when a real response omits fields:

```json
{
  "explores": [
    {
      "model_name": "commerce",
      "name": "orders",
      "view_name": "orders",
      "sql_table_name": "demo_project.sales.orders",
      "joins": [],
      "always_join": [],
      "access_filters": [],
      "access_filter_fields": [],
      "sql_always_where": "",
      "access_grants": [],
      "required_access_grants": [],
      "always_filter": [],
      "conditionally_filter": [],
      "fields": {
        "dimensions": [
          {"name": "orders.region", "view": "orders", "type": "string",
           "sql": "${TABLE}.region", "sql_case": null, "dimension_group": null},
          {"name": "orders.amount", "view": "orders", "type": "number",
           "sql": "${TABLE}.amount", "sql_case": null, "dimension_group": null}
        ],
        "measures": [
          {"name": "orders.sales", "view": "orders", "type": "sum",
           "sql": "${TABLE}.amount", "sql_case": null, "dimension_group": null,
           "filters": []}
        ],
        "filters": [],
        "parameters": []
      }
    }
  ],
  "dashboards": [
    {
      "title": "Revenue by Region",
      "dashboard_filters": [],
      "dashboard_elements": [
        {
          "title": "Sales by Region",
          "query": {
            "model": "commerce",
            "view": "orders",
            "fields": ["orders.region", "orders.sales"],
            "filters": {},
            "filter_expression": null,
            "filter_config": null,
            "pivots": [],
            "fill_fields": [],
            "dynamic_fields": null,
            "has_table_calculations": false,
            "sorts": [],
            "total": false,
            "row_total": null,
            "subtotals": [],
            "query_timezone": null,
            "column_limit": null,
            "limit": "-1",
            "vis_config": {"type": "looker_bar"}
          }
        }
      ]
    }
  ]
}
```

To exercise the three added mappings in one synthetic dashboard, replace the example's sole
element with three copies and set each title, `query.fields` and entire `query.vis_config` as
follows. Leave the other query evidence unchanged; do not invent empty evidence for real inputs.

| Title | `query.fields` | `query.vis_config` |
|---|---|---|
| `Trend` | `["orders.region", "orders.sales"]` | `{"type": "looker_line"}` |
| `Columns` | `["orders.region", "orders.sales"]` | `{"type": "looker_column"}` |
| `KPI` | `["orders.sales"]` | `{"type": "single_value"}` |

Install BQToFabric as in the local setup below. For generation, obtain a **trusted, compatible**
[TableauToPowerBI](https://github.com/cyphou/TableauToPowerBI) 44.0.0 source checkout separately,
with its compatible Python dependencies. It is not bundled. The adapter uses internal
`powerbi_import` and `tableau_export` interfaces; missing or incompatible imports/APIs produce
explicit errors, not an automatic fallback. For example, in PowerShell, point `PYTHONPATH` to
the checkout root containing those two package directories:

```powershell
$tableauCheckout = "C:\path\to\trusted\TableauToPowerBI"
$env:PYTHONPATH = "$tableauCheckout;$env:PYTHONPATH"

bqtofabric import-looker-api inventory.json --payload looker.json --output imported.json
bqtofabric generate-looker-powerbi imported.json --asset demo-project.looker.api_export --output review-project
```

On Bash, use `export PYTHONPATH="/path/to/trusted/TableauToPowerBI${PYTHONPATH:+:$PYTHONPATH}"`
instead. For another project, replace `demo-project` in the selector with the inventory
`project_id`: `PROJECT_ID.looker.api_export`. The generator also accepts an unambiguous exact
asset name and `--project-name` (default `LookerMigration`).

Import preserves the existing inventory and appends a component with `external_payload`
provenance; it rejects a duplicate source ID. It creates a **new** output file and never
overwrites inputs or an existing file. Generation requires a **new or empty** output directory
and does not overwrite existing files. Use fresh paths for another run.

Inspect `imported.json` component labels `looker_ingestion_report` and
`looker_source_identifiers`: these are JSON strings with fixed-path/code diagnostics and
validated identifiers respectively. Inspect `review-project/looker-powerbi-review.json` for
`ingestion_diagnostics`, `issues`, `converted` and review status, alongside
`LookerMigration.pbip`, `LookerMigration.SemanticModel/` and `LookerMigration.Report/`.
If no model can be converted, generation returns a validation failure but saves the review JSON;
it does not fabricate a project. Empty dashboard input can yield an empty review page.

For the three-visual variant, inspect the `visual.json` files: the line and column charts project
the `orders.region` column as `Category` and the `orders.sales` measure as `Y`; the card projects
the measure as `Data`. Inspect their `queryRef` and `nativeQueryRef` bindings. To check
reproducibility, generate again from the same imported inventory and project name into another
fresh directory and compare relative paths and file bytes.

The API importer accepts direct `${TABLE}.column` dimensions of type `string`, `number`, `yesno`
or `date`, and unfiltered `sum`, `average`, `min`, `max` and `count_distinct` measures over a
direct column. The generator requires an unambiguous declared dimension for that column; sum and
average require a numeric dimension, min and max a numeric or date dimension.
`count_distinct` uses `COALESCE(DISTINCTCOUNTNOBLANK(...), 0)`; a SQL-less `count` uses
`COALESCE(COUNTROWS(...), 0)` for a directly authored canonical asset but is not normalized by
the API importer. These expressions do not establish runtime equivalence.

| Exact `vis_config.type` | Canonical type | PBIR `visualType` | Fields from one view |
|---|---|---|---|
| `looker_grid` | `table` | `tableEx` | One or more supported dimensions or measures |
| `looker_bar` | `bar` | `clusteredBarChart` | Exactly one dimension and one measure |
| `looker_line` | `line` | `lineChart` | Exactly one dimension and one measure |
| `looker_column` | `column` | `clusteredColumnChart` | Exactly one dimension and one measure |
| `single_value` | `card` | `cardVisual` | Exactly one measure and no dimension |

`vis_config` must contain only `type`; any extra key, even with a null value, blocks the visual.
Pages use a fixed grid of at most six visuals, not source layout.

Joins/relationships, joined fields, filters, access controls, derived tables, arbitrary SQL,
calculations, pivots, query shaping, non-unlimited limits, and other visual configurations are
not migrated. Unsupported or missing filter, query-shaping, join, security or other context is
diagnosed and prevents affected visuals from being emitted rather than silently dropping
constraints. Diagnostics use fixed paths and codes rather than sensitive values. Unsupported
fields may be omitted; review all diagnostics, including metadata and layout not migrated. Safe
source table identifiers may be retained in the imported inventory, but not bound into the
generated project. All generated partitions deliberately error on refresh; no credentials or
deployment are provided. The deterministic output is review-only: runtime, precision,
source/target parity and security have not been validated, and an offline structural check is
not a Desktop open or refresh test.

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

Review the `Wave decision summary` in `migration-plan.md` and the `waves` array in
`migration-plan.json`. A wave is `blocked` when its plan items carry manual-review reasons or
unresolved dependencies. `ready_for_review` means only that the local decision package is complete
enough for human review; it does not mean deployable or runtime-parity proven.
Wave `owner` is `unassigned` until a migration program assigns a responsible team. `effort_band`
(`S`, `M`, `L`, or `XL`) is deterministic triage metadata, not a delivery estimate or cost model.
Generated waves always have `approval_status: pending_review`; changing it to `approved`, `deferred`,
or `rejected` requires a future explicit review workflow and is not performed by offline generation.
The generated `wave-signoff.json` is the portable summary for a review board. Its
`approvalPolicy` is `human_review_required`; it records parity status and criteria but never grants
approval or deployment authority. `parityEvidence` contains per-check status, provenance, and
`collectedAt`; absent values are explicitly `not_recorded`.
`securityEvidence` separately reports security blockers and review codes. Its `effectiveAccess` and
`fabricPermissionParity` fields remain `not_recorded` unless a future approved evidence source
supplies them; absence of a security finding is not a security pass.
`evidence-manifest.json` hashes the assessment, summary, migration plan, and sign-off files. Use
the local `verify_evidence_manifest` contract before accepting a package; it detects byte changes
but does not establish source-system authenticity or runtime parity. `validate_artifact` also checks
this manifest when it is present in a package.

Also inspect `assessment-summary.json` when feeding a dashboard or HTML report. `write_reports`
creates this deterministic presentation summary with `projectId`, `score`, `evidenceCoverage`,
`architecture`, `componentCount`, `findingCounts`, `targetSummary`, `compatibilitySummary`,
`discoveryCoverage`, `paritySummary`, `manualReviewCount`, `manualReviewReasons`,
`unresolvedDependencies`, `blockers`, and `status`. It complements rather than replaces the
detailed `assessment.json`.

`discoveryCoverage` counts objects by provenance. Review the `assisted` count before approving a
wave: those components carry evidence an agent inferred rather than read from a source system.

`FAIL` findings block reliance on the affected recommendation until the evidence or compatibility
issue is resolved or explicitly accepted. `WARN` findings require documented design or manual
review. Discovery exit code `3` means the required read-only ADC, API, or metadata visibility could
not be established; it does not indicate a deployment failure or success.

`python -m pyright` and `python -m ruff check src tests` are local static-quality gates. Their
success validates Python typing and lint checks only; it does not validate generated artifacts
against official Fabric schemas or APIs, establish runtime parity, or authorize deployment.

### Review connection transcode and repair results

The offline connectivity contract maps canonical GCP connection metadata to a deterministic Fabric
reference candidate without creating a connection or persisting credentials. Embedded credential
material and unsupported backends produce `manual_review`; only the finding type is retained.
The normal report/generate flow writes these records to `connection-transcode.json` for review.
The generic repair loop applies explicitly supplied `RepairRule` instances once by default, records
the rules that changed the value, and revalidates the result. With `max_passes > 1` it repeats the
rules until a pass changes nothing; a value that has not converged by the last pass is
`manual_review`. Domain rules move misplaced pipeline
`triggers` to the resource level and remove only exact duplicate schema fields; conflicting
duplicate definitions remain `manual_review`. A failed validator remains `manual_review`. Repairs are opt-in
and operate on a defensive copy rather than silently rewriting a persisted artifact.

Validate these contracts with:

```powershell
python -m pytest tests/test_connectivity_enabler.py tests/test_repair_loop.py tests/test_parity.py
```

These results are planning evidence only. They do not prove Fabric connectivity, identity binding,
runtime parity, or deployment readiness.

### Compare canonical inventories offline

`inventory-drift` compares two validated canonical inventory files without contacting GCP or
writing files itself. Both files must be validated canonical inventories for the same project.
For example, redirect its JSON stdout to save the report:

```powershell
bqtofabric inventory-drift baseline.json current.json > drift.json
```

The deterministic JSON report contains `baselineProject`, `currentProject`, `added`,
`removed`, `changed`, and `status`. Each `changed` entry includes the differing field paths;
property values are never copied into the report. Review `drift.json` as offline comparison
evidence only: it does not verify live discovery or establish why an inventory changed.

### Run the opt-in live GCP discovery gate

The live integration test is disabled unless explicitly enabled. It requires Application Default
Credentials with read-only access, the BigQuery and external-adapter APIs, and an authorized
sandbox project with visibility in the configured regions. The external adapters request the
broader `cloud-platform.read-only` scope.

```powershell
$env:BQTOFABRIC_LIVE_GCP = "1"
$env:BQTOFABRIC_GCP_PROJECT = "your-sandbox-project"
$env:BQTOFABRIC_DATAFLOW_REGIONS = "us-central1"
$env:BQTOFABRIC_DATAPROC_REGIONS = "us-central1"
$env:BQTOFABRIC_COMPOSER_REGIONS = "us-central1"
$env:BQTOFABRIC_DATAFORM_LOCATION = "us-central1"

python -m pytest -m live_gcp tests/test_live_gcp_discovery.py -v
```

The test runs the public `discover` command twice with BigQuery, Dataflow, Dataproc, Dataform,
and Composer enabled. It requires byte-identical canonical output, checks adapter provenance, and
scans the result for credential-like values. Do not enable it in CI until the sandbox and scope
approval are in place. The default test command remains cloud-free.

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

The focused test passes in CI. Measured workload telemetry and runtime benchmarking remain open and
are required before making performance or tuning claims.

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

The focused test passes in CI. The validator performs offline pattern and structural checks only;
pattern scanning is not a substitute for official Fabric schema validation or deployment
validation. Validation now runs after every artifact is written, so `parity-evidence.json` and
`deployment-manifest.json` are covered by the credential scan and the structural checks too.

An artifact's `valid` flag is derived from a real content check rather than asserted by the
generator:

| Validator | Rejects |
|---|---|
| `NotebookValidator` | Undefined DataFrame references |
| `TsqlValidator` | A comment-stripped `CREATE TABLE` that does not re-parse, `#` comments, and `CREATE SCHEMA` outside its own batch |
| `PipelineValidator` | Parameters or variables that are not name-keyed, `triggers` as a pipeline property, and secret-bearing expressions |
| Airflow compatibility validator | Missing Composer/Airflow report contract fields |
| Warehouse generator guard | Empty or control-character schema, object, or column identifiers |
| Manifest consistency validator | Duplicate generated artifact paths for different source IDs |
| Manifest path confinement | Artifact paths resolving outside `generated/`, including `..` traversal |

A generated Warehouse view body is converted GoogleSQL → T-SQL. When conversion fails or produces
constructs Fabric Warehouse does not support, the body is omitted, the artifact is marked invalid,
and the candidate conversion appears as `--` comments for review. Generated pipelines carry named
connection references bound to managed identity instead of connection strings. Manifest paths use
POSIX separators so output is byte-identical across platforms.

The validator also rejects a non-object JSON root with a deterministic validation error instead of
raising. Parity evidence is hardened separately: negative or boolean row counts, duplicate schema
field names, and malformed nested fields are classified as `not_run`.

Validate both contracts with:

```powershell
python -m pytest tests/test_artifact_validation.py -v
python -m pytest tests/test_parity.py -v
```

Both focused suites pass in CI. These checks are offline-only and do not replace official Fabric
schema validation, workload execution, or runtime/data parity evidence.

### Review parity evidence

Parity status is recomputed from evidence on every run. A `status` recorded in the inventory is
never trusted:

- Each check is derived from its own `source` and `target` payload.
- A declared `passed` with no payload resolves to `not_run`.
- A declared status that contradicts the computed result is preserved as `declaredStatus`, so the
  disagreement is visible during review rather than silently overwritten.
- The `type` check was removed because no comparator backed it. The check set is `schema`,
  `row_count`, `checksum`, `aggregate`, `null_distribution`, `sample`, and `sql_result`.
- Applicability is keyed on data-bearing kind — table, external table, view, materialized view —
  rather than on whether columns happened to be captured.

A `failed` check emits `PARITY_FAILED` and adds the `parity_failed` manual-review reason. An
applicable check with missing or malformed evidence emits `PARITY_NOT_RUN`. No source or Fabric
query is executed, so `passed` means the supplied evidence agrees — never that the data matches at
runtime.

### Collect parity evidence with the parity kit

```powershell
bqtofabric parity-pack inventory.json --output artifacts/parity
# Run parity-source.sql in BigQuery and parity-target.sql in Fabric, then save results.json:
# {"pack_id": "<from parity-pack.json>", "results": [
#   {"query_id": "<id>", "source": [{...row...}], "target": [{...row...}], "collected_at": "..."}]}
bqtofabric parity-ingest inventory.json --pack artifacts/parity/parity-pack.json `
  --results results.json --output inventory-with-parity.json
bqtofabric assess inventory-with-parity.json
```

**What the pack contains:**

- **Checks generated:** `row_count` for every data-bearing component. For flat columns it adds
  `null_distribution`, and for integer and decimal columns it adds `aggregate`
  (`SUM`/`MIN`/`MAX`).
- **Checks not generated:** `schema`, `checksum`, `sample`, and `sql_result`. The pack explains
  why under `not_generated`.
- **Unsafe names:** components whose identifiers fail a strict allowlist are skipped rather than
  interpolated.

**How ingestion behaves:**

- **Tampering and mismatches:** it rejects a modified pack, results for a different `pack_id`, and
  unknown query IDs.
- **One-sided results:** a result that is missing either side leaves the check `not_run`.
- **No status is written:** only payloads are attached, and `assess` recomputes each status.

The target table name is the proposed `schema.table` name (`[dataset].[name]` for Warehouse,
`` `dataset`.`name` `` for Lakehouse). Edit `parity-target.sql` if the deployed names differ.

### Review the readiness score

The readiness score is computed per component, scaled by evidence coverage, and forced to zero for
any component carrying a `FAIL` blocker. Type risk and SQL risk fold into the component that owns
them, and schema width no longer contributes. A low score with high `FAIL` or `EVIDENCE_MISSING`
counts therefore reflects incomplete evidence rather than an arbitrary penalty; close the evidence
gaps first and re-assess.

### Verify CLI and deployment-readiness failure paths

The local contract fails closed for invalid inputs and incomplete generated packages:

| Failure path | Expected result |
|---|---|
| Missing inventory | CLI exit code `2` |
| Malformed inventory | CLI exit code `5` |
| Tampered deployment manifest | Manifest verification exit code `5` |
| Invalid artifact validation | `deployment-check` blocks |
| `FAIL` findings or recorded blockers | `deployment-check` blocks |
| Failed parity | `deployment-check` blocks |
| A component mapped `redesign` | `deployment-check` blocks |
| Unsupported target component | `deployment-check` blocks |
| Pending manual review | `deployment-check` blocks |
| Unresolved dependencies | `deployment-check` blocks |

Validate the complete failure-path contract with:

```powershell
python -m pytest tests/test_cli.py tests/test_deployment_readiness.py
```

The focused suite passes in CI. These are offline, deterministic guards before any future
deployment phase; they do not validate official Fabric schemas or APIs, execute workloads,
establish runtime or data parity, or perform cloud operations. `ready_for_review` is a local gate
result, never a deployment approval.

### Validate the canonical inventory contract

The JSON provider validates `project_id`, dataset/object IDs and names, known object kinds,
duplicate source IDs, column structures, dependency arrays, and non-negative `size_bytes` before
model coercion. Explicit `null` `size_bytes` remains valid optional evidence. This validation is
offline and non-destructive; it does not validate cloud schemas, runtime behavior, data parity, or
deployment readiness.

Validate the focused provider and CLI contract with:

```powershell
python -m pytest tests/test_models.py tests/test_cli.py
```

The focused suite passes in CI. For the per-kind required-evidence matrix an inventory author must
satisfy, see [INVENTORY_SCHEMA.md](INVENTORY_SCHEMA.md#required-evidence-by-kind).

### Validate adapter contract edge cases

Composer normalization extracts task connection names even when the DAG dependency map is empty.
If no task declares a connection, it emits explicit `connections: []`, which is distinct from
missing evidence. Dataflow discovery deduplicates repeated job IDs across regional and paginated
payloads deterministically.

Run the focused offline contract tests with:

```powershell
python -m pytest tests/test_discovery.py tests/test_dataflow_discovery.py
```

The focused suite passes in CI. These fixtures do not validate official GCP API behavior, live
permissions, metadata freshness, runtime or data parity, or an authorized live-GCP sandbox. The
Dataflow, Dataproc, Dataform, and Composer adapters are live but opt-in; regional adapters never
scan all regions, and none has been exercised against an authorized sandbox.

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
    # Optional opt-in live adapters. Each makes credentialed read-only Google API calls and
    # requests the broader cloud-platform.read-only scope. Without a flag, discovery is
    # BigQuery-only.
    bqtofabric discover <project-id> `
        --dataflow-region europe-west1 `
        --dataproc-region europe-west1 `
        --dataform --dataform-location us-central1 `
        --composer-region us-central1 `
        --output artifacts/<project-id>/inventory.json
    bqtofabric validate artifacts/<project-id>/inventory.json
    bqtofabric inventory artifacts/<project-id>/inventory.json
    bqtofabric assess artifacts/<project-id>/inventory.json
    bqtofabric map artifacts/<project-id>/inventory.json
    bqtofabric plan artifacts/<project-id>/inventory.json --output artifacts/<project-id>/plan
    bqtofabric generate artifacts/<project-id>/inventory.json --output artifacts/<project-id>/project
    bqtofabric deployment-check artifacts/<project-id>/project/fabric
    ```

## Discovery capability and permissions

The BigQuery path uses ADC with the `https://www.googleapis.com/auth/bigquery.readonly` scope and
requires the BigQuery API, BigQuery Data Transfer API, and BigQuery Connection API.

> [!WARNING]
> The Dataflow, Dataproc, Dataform, and Composer adapters are **live, credentialed, read-only
> Google API calls**, not offline payload normalization. They are opt-in: nothing contacts those
> services unless the corresponding CLI flag is supplied. All four request
> `https://www.googleapis.com/auth/cloud-platform.read-only`, which is **broader** than
> `bigquery.readonly`. A security administrator must review and approve that scope before first
> use. **None of the adapters has been validated against an authorized GCP sandbox** — the adapter
> code exists and is covered by offline fixture tests; the live verification does not exist.

All adapters are read-only, redact credential-like metadata, pseudonymize principal identities as
stable non-reversible `principal:<12 hex>` values, bound their paging, reject repeated page tokens,
and never print provider response bodies. Regional adapters never scan all regions.

| Source family | Live adapter? | Enabled by | Rights extracted? | Minimum discovery permission/role guidance | Assessment status |
|---|---|---|---|---|---|
| BigQuery core: datasets, tables, views, materialized/external tables, routines, procedures, BQML models | Yes, `bigquery.readonly` | Always | No Cloud IAM bindings | Dataset-level metadata visibility, such as `roles/bigquery.metadataViewer`, for every dataset in scope | Live metadata extraction; assessed and mapped offline |
| BigQuery jobs | Yes, `bigquery.readonly` | Always | No | For estate-wide history, use project-level `roles/bigquery.resourceViewer`, which supplies `bigquery.jobs.listAll`; do not grant broad administrative roles for discovery | Live metadata extraction; assessed and mapped offline |
| Scheduled queries (BigQuery Data Transfer transfer configurations) | Yes, `bigquery.readonly` | Always | No | Grant only the Data Transfer visibility required for the transfer configurations in scope; validate the exact role with the security administrator | Live metadata extraction; assessed and mapped offline |
| BigQuery connections | Yes, `bigquery.readonly` | Always | Connection IAM bindings are not extracted | Grant `bigquery.connections.get` and `bigquery.connections.list`, for example through a suitable role such as `roles/bigquery.connectionUser` where appropriate | Live metadata extraction; assessed and mapped offline |
| Dataset ACLs (`datasets.get` payload `access` entries) | Yes, `bigquery.readonly` | Always | Redacted, principal-pseudonymized dataset access entries only, with `evidence_scope: dataset_access_entry`; they do not prove effective project, organization, group, or inherited IAM access | Dataset metadata visibility, such as `roles/bigquery.metadataViewer`, for every dataset in scope | Assessment emits `FAIL` `SECURITY_EFFECTIVE_ACCESS_REVIEW`; manual security review required |
| Dataflow regional jobs | **Yes, `cloud-platform.read-only`** | `--dataflow-region` (repeatable) | No | Security-administrator-validated, read-only Dataflow job visibility for each requested region; use least-privilege viewer guidance rather than broad administrative access | Live identity, state, type, labels, timestamps, and present environment/pipeline metadata; missing compatibility evidence remains a finding |
| Dataproc regional jobs and clusters | **Yes, `cloud-platform.read-only`** | `--dataproc-region` (repeatable) | No | Security-administrator-validated, read-only Dataproc job and cluster visibility for each requested region | Live job type, language, and cluster-derived `runtime_version`; `unknown` remains missing evidence |
| Dataform repositories, workflows, and compilation results | **Yes, `cloud-platform.read-only`** | `--dataform`, `--dataform-location` | No | Security-administrator-validated, read-only Dataform repository and compilation-result visibility | Successful details aggregate models/assertions/incremental evidence; a detail-request failure emits an incomplete fallback workflow and requires manual review |
| Composer environments and DAGs | **Yes, `cloud-platform.read-only`** | `--composer-region` (repeatable) | No | Security-administrator-validated, read-only Composer environment visibility for each requested region | Live image/environment version, declared operators, and declared task connection names; no connection configuration or secrets |
| Project/org IAM | No | — | No | No IAM API calls; live adapter and permission contract not implemented | Not extracted; manual security review required |
| Connection IAM | No | — | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |
| Distinct row access policies, BigQuery Data Policies, and policy tags | No | — | No | Live adapter and permission contract not yet implemented; security review required | Canonical/offline assessment type only |
| Workflows | No | — | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |
| Pub/Sub | No | — | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |
| Cloud Storage (GCS) | No | — | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |
| Looker | No | — | No | Live adapter and permission contract not yet implemented | Offline assessment and bounded review-only Power BI scaffold |
| Vertex AI | No | — | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |
| Dataplex | No | — | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |
| Cloud SQL | No | — | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |
| Spanner | No | — | No | Live adapter and permission contract not yet implemented | Canonical/offline assessment type only |

### Exit code 3

Exit code `3` means discovery could not establish the required read-only access. Re-run
`gcloud auth application-default login`, confirm the APIs for the adapters you enabled are
enabled, then have a security administrator verify the relevant least-privilege visibility in the
matrix. Do not add credentials, tokens, or service-account keys to the inventory or command line.

Workflows, Pub/Sub, GCS, Looker, Vertex AI, Dataplex, Cloud SQL, and Spanner have offline
normalization and assessment support; they do not have live adapters. Looker also has the bounded
offline review-only Power BI scaffold above. The live adapters that
do exist are opt-in per flag and, for Dataflow, Dataproc, and Composer, per region. Each requested
region must have separately validated read-only visibility. Extraction triggers no deployment
behavior.

### Discovery provenance

Canonical components carry a `discovered_from` value so review can distinguish acquisition paths.
The canonical values are `inventory` (imported canonical JSON, the default), `bigquery_api`,
`dataflow_api`, `composer_api`, `dataproc_api`, `dataform_api`, and `external_payload`. Assessment
repeats the value for each object in `evidence_summary` and reports deterministic counts by source
in `discovery_coverage`.

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
graph's completeness. This behavior is validated by `python -m pytest tests/test_discovery.py
tests/test_assessment.py tests/test_dataform_conversion.py`, which passes in CI.

### Composer schedule review

Composer has an opt-in read-only live adapter (`--composer-region`) that has not been validated
against an authorized GCP sandbox. Normalization writes `properties.schedule_interval` as the
canonical schedule field and retains `properties.schedule` for compatibility. Generated pipelines
read `schedule_interval` first and fall back to `schedule`, preserving `@daily`, `@hourly`, and
`@weekly` trigger mapping for legacy inventories.

Raw cron expressions are not automatically mapped. They remain review-required until the source
cron, timezone, start-date, catchup, retries, and equivalent Fabric trigger semantics are reviewed.
This limitation does not imply trigger execution or schedule parity. The behavior is validated by
`python -m pytest tests/test_discovery.py tests/test_artifact_generation.py`, which passes in CI.

### Composer adapter-evidence review

For each normalized Composer DAG, `properties.runtime_version` uses the Composer image version when
present, then a sanitized environment-version label, then `unknown`. `properties.connections`
contains only declared task connection names found in `conn_id`, `connection_id`, `gcp_conn_id`, or
`google_cloud_conn_id`. No connection configuration, secret, or credential data is serialized.

An explicit `connections: []` is complete evidence that no task declared a connection, while a
missing `connections` field remains incomplete evidence during assessment. In either case, inspect
connection configuration, secret bindings, and effective runtime access manually before accepting a
migration recommendation.

This behavior is validated by `python -m pytest tests/test_discovery.py tests/test_assessment.py`,
which passes in CI. The evidence contract records static declarations only; it does not establish
runtime access parity, and the Composer adapter itself has not been exercised against an authorized
GCP sandbox.

### Dataproc adapter-evidence review

Dataproc job normalization writes canonical `properties.language`: PySpark maps to `python`, Spark
SQL and Hive map to `sql`, and Pig maps to `pig`. Unsupported or ambiguous job types map to
`unknown`; the existing `properties.runtime` job classification remains unchanged.

`properties.runtime_version` is inherited from the referenced cluster's
`config.softwareConfig.imageVersion` when present, otherwise `unknown`. Assessment treats
`unknown` and `not specified` as missing evidence, not as complete readiness evidence. Supply the
runtime version or re-discover from a payload whose referenced cluster contains `imageVersion`
before accepting readiness as complete.

This behavior is validated by `python -m pytest tests/test_discovery.py tests/test_assessment.py`,
which passes in CI. The evidence contract does not establish runtime execution or parity, and the
Dataproc adapter has not been exercised against an authorized GCP sandbox.

### Incomplete external payloads

An `external_payload` component without required offline evidence receives exactly one assessment
finding: `FAIL` `EXTERNAL_PAYLOAD_INCOMPLETE_ADAPTER` in category `adapter`. It states that the
offline evidence must be completed because the component was supplied rather than discovered.
Resolve the evidence gap before relying on its target recommendation or migration wave.

The planner marks the incomplete component and all direct and transitive dependents
`manual_review`. This propagation is a review requirement, not an unresolved dependency:
`unresolved_dependencies` remains for missing or external source IDs and dependency cycles. The
workflow stays offline and does not call external GCP services or add live adapters.

### Manual-review reasons

`manual_review` remains the planner's decision flag. A flagged `PlanItem` also carries a
deterministic `manual_review_reasons` list so reviewers can identify why action is needed. Reasons
are recorded independently, so one component can carry several. Review all 12 codes before
approving a migration wave: `cycle_or_unresolved_dependency`,
`depends_on_incomplete_dataform_compilation`, `depends_on_incomplete_external_adapter`,
`external_dependency`, `incompatible_mapping`, `incomplete_dataform_compilation`,
`incomplete_external_adapter`, `missing_required_evidence`, `parity_failed`, `security_review`,
`sql_incompatibility`, and `streaming_downstream_review`. Their triggers are tabulated in the
[mapping reference](MAPPING_REFERENCE.md#manual-review-decision-contract).

`migration-plan.md` renders the decision flag and codes. The generated
`fabric/target-manifest.json` renders the corresponding `manualReview` and
`manualReviewReasons` fields for target-level review. These are deterministic dry-run planning
metadata and introduce no cloud calls or deployment behavior.

### Migration-plan findings

The generated `migration-plan.md` includes a `Findings` section copied from assessment output. Each
entry lists `severity`, `code`, `category`, `source`, and `message`, making `WARN` and `FAIL`
conditions visible in the human review report. Treat these entries as actionable review evidence:
resolve, document, or explicitly accept each relevant finding before relying on a migration wave.

All 18 finding codes, with their severity, category, trigger, and the reviewer action each expects,
are tabulated in the
[finding-code reference](MAPPING_REFERENCE.md#assessment-finding-codes). Triage by code, not by
message text; message wording is not a stable contract.

Type findings are attributable to the object that owns the type. A `TYPE_REDESIGN` or
`TYPE_UNSUPPORTED` finding's `source_id` is the table or view, with one finding per distinct type
per object listing the affected column paths.

### Review SQL fidelity

The converter preserves `DIRECT` compatibility for existing supported GoogleSQL cases. It detects
`SAFE_CAST` and `NOT IN`, downgrades affected conversions to `TRANSFORM`, and emits semantic
warnings and manual parity steps. Inspect those warnings and steps in the conversion output, then
design source-versus-target checks for the affected null-handling and membership semantics.

Validate the focused conversion contract with:

```powershell
python -m pytest tests/test_sql_converter.py
```

The focused suite passes in CI. Assessment and generation share one SQL conversion stack:
`sql_assessment` delegates to the `converter/` package (`SqlConverter`), and SQL compatibility is
the worst of the converter verdict, the detected semantic risks, and the mapping decision — it never
defaults to `direct`. A non-SQL routine body, such as a JavaScript UDF, is `redesign` and emits no
converted SQL. This is an offline conversion check only; it does not execute source or target SQL,
validate official Fabric schemas, or establish runtime/data parity. Do not approve transformed SQL
without separate parity evidence.

The section is not proof that a finding has been remediated, that Fabric deployment is ready, or
that runtime parity has been established. Use `assessment.json`, mapping output, generated artifacts,
and independent parity/security checks for deeper review.

### Schedule-trigger start time

Generated schedule triggers use `@utcNow()` for `startTime` instead of retaining the stale fixed
`2024` date. This keeps the generated trigger start time current for the supported preset schedule
mappings while preserving deterministic, offline artifact generation.

This behavior is validated by `python -m pytest tests/test_artifact_generation.py`, which passes in
CI. Generated pipeline definitions remain review artifacts: validate them against the official
Fabric/ADF schema and complete deployment validation before deployment.

### Pipeline activity resilience defaults

Generated operational activities use deterministic policy defaults: `retry: 3`,
`retryIntervalInSeconds: 30`, `secureInput: true`, and `secureOutput: true`. The failure handler
retains its specialized secure policy. Validate the generated definition and its retry behavior
against the official Fabric/ADF schema and runtime before treating it as deployable. This behavior
is validated by `python -m pytest tests/test_artifact_generation.py`, which passes in CI.

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
python -m pytest tests/test_cli.py tests/test_deployment_readiness.py
```

The focused suite passes in CI. This artifact is generated from local inputs and is
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
    create-only-when-absent statement and preserve existing definitions. View bodies are converted
    GoogleSQL → T-SQL; when conversion fails or produces constructs Fabric Warehouse does not
    support, the body is omitted, the artifact is marked invalid, and the candidate conversion is
    emitted as `--` comments for review. An Eventhouse
    schema with no source columns is marked invalid: its artifact contains review comments and a
    `REDESIGN` warning only, with no KQL create, ingestion-mapping, or materialized-view statements;
    the artifact manifest records `valid: false`. Normal Eventhouse schema generation is unchanged.
    Generated Eventstream output is likewise a non-deployable review scaffold: it sets
    `deployable: false` and artifact `valid: false`, and its source node uses
    `connectionReference: review_required` rather than an invented `connectionId`. It includes
    authoring TODOs and the artifact manifest propagates `valid: false`.
    For a table, view, or materialized view with no discovered columns, semantic-model generation
    instead returns an invalid review-only scaffold: `valid: false`, `deployable: false`, and
    `validationStatus: pending_source_schema`, with no tables, measures, relationships, or
    connection placeholders. It emits a `REDESIGN` warning requiring source-schema discovery and
    regeneration; normal schema-backed output is unchanged.
    Every `valid` flag is derived from a real content check by `NotebookValidator`,
    `TsqlValidator`, or `PipelineValidator` rather than asserted by the generator.
    These structural dry-run guards are not official Fabric validation or deployment; author the
    Eventstream against the official Fabric API/schema and supply approved connections before
    deployment. Regenerated semantic models still require official Fabric semantic-model
    schema/API validation. All generated output requires validation and an explicit deployment
    workflow before it can be treated as deployable. Artifact generation processes each category
    in sorted source-ID order, serializes JSON artifacts, manifests, and notebooks with sorted
    keys, aggregates warnings in source-ID order, and writes manifest paths with POSIX separators.
    Equivalent inventories therefore produce identical artifact paths and bytes even when input
    component order or host platform differs. Each artifact filename combines a filesystem-safe
    source ID with the first 12 hexadecimal characters of that source ID's SHA-256 digest, so
    distinct source IDs cannot collide on a generated filename.
    Numeric `Count of <column>` measures use DAX `COUNT`, so the generated measure counts populated
    values as its name implies. Generated semantic models remain dry-run review artifacts and still
    require official Fabric semantic-model schema/API validation before deployment. These behaviors
    are validated by `python -m pytest tests/test_artifact_generation.py`, which passes in CI.
5. Design parity checks for row counts, schemas, nulls, aggregates, samples, and security behavior.
    Supplied parity evidence is always recomputed; a declared `status` is ignored, and a contradiction
    is preserved as `declaredStatus`.
6. Use the native Fabric BigQuery connector for Dataflow Gen2, Pipeline Copy/Lookup, or Copy Job.
7. Pilot one representative dataset before scaling by migration wave.
8. Add live deployment only after explicit approval, credentials, rollback, and audit controls.
