"""Deterministic dry-run specifications for specialized Fabric targets."""

from __future__ import annotations

import re
from typing import Any

from .mapping import FabricTarget, MappingDecision
from .models import BigQueryInventory, BigQueryObject

_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LOOKML_COLUMN = re.compile(r"^\$\{(?:TABLE\}\.)?([A-Za-z_][A-Za-z0-9_]*)\}?$")
_DAX_AGGREGATES = {
    "sum": "SUM",
    "average": "AVERAGE",
    "min": "MIN",
    "max": "MAX",
    "count_distinct": "DISTINCTCOUNT",
}
# BQML model_type -> suggested Fabric Data Science starting point; never a parity claim.
_BQML_APPROACHES = {
    "LINEAR_REG": "scikit-learn LinearRegression",
    "LOGISTIC_REG": "scikit-learn LogisticRegression",
    "KMEANS": "scikit-learn KMeans",
    "BOOSTED_TREE_CLASSIFIER": "LightGBM classifier (SynapseML)",
    "BOOSTED_TREE_REGRESSOR": "LightGBM regressor (SynapseML)",
    "RANDOM_FOREST_CLASSIFIER": "scikit-learn RandomForestClassifier",
    "RANDOM_FOREST_REGRESSOR": "scikit-learn RandomForestRegressor",
    "MATRIX_FACTORIZATION": "SynapseML SAR or ALS recommender",
    "ARIMA_PLUS": "statsmodels or Prophet time-series model",
    "AUTOML_CLASSIFIER": "FLAML AutoML classification",
    "AUTOML_REGRESSOR": "FLAML AutoML regression",
}


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
        converted, unconverted = _convert_lookml_measures(item.properties.get("measures", []))
        fields = {
            "explores": item.properties.get("explores", []),
            "measures": item.properties.get("measures", []),
            "joins": item.properties.get("joins", []),
            "security": item.properties.get("access_filters", "review_required"),
            "daxMeasures": converted,
            "unconvertedMeasures": unconverted,
        }
    elif target is FabricTarget.DATA_SCIENCE:
        artifact_type = "data_science_spec"
        model_type = str(item.properties.get("model_type", "review_required"))
        fields = {
            "modelType": model_type,
            "features": item.properties.get("features", []),
            "metrics": item.properties.get("evaluation_metrics", []),
            "serving": item.properties.get("serving_mode", "review_required"),
            "scaffold": _data_science_scaffold(item, model_type),
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


def _convert_lookml_measures(measures: Any) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Translate simple LookML aggregate measures to DAX; everything else is listed, not guessed."""
    converted: list[dict[str, str]] = []
    unconverted: list[dict[str, str]] = []
    for measure in measures if isinstance(measures, list) else []:
        if not isinstance(measure, dict):
            continue
        name = str(measure.get("name", ""))
        view = str(measure.get("view", ""))
        kind = str(measure.get("type", "")).lower()
        if not (_SAFE_NAME.match(name) and _SAFE_NAME.match(view)):
            unconverted.append({"name": name, "reason": "unsafe_identifier"})
            continue
        if measure.get("filters"):
            unconverted.append({"name": name, "reason": "filtered_measure"})
            continue
        if kind == "count":
            converted.append({"name": name, "table": view, "expression": f"COUNTROWS('{view}')"})
            continue
        column = _LOOKML_COLUMN.match(str(measure.get("sql", "")).strip())
        if kind not in _DAX_AGGREGATES:
            unconverted.append({"name": name, "reason": f"unsupported_type:{kind or 'missing'}"})
        elif column is None:
            unconverted.append({"name": name, "reason": "sql_expression"})
        else:
            converted.append({
                "name": name,
                "table": view,
                "expression": f"{_DAX_AGGREGATES[kind]}('{view}'[{column.group(1)}])",
            })
    return converted, unconverted


def _data_science_scaffold(item: BigQueryObject, model_type: str) -> dict[str, Any]:
    """Describe a notebook-and-experiment starting point; parity stays not_run."""
    steps = item.properties.get("pipeline_steps", [])
    experiment = re.sub(r"[^A-Za-z0-9_]", "_", item.name)
    return {
        "experimentName": f"{item.kind.value}_{experiment}",
        "approach": _BQML_APPROACHES.get(model_type.upper(), "review_required"),
        "notebookSteps": [str(step) for step in steps] if isinstance(steps, list) and steps else [
            "load_features", "train", "evaluate", "register_model",
        ],
        "modelParity": "not_run",
    }
