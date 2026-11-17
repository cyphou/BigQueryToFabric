# Public offline Looker examples

These are public, checked-in inputs, not live Looker discovery. The copied upstream files are
unchanged; nine files in total, including both licenses, were hash-verified against the original
downloads.

These examples cover the saved dashboard API path and a manually assisted inventory. For the
separate versioned, pre-parsed LookML JSON import and its unresolved-context visual gate, see
the [LookML contract](../../docs/MIGRATION_RUNBOOK.md#offline-lookml-derived-metadata-normalizer).
It does not parse the raw LookML files included here.

## Provenance and evidence

* `looker-cli/Dashboard_17_FAA_KPIs.json`: [looker-open-source/looker-cli](https://github.com/looker-open-source/looker-cli/blob/b8a506bea2d31bbf3e5f90d544f1fdf5bb3b4292/examples/Dashboard_17_FAA_KPIs.json),
  commit `b8a506bea2d31bbf3e5f90d544f1fdf5bb3b4292`; SHA256
  `0e9623f09b9480a7f98016d48c9377979d49b2e4bd298757c77aca6b087147b6`.
  The upstream Apache-2.0 license is copied in `looker-cli/LICENSE`.
* The LookML files under `looker-skills/` are a subset of
  [looker-open-source/looker-skills](https://github.com/looker-open-source/looker-skills/tree/ce5ad43e76d57affddb8b54e472b6408dad352ca),
  commit `ce5ad43e76d57affddb8b54e472b6408dad352ca`, with its Apache-2.0 license in
  `looker-skills/LICENSE`. Some included LookML dependencies are missing locally. The manifest's
  dataset is an overrideable default, not proof of actual access or of the effective value.
* `looker-skills/inventory.assisted.json` is a **manually selected, partially normalized
  LookML-derived canonical inventory**, marked `discovered_from: assisted`. It is neither a
  computed API response nor the output of an automatic LookML parser. It intentionally omits
  uncertain evidence; assessment reports `ASSISTED_EVIDENCE_UNVERIFIED`. Inspect the original
  sources and review findings rather than treating this selection as a complete model.

## Setup

Run the following PowerShell from the repository root. Install BQToFabric locally as described in
the [runbook](../../docs/MIGRATION_RUNBOOK.md#test-the-assessment-locally). Separately install a
trusted compatible [TableauToPowerBI](https://github.com/cyphou/TableauToPowerBI) 44.0.0 source
checkout and its dependencies. The checkout must contain `powerbi_import` and `tableau_export`;
it is not bundled or fetched by these commands.

```powershell
$tableauCheckout = "C:\path\to\trusted\TableauToPowerBI"
$env:PYTHONPATH = "$tableauCheckout;$env:PYTHONPATH"
```

The commands below are offline. Each uses a fresh directory under `$env:TEMP`: change the directory
name for another run. Python creates the directories exclusively, so an existing output is an
error, not an overwrite. Check command exit codes before continuing.

## Synthetic coverage versus public examples

**Expected:** The [runbook](../../docs/MIGRATION_RUNBOOK.md#offline-looker-api-to-power-bi-review-project)
describes an optional three-visual synthetic envelope, separate from the public samples below.

**Implemented:** Exact `vis_config.type` values `looker_line`, `looker_column` and `single_value`
map to canonical `line`, `column` and `card`, then to PBIR `lineChart`,
`clusteredColumnChart` and `cardVisual`. Existing `looker_grid` and `looker_bar` remain supported.
Bar, line and column require exactly one dimension and one measure; cards require exactly one
measure and no dimension, from one view. Extra `vis_config` keys and unsupported or missing
filter, query-shaping, join, security or other context suppress affected visuals; diagnostics
omit sensitive values. Output is deterministic, review-only and source binding is disabled.

**Validated:** A synthetic offline run produced all three visuals with checked role/reference
bindings and byte-identical repeat output; TableauToPowerBI 44.0.0 static structure/openability
checks passed including all three. The targeted Looker suite passed 203 tests with no skips; Ruff
and Pyright passed. `powerbi-report-author` 0.5.0 `validate --no-schema` reported 0 errors and
0 warnings with Node network access blocked. These results do not change the public sample
outcomes below.

**Open:** Remote JSON Schema validation was explicitly skipped; no Desktop opening, runtime or
refresh tests, deployed-security checks, real-data or visual parity checks, deployment or cloud
calls were performed.

## FAA dashboard response

The dashboard has six elements, including two linked Looks. The Python wrapper preserves the
checked-in dashboard and creates a real JSON `explores: []` array. Do not invent an Explore,
security grant, source binding or filter evidence to fill the missing context. PowerShell's
`ConvertTo-Json` can serialize empty arrays incorrectly; this wrapper uses Python's `json` module.

```powershell
$env:LOOKER_EXAMPLE_OUT = Join-Path $env:TEMP "bqtofabric-looker-faa"
@'
import json
import os
from pathlib import Path

out = Path(os.environ["LOOKER_EXAMPLE_OUT"])
out.mkdir(parents=True, exist_ok=False)
dashboard = json.loads(Path(r"examples\looker\looker-cli\Dashboard_17_FAA_KPIs.json").read_text(encoding="utf-8"))
inventory = {"project_id": "demo-project", "schema_version": "1.1",
             "datasets": [], "components": [], "metadata": {}}
payload = {"explores": [], "dashboards": [dashboard]}
for name, data in (("inventory.json", inventory), ("payload.json", payload)):
    with (out / name).open("x", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
'@ | python -
if ($LASTEXITCODE -ne 0) { throw "Could not create fresh FAA inputs" }

bqtofabric import-looker-api "$env:LOOKER_EXAMPLE_OUT\inventory.json" --payload "$env:LOOKER_EXAMPLE_OUT\payload.json" --output "$env:LOOKER_EXAMPLE_OUT\imported.json"
if ($LASTEXITCODE -ne 0) { throw "FAA import failed" }
bqtofabric generate-looker-powerbi "$env:LOOKER_EXAMPLE_OUT\imported.json" --asset demo-project.looker.api_export --output "$env:LOOKER_EXAMPLE_OUT\review"
if ($LASTEXITCODE -ne 5) { throw "Expected FAA generation exit 5, got $LASTEXITCODE" }
```

**Measured offline:** import exited 0; generation exited 5 and wrote only
`review/looker-powerbi-review.json`, with nine ingestion diagnostics and one
`no_convertible_model` issue and no PBIP because the Explore is missing. The final two elements
have value-free `linked_look_not_migrated` diagnostics, not `invalid_element`. No missing Explore,
source, security or filters are invented.

## Assisted LookML-derived inventory

The source dashboard contains seven tiles: one navigation text tile and six visual tiles. The
subset also includes five joins, filters, a model access grant, refinement and Liquid. These are
source constructs, not claims that they migrated.

```powershell
$env:LOOKER_EXAMPLE_OUT = Join-Path $env:TEMP "bqtofabric-looker-skills"
@'
import os
from pathlib import Path
Path(os.environ["LOOKER_EXAMPLE_OUT"]).mkdir(parents=True, exist_ok=False)
'@ | python -
if ($LASTEXITCODE -ne 0) { throw "Could not create fresh LookML output directory" }

$inventory = "examples\looker\looker-skills\inventory.assisted.json"
bqtofabric validate $inventory
if ($LASTEXITCODE -ne 0) { throw "Validation failed" }
bqtofabric assess $inventory
if ($LASTEXITCODE -ne 0) { throw "Assessment failed" }
bqtofabric generate-looker-powerbi $inventory --asset enterprise_analytics.looker.orders --output "$env:LOOKER_EXAMPLE_OUT\review"
if ($LASTEXITCODE -ne 0) { throw "Generation failed" }
```

**Measured offline with the real compatible 44.0.0 backend:** validate, assess and generate exited
0. Assessment counted one assisted object and reported `ASSISTED_EVIDENCE_UNVERIFIED`. The
review-only PBIP contains exactly one converted `user_id` column, no measures and zero migrated
visuals because evidence/context is missing or unsupported, with 24 issues. Four local
report-structure checks and a static openability check passed. To repeat those backend checks on
this output:

```powershell
@'
import os
from pathlib import Path
from powerbi_import import openability, schema_validator

out = Path(os.environ["LOOKER_EXAMPLE_OUT"]) / "review"
results = schema_validator.validate_report_dir(str(out / "LookerMigration.Report" / "definition"))
print("Static report checks:", len(results), "passed:", all(result.ok for result in results))
assert len(results) == 4 and all(result.ok for result in results)
result = openability.check_openability(str(out))
print("Static openability:", result.openable, "refresh:", result.to_dict()["refresh_verification"])
assert result.openable and result.to_dict()["refresh_verification"] == "not_run"
'@ | python -
if ($LASTEXITCODE -ne 0) { throw "Offline backend checks failed" }
```

Inspect `review/looker-powerbi-review.json` and the assessment output. Source binding is disabled;
all generated partitions intentionally fail refresh. Runtime and parity are `not_run`, and security
is `not_migrated_unverified`. Static openability does **not** establish opening in Power BI
Desktop, runtime, refresh, deployed security, or data or visual parity. Raw LookML parsing,
missing dependencies, joins, filters, security, full visual conversion and live discovery remain
open; see the [roadmap](../../docs/ROADMAP.md#follow-on--looker-to-power-bi-bounded-offline-slice-implemented).
