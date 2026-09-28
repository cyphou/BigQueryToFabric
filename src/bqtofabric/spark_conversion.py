"""Offline Spark and Dataproc conversion recipes for Fabric notebooks."""

from __future__ import annotations

from typing import Any

from .converter.models import SparkCodeLanguage
from .converter.spark_converter import SparkConverter
from .models import BigQueryObject, ObjectKind

# Closed set: a review reason outside it is a converter change that needs a documented code.
SPARK_REASON_CODES = frozenset({
    "dynamic_sql",
    "language",
    "rdd",
    "storage_paths",
    "streaming",
    "udf",
    "source_code_missing",
    "runtime_version_missing",
})


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

    record: dict[str, Any] = {
        "sourceId": item.source_id,
        "sourceKind": item.kind.value,
        "target": "fabric_notebook",
        "runtime": properties.get("runtime_version", "not specified"),
        "actions": actions,
        "substitutions": substitutions,
        "status": "review_required",
    }
    reasons: set[str] = set()
    code = properties.get("code")
    if isinstance(code, str) and code.strip():
        language = (
            SparkCodeLanguage.SCALA
            if "scala" in str(properties.get("language", "")).lower()
            else SparkCodeLanguage.PYSPARK
        )
        conversion = SparkConverter().convert(item.source_id, code, language)
        reasons.update(
            pattern for step in conversion.manual_steps for pattern in step.affected_patterns
        )
        record["conversion"] = {
            "compatibility": str(conversion.compatibility_level),
            "rewrites": sum(warning.category == "rewrite" for warning in conversion.warnings),
        }
    else:
        reasons.add("source_code_missing")
    if not properties.get("runtime_version"):
        reasons.add("runtime_version_missing")
    record["reasonCodes"] = sorted(reasons)
    return record
