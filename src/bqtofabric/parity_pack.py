"""Offline parity execution kit: paired source/target queries and results ingestion.

The pack only generates SQL; nothing here connects to BigQuery or Fabric. Status is
never written: ingested payloads are handed to ``parity.assess_parity``, which
recomputes every check.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any

from .assessment import AssessmentReport
from .mapping import FabricTarget
from .models import BigQueryInventory, BigQueryObject, Column

PACK_SCHEMA_VERSION = "1.0"
PACK_PROVENANCE = "parity_pack"
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAFE_PROJECT = re.compile(r"^[a-z][a-z0-9\-]{4,28}[a-z0-9]$")
_TSQL_TARGETS = {FabricTarget.WAREHOUSE, FabricTarget.SQL_DATABASE}
_AGGREGATE_TYPES = {"INT64", "INTEGER", "NUMERIC", "BIGNUMERIC", "DECIMAL", "BIGDECIMAL"}
_DATA_BEARING = {"table", "external_table", "materialized_view", "view"}
NOT_GENERATED = {
    "schema": "Compared from inventory columns and generated DDL; engine type names differ.",
    "checksum": "No digest function is portable between BigQuery and Fabric.",
    "sample": "Requires an approved selection method and deterministic ordering.",
    "sql_result": "Requires an approved business query per component.",
}


def build_parity_pack(inventory: BigQueryInventory, assessment: AssessmentReport) -> dict[str, Any]:
    """Build deterministic row_count, null_distribution, and aggregate queries per component."""
    targets = {decision.source_id: decision.target for decision in assessment.decisions}
    checks: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for item in sorted(inventory.objects(), key=lambda value: value.source_id):
        if item.kind.value not in _DATA_BEARING:
            continue
        reason = _unsafe_reason(item)
        if reason:
            skipped.append({"source_id": item.source_id, "reason": reason})
            continue
        target = targets.get(item.source_id, FabricTarget.LAKEHOUSE)
        checks.extend(_checks_for(item, target))
    pack: dict[str, Any] = {
        "schema_version": PACK_SCHEMA_VERSION,
        "project_id": inventory.project_id,
        "checks": checks,
        "skipped": skipped,
        "not_generated": NOT_GENERATED,
    }
    pack["pack_id"] = _pack_id(pack)
    return pack


def render_sql(pack: dict[str, Any], side: str) -> str:
    """Render one side of the pack as a runnable script with query IDs as comments."""
    key = "source_sql" if side == "source" else "target_sql"
    lines = [f"-- BQToFabric parity pack {pack['pack_id']} ({side})\n"]
    for check in pack["checks"]:
        lines.append(f"\n-- query_id: {check['query_id']}\n{check[key]};\n")
    return "".join(lines)


def ingest_parity_results(
    inventory: dict[str, Any], pack: dict[str, Any], results: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Attach supplied results as parity evidence; a missing side leaves the check not_run."""
    if _pack_id({key: value for key, value in pack.items() if key != "pack_id"}) != pack.get(
        "pack_id"
    ):
        return inventory, ["pack was modified after generation"]
    if results.get("pack_id") != pack["pack_id"]:
        return inventory, [f"results reference pack {results.get('pack_id')!r}, not {pack['pack_id']!r}"]

    by_query = {check["query_id"]: check for check in pack["checks"]}
    updated = deepcopy(inventory)
    objects = {
        str(item["source_id"]): item
        for item in [
            *(obj for dataset in updated.get("datasets", []) for obj in dataset.get("objects", [])),
            *updated.get("components", []),
        ]
    }
    errors: list[str] = []
    for result in results.get("results", []):
        query_id = result.get("query_id")
        check = by_query.get(query_id)
        if check is None:
            errors.append(f"{query_id}: not in pack")
            continue
        target_object = objects.get(check["source_id"])
        if target_object is None:
            errors.append(f"{query_id}: {check['source_id']} not in inventory")
            continue
        source = _payload(check, result.get("source"))
        target = _payload(check, result.get("target"))
        if source is None or target is None:
            continue
        parity = target_object.setdefault("properties", {}).setdefault("parity", {})
        evidence = {
            "source": source,
            "target": target,
            "provenance": PACK_PROVENANCE,
            "query_id": query_id,
            "pack_id": pack["pack_id"],
        }
        if result.get("collected_at"):
            evidence["collected_at"] = str(result["collected_at"])
        parity[check["check"]] = evidence
    return updated, errors


