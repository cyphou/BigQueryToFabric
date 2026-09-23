"""Offline parity evidence evaluation for canonical inventory objects."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

PARITY_STATUSES = {"passed", "failed", "not_run", "not_applicable"}

# Every check here is recomputed from evidence. A check with no comparator would only
# ever be caller-asserted, so none is listed.
PARITY_CHECKS = (
    "schema",
    "row_count",
    "checksum",
    "aggregate",
    "null_distribution",
    "sample",
    "sql_result",
)


def compare_row_count(source: int | None, target: int | None) -> dict[str, Any]:
    """Compare supplied row counts without querying either data platform."""
    if source is None or target is None:
        return {"status": "not_run", "source": source, "target": target}
    if not _valid_count(source) or not _valid_count(target):
        return {"status": "not_run", "source": source, "target": target}
    return {
        "status": "passed" if source == target else "failed",
        "source": source,
        "target": target,
    }


def compare_aggregates(
    source: Mapping[str, Any] | None,
    target: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compare supplied named aggregate values without querying either platform."""
    if source is None or target is None:
        return {"status": "not_run", "source": source, "target": target}

    differences = []
    for name in sorted(set(source) | set(target)):
        source_value = source.get(name)
        target_value = target.get(name)
        if name not in source or name not in target or source_value != target_value:
            differences.append({
                "metric": name,
                "source": source_value,
                "target": target_value,
            })
    return {
        "status": "passed" if not differences else "failed",
        "source": dict(source),
        "target": dict(target),
        "differences": differences,
    }


