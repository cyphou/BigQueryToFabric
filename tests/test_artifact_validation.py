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


def test_validate_artifact_rejects_embedded_credentials(tmp_path: Path) -> None:
    """Package validation must reject credentials in any persisted artifact text."""
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps({"query": "SELECT 'sk-1234567890'"}), encoding="utf-8")

    result = validate_artifact(path)

    assert result["status"] == "failed"
    assert result["errors"] == ["credential detected: api_key"]


def test_validate_artifact_rejects_non_object_json_roots(tmp_path: Path) -> None:
    """Malformed JSON roots must return validation errors instead of raising."""
    for filename, value in (("array.json", []), ("scalar.json", "value")):
        path = tmp_path / filename
        path.write_text(json.dumps(value), encoding="utf-8")

        result = validate_artifact(path)

        assert result["status"] == "failed"
        assert result["errors"] == ["JSON artifact root must be an object"]


def test_validate_directory_checks_target_artifact_consistency(tmp_path: Path) -> None:
    """Non-review target entries cannot point to missing or invalid generated artifacts."""
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "manifest.json").write_text(json.dumps({
        "artifacts": {
            "warehouse": [{"sourceId": "demo.orders", "path": "warehouse/orders.sql", "valid": False}]
        }
    }), encoding="utf-8")
    (tmp_path / "target-manifest.json").write_text(json.dumps({
        "entries": [{"sourceId": "demo.orders", "artifactKind": "warehouse_ddl", "manualReview": False}]
    }), encoding="utf-8")

    result = validate_directory(tmp_path)

    assert result["status"] == "failed"
    errors = [error for artifact in result["artifacts"] for error in artifact["errors"]]
    assert any("generated artifact path is missing" in error for error in errors)


def test_tsql_validator_rejects_hash_comment_marker() -> None:
    """'#' is a Python comment, not a T-SQL one, and must not reach a .sql artifact."""
    from bqtofabric.artifact_validation import TsqlValidator

    result = TsqlValidator("# VALIDATION PENDING\nSELECT 1\n").validate()

    assert result.valid is False
    assert any("'#' is not a T-SQL comment marker" in error for error in result.errors)


def test_tsql_validator_rejects_comma_swallowed_by_trailing_comment() -> None:
    """A trailing '--' comment must not comment out the column separator."""
    from bqtofabric.artifact_validation import TsqlValidator

    script = (
        "CREATE TABLE [ds].[t] (\n"
        "  [id] bigint NOT NULL -- primary id,\n"
        "  [nm] varchar(max) NULL\n"
        ")\n"
    )

    result = TsqlValidator(script).validate()

    assert result.valid is False
    assert any("does not parse as T-SQL" in error for error in result.errors)


def test_tsql_validator_rejects_create_schema_inside_batch() -> None:
    """CREATE SCHEMA must be the only statement in its batch."""
    from bqtofabric.artifact_validation import TsqlValidator

    script = "IF NOT EXISTS (SELECT 1)\nBEGIN\nCREATE SCHEMA [analytics]\nEND\nGO\n"

    result = TsqlValidator(script).validate()

    assert result.valid is False
    assert any("CREATE SCHEMA" in error for error in result.errors)


def test_tsql_validator_accepts_generated_shape() -> None:
    """The shape the generator emits must validate, including commented keywords."""
    from bqtofabric.artifact_validation import TsqlValidator

    script = (
        "-- Create table: orders\n"
        "IF NOT EXISTS (SELECT * FROM sys.schemas WHERE name = 'analytics')\n"
        "BEGIN\n"
        "  EXEC(N'CREATE SCHEMA [analytics]')\n"
        "END\n"
        "GO\n"
        "\n"
        "CREATE TABLE [analytics].[orders] (\n"
        "    -- primary id\n"
        "    [id] bigint NOT NULL,\n"
        "    [nm] varchar(max) NULL\n"
        ")\n"
    )

    result = TsqlValidator(script).validate()

    assert result.valid is True
    assert result.errors == ()


def test_pipeline_validator_requires_name_keyed_parameters() -> None:
    """Fabric rejects array-shaped parameters and variables on import."""
    from bqtofabric.artifact_validation import PipelineValidator

    pipeline = {
        "properties": {
            "activities": [],
            "parameters": [{"name": "TableName", "type": "string"}],
            "variables": [{"name": "RowCount", "type": "Integer"}],
        }
    }

    result = PipelineValidator(pipeline).validate()

    assert result.valid is False
    assert any("parameters must be a name-keyed object" in error for error in result.errors)
    assert any("variables must be a name-keyed object" in error for error in result.errors)


def test_pipeline_validator_rejects_triggers_as_pipeline_property() -> None:
    """Triggers are separate resources and cannot be declared inside properties."""
    from bqtofabric.artifact_validation import PipelineValidator

    result = PipelineValidator({"properties": {"activities": [], "triggers": []}}).validate()

    assert result.valid is False
    assert any("triggers are separate resources" in error for error in result.errors)


def test_pipeline_validator_rejects_secret_bearing_expressions() -> None:
    """Resolving a connection string into run parameters leaks it into run history."""
    from bqtofabric.artifact_validation import PipelineValidator

    pipeline = {
        "properties": {
            "activities": [
                {
                    "name": "Main Activity",
                    "typeProperties": {
                        "parameters": {
                            "SourceConnectionString": (
                                "@linkedService().properties.typeProperties.connectionString"
                            )
                        }
                    },
                }
            ]
        }
    }

    result = PipelineValidator(pipeline).validate()

    assert result.valid is False
    assert any("resolves a secret" in error for error in result.errors)


def test_validate_artifact_rejects_notebook_with_undefined_dataframe(tmp_path: Path) -> None:
    """Notebook validation must run the DataFrame check, not only nbformat checks."""
    path = tmp_path / "notebook.ipynb"
    path.write_text(json.dumps({
        "nbformat": 4,
        "cells": [{"cell_type": "code", "source": ["df_transformed = df_source\n"]}],
    }), encoding="utf-8")

    result = validate_artifact(path)

    assert result["status"] == "failed"
    assert any("df_source" in error for error in result["errors"])