def _checks_for(item: BigQueryObject, target: FabricTarget) -> list[dict[str, Any]]:
    dialect = "tsql" if target in _TSQL_TARGETS else "spark_sql"
    source_table = f"`{item.source_id}`"
    schema = item.dataset or item.source_id.split(".")[1]
    target_table = f"[{schema}].[{item.name}]" if dialect == "tsql" else f"`{schema}`.`{item.name}`"
    base = {
        "source_id": item.source_id,
        "target": target.value,
        "target_dialect": dialect,
        "target_object": target_table,
    }
    checks = [{
        **base,
        "query_id": f"{item.source_id}:row_count",
        "check": "row_count",
        "source_sql": f"SELECT COUNT(*) AS row_count FROM {source_table}",
        "target_sql": f"SELECT {_count(dialect)} AS row_count FROM {target_table}",
        "columns": {},
    }]

    flat = [column for column in item.columns if _is_flat(column)]
    if flat:
        aliases = {f"n{index}": column.name for index, column in enumerate(flat)}
        checks.append({
            **base,
            "query_id": f"{item.source_id}:null_distribution",
            "check": "null_distribution",
            "source_sql": _select(
                "COUNT(*) AS row_count",
                [f"COUNTIF(`{name}` IS NULL) AS {alias}" for alias, name in aliases.items()],
                source_table,
            ),
            "target_sql": _select(
                f"{_count(dialect)} AS row_count",
                [
                    f"SUM(CASE WHEN {_quote(name, dialect)} IS NULL THEN 1 ELSE 0 END) AS {alias}"
                    for alias, name in aliases.items()
                ],
                target_table,
            ),
            "columns": aliases,
        })

    numeric = [column for column in flat if column.data_type in _AGGREGATE_TYPES]
    if numeric:
        aliases = {}
        source_terms: list[str] = []
        target_terms: list[str] = []
        for index, column in enumerate(numeric):
            for function in ("SUM", "MIN", "MAX"):
                alias = f"a{index}_{function.lower()}"
                aliases[alias] = f"{column.name}.{function.lower()}"
                source_terms.append(f"{function}(CAST(`{column.name}` AS BIGNUMERIC)) AS {alias}")
                target_terms.append(
                    f"{function}(CAST({_quote(column.name, dialect)} AS DECIMAL(38, 0))) AS {alias}"
                    if column.data_type in {"INT64", "INTEGER"}
                    else f"{function}({_quote(column.name, dialect)}) AS {alias}"
                )
        checks.append({
            **base,
            "query_id": f"{item.source_id}:aggregate",
            "check": "aggregate",
            "source_sql": _select(source_terms[0], source_terms[1:], source_table),
            "target_sql": _select(target_terms[0], target_terms[1:], target_table),
            "columns": aliases,
        })
    return checks


def _payload(check: dict[str, Any], rows: Any) -> Any:
    """Normalize one side's result row into the comparator payload for its check."""
    row = rows[0] if isinstance(rows, list) and len(rows) == 1 else rows
    if not isinstance(row, dict):
        return None
    if check["check"] == "row_count":
        return _as_count(row.get("row_count"))
    if check["check"] == "null_distribution":
        total = _as_count(row.get("row_count"))
        if total is None:
            return None
        distribution: dict[str, dict[str, int]] = {}
        for alias, column in check["columns"].items():
            nulls = _as_count(row.get(alias))
            if nulls is None:
                return None
            distribution[column] = {"null_count": nulls, "row_count": total}
        return distribution
    metrics: dict[str, str | None] = {}
    for alias, metric in check["columns"].items():
        if alias not in row:
            return None
        metrics[metric] = _as_decimal(row[alias])
    return metrics


def _as_count(value: Any) -> int | None:
    # BigQuery exports INT64 as JSON strings; accept those, reject bools and negatives.
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _as_decimal(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return str(value)
    return format(number.normalize(), "f")


def _unsafe_reason(item: BigQueryObject) -> str | None:
    parts = item.source_id.split(".")
    if len(parts) != 3 or not _SAFE_PROJECT.match(parts[0]):
        return "unsafe_identifier"
    names = [parts[1], parts[2], item.name, *(column.name for column in item.columns)]
    if item.dataset:
        names.append(item.dataset)
    return None if all(_SAFE_IDENTIFIER.match(name) for name in names) else "unsafe_identifier"


def _is_flat(column: Column) -> bool:
    return not column.fields and column.mode != "REPEATED" and column.data_type not in {
        "STRUCT", "RECORD", "ARRAY", "JSON", "GEOGRAPHY",
    }


def _count(dialect: str) -> str:
    return "COUNT_BIG(*)" if dialect == "tsql" else "COUNT(*)"


def _quote(name: str, dialect: str) -> str:
    return f"[{name}]" if dialect == "tsql" else f"`{name}`"


def _select(first: str, rest: list[str], table: str) -> str:
    return "SELECT " + ",\n       ".join([first, *rest]) + f"\nFROM {table}"


def _pack_id(pack: dict[str, Any]) -> str:
    canonical = json.dumps(pack, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
