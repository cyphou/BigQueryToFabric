"""Validate, record, and query agent review verdicts using only the standard library."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / ".github" / "review-verdict.schema.json"
DEFAULT_LEDGER = ROOT / "artifacts" / "review-ledger.jsonl"
RECURRENCE_THRESHOLD = 2
_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "integer": (int,),
    "boolean": (bool,),
}


def load_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def check_verdict(verdict: Any, schema: dict[str, Any] | None = None) -> list[str]:
    """Return schema violations; an empty list means the verdict conforms."""
    root = schema if schema is not None else load_schema()
    return _check(verdict, root, root, "$")


def _check(value: Any, rule: dict[str, Any], root: dict[str, Any], at: str) -> list[str]:
    if "$ref" in rule:
        target: Any = root
        for part in rule["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        return _check(value, target, root, at)

    errors: list[str] = []
    expected = rule.get("type")
    # bool is an int subclass; an integer field must not accept True.
    if expected is not None and (
        not isinstance(value, _TYPES[expected])
        or (expected == "integer" and isinstance(value, bool))
    ):
        return [f"{at}: expected {expected}"]
    if "const" in rule and value != rule["const"]:
        errors.append(f"{at}: must be {rule['const']!r}")
    if "enum" in rule and value not in rule["enum"]:
        errors.append(f"{at}: must be one of {rule['enum']}")
    if isinstance(value, str):
        if len(value) < rule.get("minLength", 0):
            errors.append(f"{at}: shorter than {rule['minLength']}")
        if "pattern" in rule and not re.search(rule["pattern"], value):
            errors.append(f"{at}: does not match {rule['pattern']}")
    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in rule and value < rule["minimum"]:
            errors.append(f"{at}: below {rule['minimum']}")
        if "maximum" in rule and value > rule["maximum"]:
            errors.append(f"{at}: above {rule['maximum']}")
    if isinstance(value, dict):
        properties = rule.get("properties", {})
        errors.extend(f"{at}: missing {key}" for key in rule.get("required", []) if key not in value)
        if rule.get("additionalProperties") is False:
            errors.extend(f"{at}: unexpected {key}" for key in value if key not in properties)
        for key, sub in properties.items():
            if key in value:
                errors.extend(_check(value[key], sub, root, f"{at}.{key}"))
    if isinstance(value, list):
        if len(value) < rule.get("minItems", 0):
            errors.append(f"{at}: needs at least {rule['minItems']} items")
        if "items" in rule:
            for index, item in enumerate(value):
                errors.extend(_check(item, rule["items"], root, f"{at}[{index}]"))
        if "contains" in rule and not any(
            not _check(item, rule["contains"], root, at) for item in value
        ):
            errors.append(f"{at}: no item matches the required condition")
    for sub in rule.get("allOf", []):
        errors.extend(_check(value, sub, root, at))
    if "if" in rule and not _check(value, rule["if"], root, at) and "then" in rule:
        errors.extend(_check(value, rule["then"], root, at))
    return errors


def read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def check_sequence(ledger: list[dict[str, Any]], verdict: dict[str, Any]) -> list[str]:
    """Rounds are counted per slice and reviewer; a closed thread accepts no more verdicts."""
    previous = [
        entry
        for entry in ledger
        if entry["slice"] == verdict["slice"] and entry["reviewer"] == verdict["reviewer"]
    ]
    if not previous:
        return [] if verdict["round"] == 1 else ["first verdict for this slice must be round 1"]
    last = previous[-1]
    if last["verdict"] != "changes_requested":
        return [f"thread already closed with {last['verdict']}; open a new slice"]
    if verdict["round"] != last["round"] + 1:
        return [f"expected round {last['round'] + 1}, got {verdict['round']}"]
    if verdict["owner"] != last["owner"]:
        return [f"owner changed from {last['owner']} to {verdict['owner']} without escalation"]
    return []


def record(path: Path, verdict: dict[str, Any]) -> list[str]:
    """Append a verdict only if it conforms to the schema and continues its thread."""
    errors = check_verdict(verdict)
    if errors:
        return errors
    errors = check_sequence(read_ledger(path), verdict)
    if errors:
        return errors
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(verdict, sort_keys=True, separators=(",", ":")) + "\n")
    return []


def recurring(ledger: list[dict[str, Any]], threshold: int = RECURRENCE_THRESHOLD) -> dict[str, list[str]]:
    """Blocking finding codes and failure modes seen on at least ``threshold`` distinct slices."""
    slices: dict[str, set[str]] = defaultdict(set)
    for entry in ledger:
        for finding in entry.get("findings", []):
            if not finding.get("blocking"):
                continue
            slices[finding["code"]].add(entry["slice"])
            if finding.get("failure_mode"):
                slices[f"failure_mode:{finding['failure_mode']}"].add(entry["slice"])
    return {key: sorted(found) for key, found in sorted(slices.items()) if len(found) >= threshold}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="validate a verdict file against the schema")
    check.add_argument("verdict", type=Path)
    add = commands.add_parser("record", help="validate and append a verdict to the ledger")
    add.add_argument("verdict", type=Path)
    add.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    recur = commands.add_parser("recurring", help="list findings that recur across slices")
    recur.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    args = parser.parse_args(argv)

    if args.command == "recurring":
        print(json.dumps(recurring(read_ledger(args.ledger)), indent=2))
        return 0
    verdict = json.loads(args.verdict.read_text(encoding="utf-8"))
    errors = check_verdict(verdict) if args.command == "check" else record(args.ledger, verdict)
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
