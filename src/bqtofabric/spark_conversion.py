"""Offline Spark and Dataproc conversion recipes for Fabric notebooks."""

from __future__ import annotations

from typing import Any

from .models import BigQueryObject, ObjectKind


def convert_spark_job(item: BigQueryObject) -> dict[str, Any]:
    """Return a deterministic notebook conversion recipe from inventory evidence."""
    if item.kind not in {ObjectKind.SPARK_JOB, ObjectKind.DATAPROC_JOB}:
        raise ValueError(f"Unsupported Spark conversion kind: {item.kind.value}")

    properties = item.properties
    actions = [
        "Create a Fabric notebook bound to the target Lakehouse.",
        "Validate the Spark runtime and dependency versions before execution.",
    ]
    substitutions = []
    if properties.get("uses_gcs"):
        substitutions.append({"source": "gs://", "target": "OneLake path or approved Shortcut"})
    if properties.get("uses_bigquery_connector"):
        substitutions.append({
            "source": "BigQuery connector",
            "target": "Fabric native BigQuery connector",
        })
    if properties.get("language"):
        actions.append(f"Preserve {str(properties['language']).upper()} source cells where supported.")
    if properties.get("streaming"):
        actions.append("Carry checkpoint, watermark, trigger, and delivery semantics into the notebook design.")

    return {
        "sourceId": item.source_id,
        "sourceKind": item.kind.value,
        "target": "fabric_notebook",
        "runtime": properties.get("runtime_version", "not specified"),
        "actions": actions,
        "substitutions": substitutions,
        "status": "review_required",
    }
