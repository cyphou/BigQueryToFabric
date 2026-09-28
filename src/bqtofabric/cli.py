"""Read-only BigQuery discovery, migration assessment, and dry-run Fabric planning."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from enum import IntEnum
from pathlib import Path

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
from .inventory import JsonInventoryProvider
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
    for command in ("plan", "generate"):
        child = subparsers.add_parser(command)
        child.add_argument("inventory", type=Path)
        child.add_argument("--output", "-o", type=Path, required=True)
        child.add_argument("--decisions", type=Path, default=None)
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
