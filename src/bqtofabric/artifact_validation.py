"""Offline structural validation for generated Fabric artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ArtifactValidationResult:
    """Outcome of validating an in-memory generated artifact."""

    valid: bool
    errors: tuple[str, ...] = ()


class NotebookValidator:
    """Check generated notebooks for undefined DataFrame references."""

    def __init__(self, notebook: Any) -> None:
        self.notebook = notebook

    def validate(self) -> ArtifactValidationResult:
        code = "\n".join(
            "".join(cell.source)
            for cell in self.notebook.cells
            if cell.cell_type == "code"
        )
        defined = set(re.findall(r"^\s*(df_[A-Za-z0-9_]+)\s*=", code, re.MULTILINE))
        referenced = set(re.findall(r"\b(df_[A-Za-z0-9_]+)\b", code))
        errors = tuple(
            f"Undefined DataFrame reference: {name}"
            for name in sorted(referenced - defined)
        )
        return ArtifactValidationResult(valid=not errors, errors=errors)


class KqlValidator:
    """Reject common non-KQL syntax in generated Eventhouse queries."""

    def __init__(self, query: str) -> None:
        self.query = query

    def validate(self) -> ArtifactValidationResult:
        errors: list[str] = []
        if not self.query.strip():
            errors.append("KQL syntax error: query is empty")
        if re.search(r"\bSELECT\s+FROM\s+WHERE\b", self.query, re.IGNORECASE):
            errors.append("KQL syntax error: incomplete SQL SELECT statement")
        return ArtifactValidationResult(valid=not errors, errors=tuple(errors))


class PipelineValidator:
    """Check pipeline activity dependencies resolve to declared activities."""

    def __init__(self, pipeline: dict[str, Any]) -> None:
        self.pipeline = pipeline

    def validate(self) -> ArtifactValidationResult:
        activities = self.pipeline.get("properties", {}).get("activities", [])
        names = {
            activity.get("name")
            for activity in activities
            if isinstance(activity, dict) and activity.get("name")
        }
        errors: list[str] = []
        for activity in activities:
            if not isinstance(activity, dict):
                errors.append("Pipeline activity must be an object")
                continue
            for dependency in activity.get("dependsOn", []):
                predecessor = dependency.get("activity") if isinstance(dependency, dict) else None
                if predecessor and predecessor not in names:
                    errors.append(
                        f"Activity {activity.get('name', '<unnamed>')} depends on undefined activity {predecessor}"
                    )
        return ArtifactValidationResult(valid=not errors, errors=tuple(errors))


def validate_artifact(path: Path) -> dict[str, Any]:
    """Validate one generated artifact without executing or deploying it."""
    result: dict[str, Any] = {"path": path.name, "status": "passed", "errors": []}
    try:
        if path.suffix == ".json" or path.suffix == ".ipynb":
            value = json.loads(path.read_text(encoding="utf-8"))
            if path.suffix == ".ipynb":
                _validate_notebook(value, result["errors"])
            elif value.get("mode") == "dry-run" and not value.get("projectId", True):
                result["errors"].append("dry-run artifact is missing projectId")
        elif path.suffix == ".sql":
            if not path.read_text(encoding="utf-8").strip():
                result["errors"].append("SQL artifact is empty")
    except (OSError, json.JSONDecodeError) as error:
        result["errors"].append(str(error))
    result["status"] = "failed" if result["errors"] else "passed"
    return result


def validate_directory(root: Path) -> dict[str, Any]:
    results = [
        validate_artifact(path)
        for path in sorted(root.iterdir())
        if path.is_file() and path.suffix in {".json", ".ipynb", ".sql"}
    ]
    return {
        "mode": "dry-run",
        "status": "failed" if any(item["status"] == "failed" for item in results) else "passed",
        "artifacts": results,
    }


def _validate_notebook(value: Any, errors: list[str]) -> None:
    if value.get("nbformat") != 4:
        errors.append("notebook nbformat must be 4")
    if not isinstance(value.get("cells"), list):
        errors.append("notebook cells must be a list")
    for index, cell in enumerate(value.get("cells", [])):
        if not isinstance(cell, dict):
            errors.append(f"cell {index} must be an object")
            continue
        if cell.get("cell_type") not in {"code", "markdown", "raw"}:
            errors.append(f"cell {index} has an invalid cell_type")
