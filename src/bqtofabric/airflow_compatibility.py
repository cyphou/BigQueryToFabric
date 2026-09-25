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
    operators = _sorted_strings(properties.get("operators", []))
    connections = _sorted_strings(properties.get("connections", []))
    providers = _sorted_strings(properties.get("providers", []))
    sensors = _sorted_strings(properties.get("sensors", []))
    pools = _sorted_strings(properties.get("pools", []))
    plugins = bool(properties.get("custom_plugins", False))
    status = "redesign_required" if unsupported or plugins else "review_required"
    actions = ["Validate provider versions, schedules, retries, pools, and secret bindings."]
    if unsupported:
        actions.append("Replace unsupported operators with Fabric Pipeline or Notebook activities.")
    if plugins:
        actions.append("Port custom plugins explicitly; do not assume Composer plugins run in Fabric.")
    if sensors:
        actions.append("Review sensor polling, timeout, and deferrable-operator behavior in Fabric.")
    if pools:
        actions.append("Map Airflow pools to Fabric concurrency and workload controls.")
    if properties.get("sla") is not None:
        actions.append("Recreate SLA monitoring and escalation outside the migrated DAG.")

    return {
        "sourceId": item.source_id,
        "target": "airflow_job" if status == "review_required" else "fabric_pipeline",
        "operators": operators,
        "unsupportedOperators": unsupported,
        "providers": providers,
        "sensors": sensors,
        "pools": pools,
        "connections": connections,
        "sla": properties.get("sla"),
        "retries": properties.get("retries"),
        "retryDelay": properties.get("retry_delay"),
        "schedule": properties.get("schedule_interval", properties.get("schedule")),
        "customPlugins": plugins,
        "actions": actions,
        "status": status,
    }


def _sorted_strings(value: Any) -> list[str]:
    """Return deterministic non-empty string metadata."""
    if not isinstance(value, (list, tuple, set)):
        return []
    return sorted({str(item) for item in value if str(item)})
