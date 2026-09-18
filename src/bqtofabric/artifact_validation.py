"""Offline structural validation for generated Fabric artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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
