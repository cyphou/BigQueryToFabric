"""Offline parity evidence evaluation for canonical inventory objects."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

PARITY_STATUSES = {"passed", "failed", "not_run", "not_applicable"}


def compare_row_count(source: int | None, target: int | None) -> dict[str, Any]:
    """Compare supplied row counts without querying either data platform."""
    if source is None or target is None:
        return {"status": "not_run", "source": source, "target": target}
    return {
        "status": "passed" if source == target else "failed",
        "source": source,
        "target": target,
    }


def compare_schema(
    source: list[Mapping[str, Any]], target: list[Mapping[str, Any]]
) -> dict[str, Any]:
    """Compare portable column metadata without querying either cloud."""
    differences: list[dict[str, Any]] = []
    _compare_columns(source, target, differences)
    return {
        "status": "passed" if not differences else "failed",
        "source": {"fields": len(source)},
        "target": {"fields": len(target)},
        "differences": differences,
    }


def _compare_columns(
    source: list[Mapping[str, Any]],
    target: list[Mapping[str, Any]],
    differences: list[dict[str, Any]],
    prefix: str = "",
) -> None:
    source_by_name = {str(column.get("name")): column for column in source}
    target_by_name = {str(column.get("name")): column for column in target}
    for name in sorted(set(source_by_name) | set(target_by_name)):
        path = f"{prefix}.{name}" if prefix else name
        source_column = source_by_name.get(name)
        target_column = target_by_name.get(name)
        if source_column is None or target_column is None:
            differences.append({"column": path, "reason": "missing_column"})
            continue
        for field in ("data_type", "nullable", "mode"):
            if source_column.get(field) != target_column.get(field):
                differences.append({
                    "column": path,
                    "field": field,
                    "source": source_column.get(field),
                    "target": target_column.get(field),
                })
        source_fields = source_column.get("fields", [])
        target_fields = target_column.get("fields", [])
        if isinstance(source_fields, list) and isinstance(target_fields, list):
            _compare_columns(source_fields, target_fields, differences, path)


def assess_parity(properties: Mapping[str, Any], *, applicable: bool = True) -> dict[str, Any]:
    """Summarize supplied parity checks without claiming checks that were not run."""
    if not applicable:
        return {"status": "not_applicable", "checks": {}}

    supplied = properties.get("parity")
    if not isinstance(supplied, Mapping):
        return {"status": "not_run", "checks": {}}

    checks: dict[str, dict[str, Any]] = {}
    for name in ("schema", "type", "row_count", "checksum", "aggregate", "sample"):
        value = supplied.get(name)
        if not isinstance(value, Mapping):
            checks[name] = {"status": "not_run"}
            continue
        status = str(value.get("status", "not_run"))
        if status not in PARITY_STATUSES:
            status = "not_run"
        checks[name] = {"status": status, **dict(value)}

    statuses = [str(value["status"]) for value in checks.values()]
    if "failed" in statuses:
        overall = "failed"
    elif any(status == "not_run" for status in statuses):
        overall = "not_run"
    elif statuses and all(status == "not_applicable" for status in statuses):
        overall = "not_applicable"
    else:
        overall = "passed"
    return {"status": overall, "checks": checks}