def compare_checksums(
    source: Mapping[str, Any] | None,
    target: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compare checksums only when digest algorithm and canonical ordering agree."""
    if source is None or target is None:
        return {"status": "not_run", "source": source, "target": target}

    required = ("algorithm", "ordering", "value")
    if any(source.get(field) is None or target.get(field) is None for field in required):
        return {"status": "not_run", "source": dict(source), "target": dict(target)}

    differences = [
        {"field": field, "source": source[field], "target": target[field]}
        for field in required
        if source[field] != target[field]
    ]
    return {
        "status": "passed" if not differences else "failed",
        "source": dict(source),
        "target": dict(target),
        "differences": differences,
    }


def compare_null_distributions(
    source: Mapping[str, Mapping[str, int]] | None,
    target: Mapping[str, Mapping[str, int]] | None,
) -> dict[str, Any]:
    """Compare supplied per-column null and row counts without querying either platform."""
    if source is None or target is None:
        return {"status": "not_run", "source": source, "target": target}
    if not _has_valid_null_distribution(source) or not _has_valid_null_distribution(target):
        return {"status": "not_run", "source": dict(source), "target": dict(target)}

    differences = []
    for column in sorted(set(source) | set(target)):
        source_counts = source.get(column)
        target_counts = target.get(column)
        if source_counts is None or target_counts is None:
            differences.append({"column": column, "reason": "missing_column"})
            continue
        for field in ("null_count", "row_count"):
            if source_counts[field] != target_counts[field]:
                differences.append({
                    "column": column,
                    "field": field,
                    "source": source_counts[field],
                    "target": target_counts[field],
                })
    return {
        "status": "passed" if not differences else "failed",
        "source": {column: dict(counts) for column, counts in source.items()},
        "target": {column: dict(counts) for column, counts in target.items()},
        "differences": differences,
    }


def _has_valid_null_distribution(distribution: Mapping[str, Mapping[str, int]]) -> bool:
    for counts in distribution.values():
        null_count = counts.get("null_count")
        row_count = counts.get("row_count")
        if (
            not isinstance(null_count, int)
            or isinstance(null_count, bool)
            or not isinstance(row_count, int)
            or isinstance(row_count, bool)
            or null_count < 0
            or row_count < 0
            or null_count > row_count
        ):
            return False
    return True


def compare_samples(
    source: Mapping[str, Any] | None,
    target: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compare supplied sample rows with matching selection method and ordering."""
    if source is None or target is None:
        return {"status": "not_run", "source": source, "target": target}

    required = ("method", "ordering", "rows")
    if (
        any(field not in source or field not in target for field in required)
        or not isinstance(source["rows"], list)
        or not isinstance(target["rows"], list)
    ):
        return {"status": "not_run", "source": dict(source), "target": dict(target)}

    differences = [
        {"field": field, "source": source[field], "target": target[field]}
        for field in ("method", "ordering", "rows")
        if source[field] != target[field]
    ]
    return {
        "status": "passed" if not differences else "failed",
        "source": dict(source),
        "target": dict(target),
        "differences": differences,
    }


def compare_sql_results(
    source: Mapping[str, Any] | None,
    target: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compare supplied results from the same approved SQL parity query."""
    if source is None or target is None:
        return {"status": "not_run", "source": source, "target": target}

    required = ("query_id", "ordering", "rows")
    if (
        any(field not in source or field not in target for field in required)
        or not isinstance(source["rows"], list)
        or not isinstance(target["rows"], list)
    ):
        return {"status": "not_run", "source": dict(source), "target": dict(target)}

    differences = [
        {"field": field, "source": source[field], "target": target[field]}
        for field in required
        if source[field] != target[field]
    ]
    return {
        "status": "passed" if not differences else "failed",
        "source": dict(source),
        "target": dict(target),
        "differences": differences,
    }


def compare_schema(
    source: Sequence[Mapping[str, Any]], target: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Compare portable column metadata without querying either cloud."""
    if not _valid_schema_fields(source) or not _valid_schema_fields(target):
        return {
            "status": "not_run",
            "source": {"fields": len(source)},
            "target": {"fields": len(target)},
            "differences": [],
        }
    differences: list[dict[str, Any]] = []
    _compare_columns(source, target, differences)
    return {
        "status": "passed" if not differences else "failed",
        "source": {"fields": len(source)},
        "target": {"fields": len(target)},
        "differences": differences,
    }


def _valid_count(value: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _valid_schema_fields(fields: Sequence[Mapping[str, Any]]) -> bool:
    names: set[str] = set()
    for column in fields:
        name = column.get("name")
        data_type = column.get("data_type")
        if not isinstance(name, str) or not name or name in names:
            return False
        if not isinstance(data_type, str) or not data_type:
            return False
        names.add(name)
        nested = column.get("fields", [])
        if not isinstance(nested, list) or not _valid_schema_fields(nested):
            return False
    return True


def _compare_columns(
    source: Sequence[Mapping[str, Any]],
    target: Sequence[Mapping[str, Any]],
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


def _evaluate_check(name: str, value: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute a single parity check from its supplied evidence payload."""
    source = value.get("source")
    target = value.get("target")
    if name == "schema":
        if not isinstance(source, Sequence) or not isinstance(target, Sequence):
            return {"status": "not_run"}
        return compare_schema(source, target)
    if name == "row_count":
        source_count = source if isinstance(source, int) else None
        target_count = target if isinstance(target, int) else None
        return compare_row_count(source_count, target_count)
    if name == "checksum":
        return compare_checksums(_as_mapping(source), _as_mapping(target))
    if name == "aggregate":
        return compare_aggregates(_as_mapping(source), _as_mapping(target))
    if name == "null_distribution":
        return compare_null_distributions(_as_mapping(source), _as_mapping(target))
    if name == "sample":
        return compare_samples(_as_mapping(source), _as_mapping(target))
    if name == "sql_result":
        return compare_sql_results(_as_mapping(source), _as_mapping(target))
    return {"status": "not_run"}


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def assess_parity(properties: Mapping[str, Any], *, applicable: bool = True) -> dict[str, Any]:
    """Recompute parity from supplied evidence.

    A caller-declared ``status`` is never trusted: each check is derived from its own
    ``source``/``target`` payload, so an assertion without evidence resolves to
    ``not_run`` rather than ``passed``.
    """
    if not applicable:
        return {"status": "not_applicable", "checks": {}}

    supplied = properties.get("parity")
    if not isinstance(supplied, Mapping):
        return {"status": "not_run", "checks": {}}

    checks: dict[str, dict[str, Any]] = {}
    for name in PARITY_CHECKS:
        value = supplied.get(name)
        if not isinstance(value, Mapping):
            checks[name] = {"status": "not_run"}
            continue
        declared = str(value.get("status", "not_run"))
        if declared == "not_applicable":
            checks[name] = {"status": "not_applicable", **dict(value)}
            continue
        computed = _evaluate_check(name, value)
        merged = {**dict(value), **computed}
        merged["status"] = computed["status"]
        if declared in PARITY_STATUSES and declared != computed["status"]:
            merged["declaredStatus"] = declared
        checks[name] = merged

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
