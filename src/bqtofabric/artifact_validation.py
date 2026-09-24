"""Offline structural validation for generated Fabric artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot.errors import SqlglotError

from .security import CredentialScanner


@dataclass(frozen=True, slots=True)
class ArtifactValidationResult:
    """Outcome of validating an in-memory generated artifact."""

    valid: bool
    errors: tuple[str, ...] = ()


def find_undefined_dataframes(code: str) -> tuple[str, ...]:
    """Return ``df_*`` names referenced by notebook code but never assigned."""
    defined = set(re.findall(r"^\s*(df_[A-Za-z0-9_]+)\s*=", code, re.MULTILINE))
    referenced = set(re.findall(r"\b(df_[A-Za-z0-9_]+)\b", code))
    return tuple(sorted(referenced - defined))


def _notebook_code(notebook: Any) -> str:
    """Join code-cell sources from either a FabricNotebook or a parsed ``.ipynb``."""
    if isinstance(notebook, dict):
        cells = [cell for cell in notebook.get("cells", []) if isinstance(cell, dict)]
        return "\n".join(
            "".join(cell.get("source", []))
            for cell in cells
            if cell.get("cell_type") == "code"
        )
    return "\n".join(
        "".join(cell.source) for cell in notebook.cells if cell.cell_type == "code"
    )


class NotebookValidator:
    """Check generated notebooks for undefined DataFrame references."""

    def __init__(self, notebook: Any) -> None:
        self.notebook = notebook

    def validate(self) -> ArtifactValidationResult:
        errors = tuple(
            f"Undefined DataFrame reference: {name}"
            for name in find_undefined_dataframes(_notebook_code(self.notebook))
        )
        return ArtifactValidationResult(valid=not errors, errors=errors)


class TsqlValidator:
    """Re-parse the parseable portions of a generated T-SQL script.

    sqlglot cannot parse T-SQL ``IF ... BEGIN ... END`` control flow, so whole-script
    parsing would report false failures. This checks the constructs it can parse plus
    batch rules that sqlglot does not model.
    """

    def __init__(self, script: str) -> None:
        self.script = script

    def validate(self) -> ArtifactValidationResult:
        errors: list[str] = []
        if not self.script.strip():
            errors.append("SQL artifact is empty")
            return ArtifactValidationResult(valid=False, errors=tuple(errors))

        for number, line in enumerate(self.script.splitlines(), start=1):
            if line.lstrip().startswith("#"):
                errors.append(f"line {number}: '#' is not a T-SQL comment marker")

        code = _strip_sql_comments(self.script)

        for statement in _extract_create_tables(code):
            try:
                sqlglot.parse(statement, read="tsql")
            except SqlglotError as error:
                detail = str(error).splitlines()[0]
                errors.append(f"CREATE TABLE does not parse as T-SQL: {detail}")

        for match in re.finditer(r"(?im)^[ \t]*CREATE\s+SCHEMA\b", code):
            errors.append(
                "CREATE SCHEMA must be the only statement in its batch; "
                "wrap it in EXEC(N'...')"
            )
        return ArtifactValidationResult(valid=not errors, errors=tuple(errors))


def _strip_sql_comments(script: str) -> str:
    """Remove ``--`` and ``/* */`` comments, preserving string literals and line count."""
    out: list[str] = []
    index = 0
    length = len(script)
    while index < length:
        char = script[index]
        if char == "'":
            out.append(char)
            index += 1
            while index < length:
                out.append(script[index])
                if script[index] == "'":
                    index += 1
                    break
                index += 1
            continue
        if script.startswith("--", index):
            while index < length and script[index] != "\n":
                index += 1
            continue
        if script.startswith("/*", index):
            end = script.find("*/", index + 2)
            segment = script[index:] if end == -1 else script[index : end + 2]
            out.append("\n" * segment.count("\n"))
            index = length if end == -1 else end + 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _extract_create_tables(script: str) -> list[str]:
    """Return each ``CREATE TABLE`` statement up to its balanced closing paren."""
    statements: list[str] = []
    for match in re.finditer(r"(?i)CREATE\s+TABLE\b", script):
        opening = script.find("(", match.end())
        if opening == -1:
            continue
        depth = 0
        for index in range(opening, len(script)):
            if script[index] == "(":
                depth += 1
            elif script[index] == ")":
                depth -= 1
                if depth == 0:
                    statements.append(script[match.start() : index + 1])
                    break
    return statements


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
        # .create-or-alter applies to functions and materialized views, not tables.
        if re.search(r"^\s*\.create-or-alter\s+table\s+\S+\s*\(", self.query, re.MULTILINE):
            errors.append(
                "KQL command error: .create-or-alter table is not a command; "
                "use .create table, .create-merge table, or .alter table"
            )
        if re.search(
            r"ingestion\s+json\s+mapping\b[^\n]*\n\s*\(", self.query, re.IGNORECASE
        ):
            errors.append(
                "KQL mapping error: a json ingestion mapping takes a JSON array of "
                "column/Path objects, not CSV-style parentheses"
            )
        errors.extend(_nondeterministic_view_errors(self.query))
        return ArtifactValidationResult(valid=not errors, errors=tuple(errors))


def _nondeterministic_view_errors(query: str) -> list[str]:
    """Materialized-view definitions must not depend on wall-clock time."""
    errors: list[str] = []
    for match in re.finditer(
        r"\.create(?:-or-alter)?\s+materialized-view\b.*?\{(.*?)\}", query, re.DOTALL
    ):
        body = match.group(1)
        for function in ("ago", "now"):
            if re.search(rf"\b{function}\s*\(", body):
                errors.append(
                    f"KQL materialized view error: {function}() is non-deterministic and "
                    "is not permitted in a materialized-view definition"
                )
    return errors


class PipelineValidator:
    """Check pipeline activity dependencies resolve to declared activities."""

    def __init__(self, pipeline: dict[str, Any]) -> None:
        self.pipeline = pipeline

    def validate(self) -> ArtifactValidationResult:
        properties = self.pipeline.get("properties", {})
        activities = properties.get("activities", [])
        names = {
            activity.get("name")
            for activity in activities
            if isinstance(activity, dict) and activity.get("name")
        }
        errors: list[str] = []
        for section in ("parameters", "variables"):
            value = properties.get(section)
            if value is not None and not isinstance(value, dict):
                errors.append(f"pipeline {section} must be a name-keyed object")
        if "triggers" in properties:
            errors.append("triggers are separate resources and cannot be pipeline properties")
        errors.extend(_secret_bearing_expressions(properties))
        for activity in activities:
            if not isinstance(activity, dict):
                errors.append("Pipeline activity must be an object")
                continue
            if activity.get("type") == "Lookup":
                type_properties = activity.get("typeProperties", {})
                dataset = (
                    type_properties.get("dataset")
                    if isinstance(type_properties, dict)
                    else None
                )
                if not isinstance(dataset, dict) or not dataset.get("referenceName"):
                    errors.append(
                        f"Lookup activity {activity.get('name', '<unnamed>')} needs a "
                        "dataset reference"
                    )
            for dependency in activity.get("dependsOn", []):
                predecessor = dependency.get("activity") if isinstance(dependency, dict) else None
                if predecessor and predecessor not in names:
                    errors.append(
                        f"Activity {activity.get('name', '<unnamed>')} depends on undefined activity {predecessor}"
                    )
        return ArtifactValidationResult(valid=not errors, errors=tuple(errors))


def _secret_bearing_expressions(value: Any, path: str = "properties") -> list[str]:
    """Flag pipeline expressions that would resolve a secret into run history."""
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            errors.extend(_secret_bearing_expressions(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_secret_bearing_expressions(child, f"{path}[{index}]"))
    elif isinstance(value, str) and re.search(
        r"(?i)typeProperties\.(connectionString|password|accountKey|sasToken)", value
    ):
        errors.append(f"{path}: expression resolves a secret into pipeline run output")
    return errors


def validate_artifact(path: Path) -> dict[str, Any]:
    """Validate one generated artifact without executing or deploying it."""
    result: dict[str, Any] = {"path": path.name, "status": "passed", "errors": []}
    try:
        text = path.read_text(encoding="utf-8")
        findings = CredentialScanner().scan(text)
        result["errors"].extend(
            f"credential detected: {finding.finding_type}"
            for finding in findings
        )
        if path.suffix == ".json" or path.suffix == ".ipynb":
            value = json.loads(text)
            if not isinstance(value, dict):
                result["errors"].append("JSON artifact root must be an object")
            elif path.suffix == ".ipynb":
                _validate_notebook(value, result["errors"])
                result["errors"].extend(NotebookValidator(value).validate().errors)
            elif "properties" in value and "activities" in value.get("properties", {}):
                result["errors"].extend(PipelineValidator(value).validate().errors)
            elif value.get("mode") == "dry-run" and not value.get("projectId", True):
                result["errors"].append("dry-run artifact is missing projectId")
        elif path.suffix == ".kql":
            result["errors"].extend(KqlValidator(text).validate().errors)
        elif path.suffix == ".sql":
            result["errors"].extend(TsqlValidator(text).validate().errors)
    except (OSError, json.JSONDecodeError) as error:
        result["errors"].append(str(error))
    result["status"] = "failed" if result["errors"] else "passed"
    return result


def validate_directory(root: Path) -> dict[str, Any]:
    results = [
        validate_artifact(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix in {".json", ".ipynb", ".sql", ".kql"}
    ]
    consistency_errors = _validate_manifest_consistency(root)
    if consistency_errors:
        results.append({
            "path": "manifest-consistency",
            "status": "failed",
            "errors": consistency_errors,
        })
    return {
        "mode": "dry-run",
        "status": "failed" if any(item["status"] == "failed" for item in results) else "passed",
        "artifacts": results,
    }


def _validate_manifest_consistency(root: Path) -> list[str]:
    """Check target entries against generated artifact paths and validity flags."""
    target_path = root / "target-manifest.json"
    generated_path = root / "generated" / "manifest.json"
    if not target_path.exists() or not generated_path.exists():
        return []
    try:
        target = json.loads(target_path.read_text(encoding="utf-8"))
        generated = json.loads(generated_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"manifest consistency could not be read: {error}"]

    artifacts: dict[str, list[dict[str, Any]]] = {}
    for entries in generated.get("artifacts", {}).values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("sourceId"), str):
                artifacts.setdefault(entry["sourceId"], []).append(entry)

    errors: list[str] = []
    expected_categories = {
        "lakehouse_notebook": "notebooks",
        "warehouse_ddl": "warehouse",
        "eventhouse_kql": "eventhouse",
        "eventstream_definition": "eventstreams",
        "semantic_model_definition": "semantic_models",
        "fabric_pipeline": "pipelines",
    }
    for entry in target.get("entries", []):
        if not isinstance(entry, dict):
            continue
        artifact_kind = entry.get("artifactKind")
        category = (
            expected_categories.get(artifact_kind)
            if isinstance(artifact_kind, str)
            else None
        )
        source_id = entry.get("sourceId")
        if not category or not isinstance(source_id, str):
            continue
        matches = [
            item for item in artifacts.get(source_id, [])
            if item in generated.get("artifacts", {}).get(category, [])
        ]
        if not matches:
            errors.append(f"target entry has no generated artifact: {source_id}")
            continue
        for artifact in matches:
            artifact_path = root / "generated" / artifact.get("path", "")
            if not artifact_path.is_file():
                errors.append(f"generated artifact path is missing: {artifact.get('path', '')}")
            if entry.get("manualReview") is False and artifact.get("valid") is False:
                errors.append(f"non-review target references invalid artifact: {source_id}")
    return errors


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
