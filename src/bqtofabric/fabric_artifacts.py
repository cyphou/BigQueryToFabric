"""Deterministic dry-run specifications for specialized Fabric targets."""

from __future__ import annotations

from typing import Any

from .mapping import FabricTarget, MappingDecision
from .models import BigQueryInventory, BigQueryObject


def build_specialized_artifacts(
    inventory: BigQueryInventory, decisions: tuple[MappingDecision, ...]
) -> dict[str, dict[str, Any]]:
    """Build reviewable target specifications without Fabric API calls."""
    objects = {item.source_id: item for item in inventory.objects()}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for decision in sorted(decisions, key=lambda item: item.source_id):
        if decision.target not in {
            FabricTarget.EVENTHOUSE,
            FabricTarget.EVENTSTREAM,
            FabricTarget.SEMANTIC_MODEL,
            FabricTarget.DATA_SCIENCE,
            FabricTarget.PURVIEW,
            FabricTarget.SQL_DATABASE,
        }:
            continue
        item = objects[decision.source_id]
        artifact = _artifact_for(item, decision)
        grouped.setdefault(artifact["artifactType"], []).append(artifact)
    return {
        artifact_type: {
            "mode": "dry-run",
            "projectId": inventory.project_id,
            "items": items,
        }
        for artifact_type, items in sorted(grouped.items())
    }


def _artifact_for(item: BigQueryObject, decision: MappingDecision) -> dict[str, Any]:
    target = decision.target
    if target in {FabricTarget.EVENTHOUSE, FabricTarget.EVENTSTREAM}:
        artifact_type = "eventhouse_eventstream_spec"
        fields = {
            "sourceKind": item.kind.value,
            "streaming": bool(item.properties.get("streaming", True)),
            "retention": item.properties.get("retention", "review_required"),
            "schema": item.properties.get("schema", "review_required"),
            "delivery": item.properties.get("delivery_semantics", "review_required"),
        }
    elif target is FabricTarget.SEMANTIC_MODEL:
        artifact_type = "semantic_model_spec"
        fields = {
            "explores": item.properties.get("explores", []),
            "measures": item.properties.get("measures", []),
            "joins": item.properties.get("joins", []),
            "security": item.properties.get("access_filters", "review_required"),
        }
    elif target is FabricTarget.DATA_SCIENCE:
        artifact_type = "data_science_spec"
        fields = {
            "modelType": item.properties.get("model_type", "review_required"),
            "features": item.properties.get("features", []),
            "metrics": item.properties.get("evaluation_metrics", []),
            "serving": item.properties.get("serving_mode", "review_required"),
        }
    elif target is FabricTarget.PURVIEW:
        artifact_type = "purview_governance_spec"
        fields = {
            "classifications": item.properties.get("classifications", []),
            "glossary": item.properties.get("glossary", []),
            "owners": item.properties.get("owners", []),
            "lineage": list(item.dependencies),
        }
    else:
        artifact_type = "sql_database_spec"
        fields = {
            "engine": item.properties.get("engine", "review_required"),
            "version": item.properties.get("version", "review_required"),
            "replication": item.properties.get("replication", "review_required"),
            "cdc": item.properties.get("change_streams", "review_required"),
        }
    return {
        "sourceId": item.source_id,
        "target": target.value,
        "artifactType": artifact_type,
        "compatibility": decision.compatibility.value,
        "actions": list(decision.actions),
        "fields": fields,
        "status": "review_required",
    }
