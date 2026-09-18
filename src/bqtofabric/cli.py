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
from .discovery import DiscoveryError, GoogleCloudInventoryProvider, create_rest_client
from .inventory import JsonInventoryProvider
from .planner import build_plan
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
    discover = subparsers.add_parser("discover")
    discover.add_argument("project")
    discover.add_argument("--output", "-o", type=Path, required=True)
    return parser


def _discover(project_id: str, output: Path) -> int:
    try:
        client = create_rest_client(project_id)
        inventory = GoogleCloudInventoryProvider(project_id, client).load()
    except DiscoveryError as error:
        print(error)
        return ExitCode.DISCOVERY_FAILED
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(inventory.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Discovered {len(inventory.objects())} components into {output}")
    return ExitCode.SUCCESS


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "discover":
        return _discover(args.project, args.output)
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
    else:
        paths = write_reports(
            args.output,
            inventory,
            assessment,
            plan,
            include_fabric_artifacts=args.command == "generate",
        )
        print(f"Generated {len(paths)} files in {args.output}")
    return ExitCode.SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
