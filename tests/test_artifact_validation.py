import json
from pathlib import Path

from bqtofabric.artifact_validation import validate_artifact, validate_directory


def test_validate_directory_checks_notebook_and_json(tmp_path: Path) -> None:
    (tmp_path / "valid.ipynb").write_text(json.dumps({
        "nbformat": 4,
        "cells": [{"cell_type": "code", "source": []}],
    }), encoding="utf-8")
    (tmp_path / "artifact.json").write_text(json.dumps({"mode": "dry-run"}), encoding="utf-8")

    result = validate_directory(tmp_path)

    assert result["status"] == "passed"
    assert len(result["artifacts"]) == 2


def test_validate_artifact_rejects_invalid_notebook(tmp_path: Path) -> None:
    path = tmp_path / "invalid.ipynb"
    path.write_text(json.dumps({"nbformat": 3, "cells": "invalid"}), encoding="utf-8")

    result = validate_artifact(path)

    assert result["status"] == "failed"
    assert result["errors"]


def test_kql_validator_rejects_invalid_syntax() -> None:
    """Invalid KQL must be deployment-blocking rather than emitted as executable code."""
    from bqtofabric.artifact_validation import KqlValidator

    result = KqlValidator("SELECT FROM WHERE").validate()

    assert result.valid is False
    assert any("syntax" in error.lower() for error in result.errors)


def test_pipeline_validator_rejects_undefined_predecessor() -> None:
    """Activities may only depend on activities declared in the same pipeline."""
    from bqtofabric.artifact_validation import PipelineValidator

    pipeline = {
        "properties": {
            "activities": [
                {
                    "name": "Main Activity",
                    "dependsOn": [{"activity": "Undefined", "dependencyConditions": ["Succeeded"]}],
                }
            ]
        }
    }

    result = PipelineValidator(pipeline).validate()

    assert result.valid is False
    assert any("Undefined" in error for error in result.errors)


def test_validate_directory_checks_nested_kql_and_pipeline_json(tmp_path: Path) -> None:
    """Generated subdirectories must use the same KQL and pipeline validators."""
    realtime = tmp_path / "realtime"
    pipelines = tmp_path / "pipelines"
    realtime.mkdir()
    pipelines.mkdir()
    (realtime / "invalid.kql").write_text("SELECT FROM WHERE", encoding="utf-8")
    (pipelines / "invalid.json").write_text(json.dumps({
        "properties": {
            "activities": [{
                "name": "Load",
                "dependsOn": [{"activity": "Missing"}],
            }]
        }
    }), encoding="utf-8")

    result = validate_directory(tmp_path)

    assert result["status"] == "failed"
    errors = [error for artifact in result["artifacts"] for error in artifact["errors"]]
    assert any("KQL syntax" in error for error in errors)
    assert any("Missing" in error for error in errors)