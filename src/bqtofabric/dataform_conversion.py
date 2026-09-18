"""Offline Dataform-to-Fabric conversion recipes."""

from __future__ import annotations

from typing import Any

from .models import BigQueryObject, ObjectKind


def convert_dataform_workflow(item: BigQueryObject) -> dict[str, Any]:
    """Translate Dataform evidence into a Fabric pipeline recipe."""
    if item.kind is not ObjectKind.DATAFORM_WORKFLOW:
        raise ValueError(f"Unsupported Dataform conversion kind: {item.kind.value}")

    properties = item.properties
    actions = [
        "Create dependency-ordered Fabric Pipeline activities for the Dataform graph.",
        "Preserve variables and environment-specific configuration as pipeline parameters.",
    ]
    if properties.get("assertions"):
        actions.append("Create explicit data-quality checks for Dataform assertions.")
    if properties.get("incremental"):
        actions.append("Review watermark, merge key, and late-arriving-data behavior.")

    return {
        "sourceId": item.source_id,
        "sourceKind": item.kind.value,
        "target": "fabric_pipeline",
        "models": properties.get("models", []),
        "dependencies": list(item.dependencies),
        "assertions": bool(properties.get("assertions", False)),
        "incremental": bool(properties.get("incremental", False)),
        "actions": actions,
        "status": "review_required",
    }
