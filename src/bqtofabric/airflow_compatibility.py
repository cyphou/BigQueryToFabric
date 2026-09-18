"""Offline Composer/Airflow compatibility assessment."""

from __future__ import annotations

from typing import Any

from .models import BigQueryObject, ObjectKind


def assess_airflow_compatibility(item: BigQueryObject) -> dict[str, Any]:
    """Classify Airflow evidence without importing or executing DAG code."""
    if item.kind is not ObjectKind.COMPOSER_DAG:
        raise ValueError(f"Unsupported Airflow compatibility kind: {item.kind.value}")

    properties = item.properties
    unsupported = list(properties.get("unsupported_operators", []))
    operators = list(properties.get("operators", []))
    connections = list(properties.get("connections", []))
    plugins = bool(properties.get("custom_plugins", False))
    status = "redesign_required" if unsupported or plugins else "review_required"
    actions = ["Validate provider versions, schedules, retries, pools, and secret bindings."]
    if unsupported:
        actions.append("Replace unsupported operators with Fabric Pipeline or Notebook activities.")
    if plugins:
        actions.append("Port custom plugins explicitly; do not assume Composer plugins run in Fabric.")

    return {
        "sourceId": item.source_id,
        "target": "airflow_job" if status == "review_required" else "fabric_pipeline",
        "operators": operators,
        "unsupportedOperators": unsupported,
        "connections": connections,
        "customPlugins": plugins,
        "actions": actions,
        "status": status,
    }
