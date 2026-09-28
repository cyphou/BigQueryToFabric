"""Normalize a dbt ``manifest.json`` into one canonical ``dbt_project`` component (offline)."""

from __future__ import annotations

from typing import Any

from .discovery import redact_mapping
from .models import BigQueryObject, ObjectKind

# Jinja the dbt converter translates; any other macro in a model is flagged for review.
TRANSLATED_MACROS = frozenset({"ref", "source", "config", "var", "is_incremental", "this"})


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def normalize_dbt_manifest(project_id: str, manifest: dict[str, Any]) -> BigQueryObject:
    """Read models, tests, and sources from a dbt manifest without running dbt."""
    if not all(isinstance(manifest.get(key), dict) for key in ("metadata", "nodes")):
        raise TypeError("dbt manifest must contain metadata and nodes objects")
    metadata, nodes, sources = _dict(manifest["metadata"]), _dict(manifest["nodes"]), _dict(manifest.get("sources"))
    project = str(metadata.get("project_name") or "dbt_project")

    source_names = {
        key: (str(value.get("source_name", "")), str(value.get("name", "")))
        for key, value in sources.items()
        if isinstance(value, dict)
    }
    model_names = {
        key: str(value.get("name", ""))
        for key, value in nodes.items()
        if isinstance(value, dict) and value.get("resource_type") == "model"
    }

    models: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []
    for key in sorted(nodes):
        node = nodes[key]
        if not isinstance(node, dict):
            continue
        depends = _dict(node.get("depends_on"))
        upstream = [str(item) for item in depends.get("nodes", [])]
        if node.get("resource_type") == "model":
            config = _dict(node.get("config"))
            macros = sorted({
                str(item).rsplit(".", 1)[-1] for item in depends.get("macros", [])
            } - TRANSLATED_MACROS)
            model: dict[str, Any] = {
                "name": model_names[key],
                "schema": str(node.get("schema", "")),
                "materialized": str(config.get("materialized", "view")),
                "sql": str(node.get("raw_code") or node.get("raw_sql") or ""),
                "refs": sorted(model_names[item] for item in upstream if item in model_names),
                "sources": sorted([list(source_names[item]) for item in upstream if item in source_names]),
                "macros": macros,
            }
            if config.get("unique_key"):
                model["unique_key"] = config["unique_key"]
            models.append(model)
        elif node.get("resource_type") == "test":
            test_metadata = _dict(node.get("test_metadata"))
            kwargs = _dict(test_metadata.get("kwargs"))
            tests.append({
                "name": str(test_metadata.get("name") or node.get("name", "")),
                "models": sorted(model_names[item] for item in upstream if item in model_names),
                "column": str(kwargs.get("column_name", "")),
            })

    properties = {
        "adapter": str(metadata.get("adapter_type", "")),
        "dbt_version": str(metadata.get("dbt_version", "")),
        "models": models,
        "tests": tests,
        "sources": [
            {"source_name": name[0], "name": name[1]} for name in sorted(set(source_names.values()))
        ],
    }
    return BigQueryObject(
        source_id=f"{project_id}.dbt.{project}",
        name=project,
        kind=ObjectKind.DBT_PROJECT,
        discovered_from="external_payload",
        properties=redact_mapping(properties),
    )
