"""Read-only BigQuery discovery, migration assessment, and dry-run Fabric planning."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from enum import IntEnum
from pathlib import Path, PurePosixPath, PureWindowsPath

from .assessment import run_assessment
from .composer_discovery import (
    ComposerInventoryProvider,
    create_composer_rest_client,
    merge_composer_components,
)
from .dataflow_discovery import (
    DataflowInventoryProvider,
    create_dataflow_rest_client,
    merge_dataflow_jobs,
)
from .dataform_discovery import (
    DataformInventoryProvider,
    create_dataform_rest_client,
    merge_dataform_components,
)
from .dataproc_discovery import (
    DataprocInventoryProvider,
    create_dataproc_rest_client,
    merge_dataproc_components,
)
from .deployment_manifest import verify_manifest
from .deployment_readiness import check_deployment_readiness
from .discovery import DiscoveryError, GoogleCloudInventoryProvider, create_rest_client
from .exported_metadata import EXPORT_SERVICES, merge_export
from .generator.looker_powerbi import generate_looker_powerbi_project
from .inventory import JsonInventoryProvider, validate_inventory_document
from .inventory_drift import inventory_drift
from .looker_api_export import normalize_looker_api_export
from .looker_lookml_export import normalize_looker_lookml_export
from .models import BigQueryInventory, ObjectKind
from .parity_pack import build_parity_pack, ingest_parity_results, render_sql
from .planner import apply_wave_decisions, build_plan, load_wave_decisions
from .reporting import write_reports


class ExitCode(IntEnum):
    SUCCESS = 0
    GENERAL_ERROR = 1
    FILE_NOT_FOUND = 2
    DISCOVERY_FAILED = 3
    VALIDATION_FAILED = 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bqtofabric", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("inventory", "assess", "map", "validate"):
        child = subparsers.add_parser(command)
        child.add_argument("inventory", type=Path)
    drift = subparsers.add_parser(
        "inventory-drift",
        help="Compare two canonical inventories offline",
        description="Report component drift between two canonical inventories; no cloud calls.",
    )
    drift.add_argument("baseline", type=Path, help="Baseline canonical inventory JSON")
    drift.add_argument("current", type=Path, help="Current canonical inventory JSON")
    for command in ("plan", "generate"):
        child = subparsers.add_parser(command)
        child.add_argument("inventory", type=Path)
        child.add_argument("--output", "-o", type=Path, required=True)
        child.add_argument("--decisions", type=Path, default=None)
    looker = subparsers.add_parser(
        "generate-looker-powerbi",
        help="Generate one offline, review-only Power BI project from a Looker asset",
        description=(
            "Generate a review-only Power BI project using the externally installed "
            "TableauToPowerBI 44.0.0 packages. No cloud calls or deployment are performed."
        ),
    )
    looker.add_argument("inventory", type=Path, help="Offline canonical inventory JSON")
    looker.add_argument(
        "--asset", required=True, help="Exact Looker source_id, or an unambiguous exact name"
    )
    looker.add_argument(
        "--output", "-o", type=Path, required=True,
        help="New or empty output directory; existing files are never overwritten",
    )
    looker.add_argument("--project-name", default="LookerMigration", help="Safe project identifier")
    looker_import = subparsers.add_parser(
        "import-looker-api",
        help="Import saved Looker API responses into a new offline inventory",
        description="Normalize saved Looker API JSON without cloud calls or overwriting files.",
    )
    looker_import.add_argument("inventory", type=Path, help="Canonical inventory JSON")
    looker_import.add_argument("--payload", type=Path, required=True, help="Saved API response JSON")
    looker_import.add_argument("--output", "-o", type=Path, required=True, help="New inventory file")
    lookml_import = subparsers.add_parser(
        "import-looker-lookml",
        help="Import a saved LookML metadata export into a new offline inventory",
        description="Normalize a versioned LookML JSON export without cloud calls or overwriting files.",
    )
    lookml_import.add_argument("inventory", type=Path, help="Canonical inventory JSON")
    lookml_import.add_argument("--payload", type=Path, required=True, help="Versioned LookML export JSON")
    lookml_import.add_argument("--output", "-o", type=Path, required=True, help="New inventory file")
    discover = subparsers.add_parser("discover")
    discover.add_argument("project")
    discover.add_argument("--output", "-o", type=Path, required=True)
    discover.add_argument("--dataflow-region", action="append", default=[])
    discover.add_argument("--dataproc-region", action="append", default=[])
    discover.add_argument("--dataform", action="store_true", default=False)
    discover.add_argument("--dataform-location", default="us-central1")
    discover.add_argument("--composer-region", action="append", default=[])
    manifest = subparsers.add_parser("manifest-verify")
    manifest.add_argument("manifest", type=Path)
    readiness = subparsers.add_parser("deployment-check")
    readiness.add_argument("artifacts", type=Path)
    pack = subparsers.add_parser("parity-pack")
    pack.add_argument("inventory", type=Path)
    pack.add_argument("--output", "-o", type=Path, required=True)
    ingest = subparsers.add_parser("parity-ingest")
    ingest.add_argument("inventory", type=Path)
    ingest.add_argument("--pack", type=Path, required=True)
    ingest.add_argument("--results", type=Path, required=True)
    ingest.add_argument("--output", "-o", type=Path, required=True)
    export = subparsers.add_parser("import-export")
    export.add_argument("inventory", type=Path)
    export.add_argument("--service", choices=EXPORT_SERVICES, required=True)
    export.add_argument("--payload", type=Path, required=True)
    export.add_argument("--output", "-o", type=Path, required=True)
    return parser


_LOOKER_REVIEW_FILE = "looker-powerbi-review.json"
_WINDOWS_DEVICE = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$", re.IGNORECASE)
_INGESTION_PATH = re.compile(
    r"(?:explores|dashboards)(?:\[(?:0|[1-9][0-9]*)\])?"
    r"(?:\.fields(?:\.(?:dimensions|measures)\[(?:0|[1-9][0-9]*)\])?"
    r"|\.elements\[(?:0|[1-9][0-9]*)\])?"
)
# The extractor emits only fixed diagnostic codes and index-only paths. Do not
# trust an arbitrary inventory label to be an unmodified extractor result.
_INGESTION_CODES = frozenset({
    "no_explore_responses", "no_dashboard_responses", "expected_object",
    "invalid_or_ambiguous_identity", "fields_missing_or_invalid",
    "source_table_missing_or_unsupported", "joined_or_invalid_field",
    "field_security_not_migrated", "unsupported_type_or_sql", "field_semantics_missing",
    "field_semantics_not_migrated", "additional_field_metadata_not_migrated",
    "explore_and_security_not_fully_represented", "invalid_dashboard",
    "dashboard_filters_missing_or_not_migrated", "dashboard_elements_missing_or_invalid",
    "invalid_element", "linked_look_not_migrated", "element_context_not_migrated",
    "query_missing_or_invalid",
    "unresolved_query_fields", "query_filter_evidence_missing_or_invalid",
    "query_semantics_evidence_missing_or_invalid", "unknown_query_property",
    "unknown_explore_property",
    "query_semantics_not_migrated", "query_limit_not_migrated",
    "visual_configuration_not_migrated", "visual_type_missing_or_unsupported",
    "element_layout_and_metadata_not_migrated", "dashboard_layout_and_metadata_not_migrated",
} | {
    f"{key}_{suffix}"
    for key in ("joins", "always_join", "access_filters", "access_filter_fields",
                "always_filter", "conditionally_filter", "filters", "parameters")
    for suffix in ("missing_or_invalid", "not_migrated")
} | {
    f"{key}_not_migrated"
    for key in ("sql_always_where", "access_grants", "required_access_grants",
                "sql_always_having", "errors")
} | {
    f"{key}_missing_or_invalid"
    for key in ("sql_always_where", "access_grants", "required_access_grants")
} | {"dimensions_missing_or_invalid", "measures_missing_or_invalid"})


def _looker_ingestion_diagnostics(labels: dict[str, str]) -> list[dict[str, str]] | None:
    if "looker_ingestion_report" not in labels:
        return None
    raw = labels["looker_ingestion_report"]
    if not isinstance(raw, str):
        raise TypeError("Invalid ingestion report")
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise TypeError("Invalid ingestion report")
    result = []
    for item in parsed:
        if (not isinstance(item, dict) or set(item) != {"path", "code"}
                or not isinstance(item["path"], str)
                or not _INGESTION_PATH.fullmatch(item["path"])
                or not isinstance(item["code"], str) or item["code"] not in _INGESTION_CODES):
            raise ValueError("Invalid ingestion report")
        result.append({"path": item["path"], "code": item["code"]})
    return result


def _import_looker_api(inventory_path: Path, payload_path: Path, output: Path) -> int:
    try:
        document = json.loads(inventory_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise TypeError("Invalid inventory")
        validate_inventory_document(document)
        inventory = BigQueryInventory.from_dict(document)
    except FileNotFoundError:
        print("Inventory file not found")
        return ExitCode.FILE_NOT_FOUND
    except (KeyError, TypeError, ValueError, UnicodeError):
        print("Invalid inventory: expected a canonical JSON inventory")
        return ExitCode.VALIDATION_FAILED
    except OSError:
        print("Could not read inventory: I/O error")
        return ExitCode.GENERAL_ERROR
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        asset = normalize_looker_api_export(inventory.project_id, payload)
    except FileNotFoundError:
        print("Looker API payload file not found")
        return ExitCode.FILE_NOT_FOUND
    except (TypeError, ValueError, UnicodeError):
        print("Invalid Looker API payload or project identifier")
        return ExitCode.VALIDATION_FAILED
    except OSError:
        print("Could not read Looker API payload: I/O error")
        return ExitCode.GENERAL_ERROR
    if any(item.source_id == asset.source_id for item in inventory.objects()):
        print("Inventory already contains the Looker API asset source_id")
        return ExitCode.VALIDATION_FAILED
    document.setdefault("components", []).append(asdict(asset))
    try:
        data = (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True,
                           allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        print("Invalid inventory or normalized Looker API output")
        return ExitCode.VALIDATION_FAILED
    created = False
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            created = True
            stream.write(data)
    except FileExistsError:
        print("Output already exists; no files were overwritten")
        return ExitCode.VALIDATION_FAILED
    except OSError:
        if created:
            output.unlink(missing_ok=True)
        print("Could not write imported inventory: I/O error")
        return ExitCode.GENERAL_ERROR
    print("Imported one Looker API asset into a new offline inventory")
    return ExitCode.SUCCESS


def _import_looker_lookml(inventory_path: Path, payload_path: Path, output: Path) -> int:
    try:
        document = json.loads(inventory_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise TypeError("Invalid inventory")
        validate_inventory_document(document)
        inventory = BigQueryInventory.from_dict(document)
    except FileNotFoundError:
        print("Inventory file not found")
        return ExitCode.FILE_NOT_FOUND
    except (KeyError, TypeError, ValueError, UnicodeError):
        print("Invalid inventory: expected a canonical JSON inventory")
        return ExitCode.VALIDATION_FAILED
    except OSError:
        print("Could not read inventory: I/O error")
        return ExitCode.GENERAL_ERROR
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("project_id") != inventory.project_id:
            raise ValueError("LookML export project_id does not match inventory")
        asset = normalize_looker_lookml_export(payload)
    except FileNotFoundError:
        print("Looker LookML payload file not found")
        return ExitCode.FILE_NOT_FOUND
    except (TypeError, ValueError, UnicodeError):
        print("Invalid Looker LookML payload or project identifier")
        return ExitCode.VALIDATION_FAILED
    except OSError:
        print("Could not read Looker LookML payload: I/O error")
        return ExitCode.GENERAL_ERROR
    if any(item.source_id == asset.source_id for item in inventory.objects()):
        print("Inventory already contains the Looker LookML asset source_id")
        return ExitCode.VALIDATION_FAILED
    document.setdefault("components", []).append(asdict(asset))
    try:
        data = (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True,
                           allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        print("Invalid inventory or normalized Looker LookML output")
        return ExitCode.VALIDATION_FAILED
    created = False
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            created = True
            stream.write(data)
    except FileExistsError:
        print("Output already exists; no files were overwritten")
        return ExitCode.VALIDATION_FAILED
    except OSError:
        if created:
            output.unlink(missing_ok=True)
        print("Could not write imported inventory: I/O error")
        return ExitCode.GENERAL_ERROR
    print("Imported one Looker LookML asset into a new offline inventory")
    return ExitCode.SUCCESS


def _looker_output_files(files: dict[str, str], review: object) -> dict[str, bytes]:
    """Validate all paths and encode all content before touching the output."""
    if not isinstance(files, dict):
        raise TypeError("Generator files must be a mapping")
    contents: dict[str, bytes] = {}
    seen: set[tuple[str, ...]] = set()
    all_files = list(files.items()) + [(
        _LOOKER_REVIEW_FILE,
        json.dumps(review, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n",
    )]
    for path, text in all_files:
        if not isinstance(path, str) or not path or not isinstance(text, str):
            raise ValueError("Generator paths and file contents must be strings")
        parts = path.split("/")
        if (PurePosixPath(path).is_absolute() or PureWindowsPath(path).drive
                or any(not part or part in {".", ".."} or part.endswith((" ", "."))
                       or _WINDOWS_DEVICE.fullmatch(part)
                       or any(ord(char) < 32 or char in '\\:*?"<>|' for char in part)
                       for part in parts)):
            raise ValueError(f"Unsafe generator path: {path!r}")
        folded = tuple(part.casefold() for part in parts)
        if any(folded[:len(existing)] == existing or existing[:len(folded)] == folded
               for existing in seen):
            raise ValueError(f"Conflicting generator path: {path!r}")
        seen.add(folded)
        contents[path] = text.encode("utf-8")
    return dict(sorted(contents.items()))


def _write_looker_files(output: Path, contents: dict[str, bytes]) -> None:
    # An empty root prevents existing links or files from being traversed or replaced.
    # Exclusive file creation also rejects an unexpectedly occupied destination.
    if output.is_symlink() or output.is_junction():
        raise ValueError("Output directory must not be a symlink or junction")
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise ValueError("Output directory must be new or empty")
    else:
        output.mkdir(parents=True)
    created_files: list[Path] = []
    created_dirs: list[Path] = []
    try:
        for relative, content in contents.items():
            parts = relative.split("/")
            directory = output
            for part in parts[:-1]:
                directory = directory / part
                if directory.is_symlink() or directory.is_junction():
                    raise ValueError("Output contains a symlink or junction")
                if not directory.exists():
                    directory.mkdir()
                    created_dirs.append(directory)
                elif not directory.is_dir():
                    raise ValueError("Output path conflicts with a file")
            target = directory / parts[-1]
            with target.open("xb") as stream:
                created_files.append(target)
                stream.write(content)
    except (OSError, ValueError):
        for target in reversed(created_files):
            target.unlink(missing_ok=True)
        for directory in reversed(created_dirs):
            directory.rmdir()
        raise


def _generate_looker_powerbi(
    inventory_path: Path, selector: str, output: Path, project_name: str
) -> int:
    try:
        inventory = JsonInventoryProvider(inventory_path).load()
    except FileNotFoundError:
        print("Inventory file not found")
        return ExitCode.FILE_NOT_FOUND
    except (KeyError, TypeError, ValueError, UnicodeError):
        print("Invalid inventory: expected a canonical JSON inventory")
        return ExitCode.VALIDATION_FAILED
    except OSError:
        print("Could not read inventory: I/O error")
        return ExitCode.GENERAL_ERROR

    assets = [item for item in inventory.objects() if item.kind is ObjectKind.LOOKER_ASSET]
    matches = [item for item in assets if item.source_id == selector]
    if not matches:
        matches = [item for item in assets if item.name == selector]
    if len(matches) != 1:
        print("Looker asset not found" if not matches else
              "Ambiguous Looker asset name; select an exact source_id")
        return ExitCode.VALIDATION_FAILED
    try:
        diagnostics = _looker_ingestion_diagnostics(matches[0].labels)
    except (TypeError, ValueError):
        print("Invalid Looker ingestion diagnostics in inventory")
        return ExitCode.VALIDATION_FAILED
    try:
        project = generate_looker_powerbi_project(matches[0], project_name=project_name)
    except (TypeError, ValueError):
        print("Invalid Looker project: asset or project_name is invalid")
        return ExitCode.VALIDATION_FAILED
    except RuntimeError as error:
        if isinstance(error.__cause__, (ImportError, AttributeError)):
            print("Looker project generation requires compatible TableauToPowerBI 44.0.0 "
                  "powerbi_import and tableau_export packages on PYTHONPATH")
        else:
            print("Looker project generation failed: backend runtime error")
        return ExitCode.GENERAL_ERROR
    except OSError:
        print("Looker project generation failed: backend I/O error")
        return ExitCode.GENERAL_ERROR
    try:
        review = dict(project.review)
        if diagnostics is not None:
            review["ingestion_diagnostics"] = diagnostics
        contents = _looker_output_files(project.files, review)
        _write_looker_files(output, contents)
    except (TypeError, ValueError, UnicodeError):
        print("Invalid Looker project output: unsafe paths, content, or output directory")
        return ExitCode.VALIDATION_FAILED
    except OSError:
        print("Could not write Looker project: I/O error")
        return ExitCode.GENERAL_ERROR
    if not project.files:
        print("No project generated; review findings were saved")
        return ExitCode.VALIDATION_FAILED
    print(f"Generated {len(contents)} review files in {output}; runtime and parity not verified")
    return ExitCode.SUCCESS


def _inventory_drift(baseline_path: Path, current_path: Path) -> int:
    inventories: list[BigQueryInventory] = []
    for label, path in (("Baseline", baseline_path), ("Current", current_path)):
        try:
            inventories.append(JsonInventoryProvider(path).load())
        except FileNotFoundError:
            print(f"{label} inventory file not found")
            return ExitCode.FILE_NOT_FOUND
        except (KeyError, TypeError, ValueError, UnicodeError):
            print(f"Invalid {label.lower()} inventory: expected a canonical JSON inventory")
            return ExitCode.VALIDATION_FAILED
        except OSError:
            print(f"Could not read {label.lower()} inventory: I/O error")
            return ExitCode.GENERAL_ERROR

    report = inventory_drift(inventories[0], inventories[1])
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False))
    return ExitCode.SUCCESS


def _discover(
    project_id: str,
    output: Path,
    dataflow_regions: Sequence[str],
    dataproc_regions: Sequence[str],
    dataform_enabled: bool,
    dataform_location: str,
    composer_regions: Sequence[str],
) -> int:
    try:
        client = create_rest_client(project_id)
        inventory = GoogleCloudInventoryProvider(project_id, client).load()
        if dataflow_regions:
            dataflow_client = create_dataflow_rest_client(project_id)
            jobs = DataflowInventoryProvider(project_id, dataflow_client).load(dataflow_regions)
            inventory = merge_dataflow_jobs(inventory, jobs)
        if dataproc_regions:
            dataproc_client = create_dataproc_rest_client(project_id)
            components = DataprocInventoryProvider(project_id, dataproc_client).load(dataproc_regions)
            inventory = merge_dataproc_components(inventory, components)
        if dataform_enabled:
            dataform_client = create_dataform_rest_client(project_id, dataform_location)
            components = DataformInventoryProvider(project_id, dataform_client, dataform_location).load()
            inventory = merge_dataform_components(inventory, components)
        if composer_regions:
            composer_client = create_composer_rest_client(project_id)
            components = ComposerInventoryProvider(project_id, composer_client).load(composer_regions)
            inventory = merge_composer_components(inventory, components)
    except DiscoveryError as error:
        print(error)
        return ExitCode.DISCOVERY_FAILED
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(inventory.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Discovered {len(inventory.objects())} components into {output}")
    return ExitCode.SUCCESS


def _parity_ingest(inventory_path: Path, pack_path: Path, results_path: Path, output: Path) -> int:
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
        results = json.loads(results_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        print(error)
        return ExitCode.FILE_NOT_FOUND
    except json.JSONDecodeError as error:
        print(f"Invalid JSON: {error}")
        return ExitCode.VALIDATION_FAILED
    updated, errors = ingest_parity_results(inventory, pack, results)
    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        return ExitCode.VALIDATION_FAILED
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote parity evidence into {output}; run assess to recompute status")
    return ExitCode.SUCCESS


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "import-looker-api":
        return _import_looker_api(args.inventory, args.payload, args.output)
    if args.command == "import-looker-lookml":
        return _import_looker_lookml(args.inventory, args.payload, args.output)
    if args.command == "generate-looker-powerbi":
        return _generate_looker_powerbi(args.inventory, args.asset, args.output, args.project_name)
    if args.command == "inventory-drift":
        return _inventory_drift(args.baseline, args.current)
    if args.command == "parity-ingest":
        return _parity_ingest(args.inventory, args.pack, args.results, args.output)
    if args.command == "import-export":
        try:
            inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
            payload = json.loads(args.payload.read_text(encoding="utf-8"))
            merged = merge_export(inventory, args.service, payload)
        except FileNotFoundError as error:
            print(error)
            return ExitCode.FILE_NOT_FOUND
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            print(f"Invalid export: {error}")
            return ExitCode.VALIDATION_FAILED
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Merged {args.service} export into {args.output}")
        return ExitCode.SUCCESS
    if args.command == "discover":
        return _discover(
            args.project,
            args.output,
            args.dataflow_region,
            args.dataproc_region,
            args.dataform,
            args.dataform_location,
            args.composer_region,
        )
    if args.command == "manifest-verify":
        try:
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as error:
            print(f"Invalid manifest: {error}")
            return ExitCode.VALIDATION_FAILED
        valid = verify_manifest(manifest)
        print("PASS: manifest integrity verified" if valid else "FAIL: manifest integrity mismatch")
        return ExitCode.SUCCESS if valid else ExitCode.VALIDATION_FAILED
    if args.command == "deployment-check":
        result = check_deployment_readiness(args.artifacts)
        print(json.dumps(result, indent=2, sort_keys=True))
        return ExitCode.SUCCESS if result["status"] == "ready_for_review" else ExitCode.VALIDATION_FAILED
    try:
        inventory = JsonInventoryProvider(args.inventory).load()
        assessment = run_assessment(inventory)
        plan = build_plan(inventory, assessment)
    except FileNotFoundError as error:
        print(error)
        return ExitCode.FILE_NOT_FOUND
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"Invalid inventory: {error}")
        return ExitCode.VALIDATION_FAILED

    if args.command == "inventory":
        print(json.dumps({
            "project_id": inventory.project_id,
            "datasets": len(inventory.datasets),
            "objects": len(inventory.objects()),
            "components_by_kind": dict(sorted(
                Counter(item.kind.value for item in inventory.objects()).items()
            )),
        }, sort_keys=True))
    elif args.command == "assess":
        print(json.dumps(asdict(assessment), indent=2, sort_keys=True))
    elif args.command == "map":
        print(json.dumps([asdict(item) for item in assessment.decisions], indent=2, sort_keys=True))
    elif args.command == "validate":
        print(f"PASS: {inventory.project_id} ({len(inventory.objects())} objects)")
    elif args.command == "parity-pack":
        pack = build_parity_pack(inventory, assessment)
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "parity-pack.json").write_text(
            json.dumps(pack, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        for side in ("source", "target"):
            (args.output / f"parity-{side}.sql").write_text(render_sql(pack, side), encoding="utf-8")
        print(f"Generated {len(pack['checks'])} parity queries ({pack['pack_id']}) in {args.output}")
    else:
        decisions = ()
        if args.decisions is not None:
            try:
                raw = json.loads(args.decisions.read_text(encoding="utf-8"))
            except FileNotFoundError as error:
                print(error)
                return ExitCode.FILE_NOT_FOUND
            except json.JSONDecodeError as error:
                print(f"Invalid decisions: {error}")
                return ExitCode.VALIDATION_FAILED
            decisions, errors = load_wave_decisions(raw if isinstance(raw, dict) else {})
            if not errors:
                plan, errors = apply_wave_decisions(plan, decisions)
            if errors:
                for error in errors:
                    print(f"FAIL: {error}")
                return ExitCode.VALIDATION_FAILED
        paths = write_reports(
            args.output,
            inventory,
            assessment,
            plan,
            include_fabric_artifacts=args.command == "generate",
            decisions=decisions,
        )
        print(f"Generated {len(paths)} files in {args.output}")
    return ExitCode.SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
