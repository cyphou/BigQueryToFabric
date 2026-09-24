"""Deterministic, offline repair-and-validate loop."""

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

RepairFunction = Callable[[Any], tuple[Any, bool]]
Validator = Callable[[Any], bool]


@dataclass(frozen=True, slots=True)
class RepairRule:
    """A named deterministic repair that reports whether it changed the value."""

    name: str
    apply: RepairFunction


@dataclass(frozen=True, slots=True)
class RepairResult:
    """Outcome of repair attempts and the final offline validation."""

    value: Any
    status: str
    valid: bool
    applied_rules: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


def repair_pipeline_triggers(value: Any) -> tuple[Any, bool]:
    """Move misplaced pipeline triggers to the resource level without mutating input."""
    if not isinstance(value, dict):
        return value, False
    properties = value.get("properties")
    if not isinstance(properties, dict) or "triggers" not in properties:
        return value, False
    repaired = deepcopy(value)
    repaired["triggers"] = repaired["properties"].pop("triggers")
    return repaired, True


def repair_duplicate_schema_fields(value: Any) -> tuple[Any, bool]:
    """Remove exact duplicate schema fields while preserving conflicting definitions."""
    if not isinstance(value, list):
        return value, False
    repaired: list[Any] = []
    seen: set[str] = set()
    changed = False
    for field in value:
        current = field
        if isinstance(field, dict) and isinstance(field.get("fields"), list):
            nested_fields, nested_changed = repair_duplicate_schema_fields(field["fields"])
            if nested_changed:
                current = dict(field)
                current["fields"] = nested_fields
                changed = True
        if isinstance(current, dict):
            identity = json.dumps(current, sort_keys=True, separators=(",", ":"))
            if identity in seen:
                changed = True
                continue
            seen.add(identity)
        repaired.append(current)
    return (repaired if changed else deepcopy(value)), changed


def repair_and_validate(
    value: Any,
    *,
    rules: tuple[RepairRule, ...] = (),
    validator: Validator,
) -> RepairResult:
    """Apply ordered repairs once, then fail closed if validation still fails."""
    current = deepcopy(value)
    applied: list[str] = []
    for rule in rules:
        current, changed = rule.apply(current)
        if changed:
            applied.append(rule.name)
    try:
        valid = bool(validator(current))
    except Exception as error:  # noqa: BLE001 - a repair gate must fail closed
        return RepairResult(
            value=current,
            status="manual_review",
            valid=False,
            applied_rules=tuple(applied),
            errors=(f"validator error: {type(error).__name__}",),
        )
    return RepairResult(
        value=current,
        status="repaired" if valid and applied else "passed" if valid else "manual_review",
        valid=valid,
        applied_rules=tuple(applied),
        errors=() if valid else ("validation failed after repair",),
    )
