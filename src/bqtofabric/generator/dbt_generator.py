"""Generate a reviewable dbt project for components mapped to a Fabric dbt job (offline).

Model bodies are converted GoogleSQL -> T-SQL through the existing converter. Table
references are swapped for placeholder identifiers before conversion and restored as
``ref``/``source`` afterwards, so Jinja never reaches the SQL parser.
"""

from __future__ import annotations

import re
from typing import Any

from ..assessment import AssessmentReport
from ..converter.models import TargetDialect
from ..converter.sql_converter import SqlConverter
from ..mapping import FabricTarget
from ..models import BigQueryInventory, BigQueryObject, ObjectKind

DBT_REASON_CODES = frozenset({
    "model_sql_missing",
    "jinja_macro_review",
    "sql_conversion_failed",
    "incremental_unique_key_missing",
    "incremental_filter_review",
    "assertion_translation_required",
    "test_review",
    "unsafe_identifier",
    "bigquery_macro_review",
})
_SAFE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BACKTICK_TABLE = re.compile(r"`([A-Za-z0-9_\-]+)\.([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)`")
_JINJA_REF = re.compile(r"\{\{\s*ref\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\)\s*\}\}")
_JINJA_SOURCE = re.compile(
    r"\{\{\s*source\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*,\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\)\s*\}\}"
)
_JINJA_CONFIG = re.compile(r"\{\{\s*config\([^}]*\)\s*\}\}")
_PLACEHOLDER = re.compile(r"\[?\b(zz_dbt_(?:ref|src)_\d+)\b\]?")
_BUILTIN_TESTS = {"unique", "not_null"}


def build_dbt_projects(
    inventory: BigQueryInventory, assessment: AssessmentReport
) -> tuple[dict[str, str], dict[str, Any]]:
    """Return ``{relative_path: content}`` and a conversion report for every dbt-job component."""
    objects = {item.source_id: item for item in inventory.objects()}
    by_name = {item.name: item for item in inventory.objects() if item.sql}
    files: dict[str, str] = {}
    projects: list[dict[str, Any]] = []
    for decision in sorted(assessment.decisions, key=lambda value: value.source_id):
        if decision.target is not FabricTarget.DBT_JOB:
            continue
        item = objects[decision.source_id]
        models = _dbt_models(item) if item.kind is ObjectKind.DBT_PROJECT else _dataform_models(
            item, inventory, by_name
        )
        project_files, report = _render_project(item, models, _dbt_tests(item))
        files.update(project_files)
        projects.append(report)
    return files, {"mode": "dry-run", "projectId": inventory.project_id, "projects": projects}


def _dbt_models(item: BigQueryObject) -> list[dict[str, Any]]:
    raw = item.properties.get("models", [])
    return [dict(model) for model in raw if isinstance(model, dict)] if isinstance(raw, list) else []


def _dbt_tests(item: BigQueryObject) -> list[dict[str, Any]]:
    raw = item.properties.get("tests", [])
    return [dict(test) for test in raw if isinstance(test, dict)] if isinstance(raw, list) else []


def _dataform_models(
    item: BigQueryObject, inventory: BigQueryInventory, by_name: dict[str, BigQueryObject]
) -> list[dict[str, Any]]:
    """Collect Dataform targets: compiled ``dataform_model`` objects plus names listed on the workflow."""
    selected: dict[str, BigQueryObject | None] = {
        obj.name: obj for obj in inventory.objects() if obj.properties.get("dataform_model")
    }
    listed = item.properties.get("models", [])
    for entry in listed if isinstance(listed, list) else []:
        name = str(entry.get("name", "")) if isinstance(entry, dict) else str(entry)
        selected.setdefault(name, by_name.get(name))
    models = []
    for name in sorted(selected):
        obj = selected[name]
        incremental = bool(obj and obj.properties.get("incremental"))
        materialized = "incremental" if incremental else (
            "view" if obj and obj.kind is ObjectKind.VIEW else "table"
        )
        models.append({
            "name": name,
            "sql": (obj.sql if obj else "") or "",
            "materialized": materialized,
            "source_object": obj.source_id if obj else None,
            "has_assertions": bool(obj and obj.properties.get("has_assertions")),
            "dataform": True,
        })
    return models


def _render_project(
    item: BigQueryObject, models: list[dict[str, Any]], tests: list[dict[str, Any]]
) -> tuple[dict[str, str], dict[str, Any]]:
    project = re.sub(r"[^a-z0-9_]", "_", item.name.lower()) or "dbt_project"
    if not project[0].isalpha():
        project = f"p_{project}"
    root = f"dbt/{project}"
    model_names = {str(model.get("name", "")) for model in models if _SAFE.match(str(model.get("name", "")))}
    files: dict[str, str] = {}
    model_reports: list[dict[str, Any]] = []
    sources: set[tuple[str, str]] = set()

    for model in sorted(models, key=lambda value: str(value.get("name", ""))):
        name = str(model.get("name", ""))
        if not _SAFE.match(name):
            model_reports.append({"name": name, "reasonCodes": ["unsafe_identifier"]})
            continue
        body, reasons, refs, model_sources = _convert_body(str(model.get("sql", "")), model_names - {name})
        sources.update(model_sources)
        materialized = str(model.get("materialized", "view"))
        config = f"materialized='{materialized}'" if materialized in {"view", "table", "incremental", "ephemeral"} else "materialized='table'"
        if materialized == "incremental":
            unique_key = model.get("unique_key")
            if isinstance(unique_key, str) and _SAFE.match(unique_key):
                config += f", unique_key='{unique_key}'"
            else:
                reasons.add("incremental_unique_key_missing")
            if model.get("dataform"):
                reasons.add("incremental_filter_review")
        if model.get("has_assertions"):
            reasons.add("assertion_translation_required")
        if model.get("macros"):
            reasons.add("bigquery_macro_review")
        files[f"{root}/models/{name}.sql"] = "{{ config(" + config + ") }}\n\n" + body
        model_reports.append({
            "name": name,
            "file": f"models/{name}.sql",
            "materialized": materialized,
            "sourceObject": model.get("source_object") or item.source_id,
            "refs": sorted(refs),
            "sources": sorted(".".join(source) for source in model_sources),
            "reasonCodes": sorted(reasons),
        })

    schema_lines = ["version: 2", "", "models:"]
    test_reasons: list[str] = []
    for report in model_reports:
        if "file" not in report:
            continue
        schema_lines.append(f"  - name: {report['name']}")
        columns: dict[str, list[str]] = {}
        for test in tests:
            if report["name"] not in test.get("models", []):
                continue
            test_name, column = str(test.get("name", "")), str(test.get("column", ""))
            if test_name in _BUILTIN_TESTS and _SAFE.match(column):
                columns.setdefault(column, []).append(test_name)
            else:
                test_reasons.append(f"{report['name']}:{test_name or 'unnamed'}")
        if columns:
            schema_lines.append("    columns:")
            for column in sorted(columns):
                schema_lines.append(f"      - name: {column}")
                schema_lines.append("        tests:")
                schema_lines.extend(f"          - {test}" for test in sorted(set(columns[column])))
    if len(schema_lines) == 3:
        schema_lines[-1] = "models: []"
    files[f"{root}/models/schema.yml"] = "\n".join(schema_lines) + "\n"

    if sources:
        source_lines = ["version: 2", "", "sources:"]
        for schema in sorted({schema for schema, _ in sources}):
            source_lines.extend([f"  - name: {schema}", f"    schema: {schema}", "    tables:"])
            source_lines.extend(f"      - name: {table}" for source, table in sorted(sources) if source == schema)
        files[f"{root}/models/sources.yml"] = "\n".join(source_lines) + "\n"

    files[f"{root}/dbt_project.yml"] = "\n".join([
        f"name: {project}",
        "version: '1.0.0'",
        "config-version: 2",
        f"profile: {project}",
        "model-paths: ['models']",
        "",
    ])
    # Reference-only profile: a Fabric dbt job sets the connection in its own UI.
    files[f"{root}/profiles.yml"] = "\n".join([
        f"{project}:",
        "  target: fabric",
        "  outputs:",
        "    fabric:",
        "      type: fabric",
        "      driver: 'ODBC Driver 18 for SQL Server'",
        "      server: '<warehouse-sql-endpoint>'",
        "      database: '<warehouse-name>'",
        f"      schema: {project}",
        "      authentication: CLI",
        "",
    ])
    reasons = sorted({code for report in model_reports for code in report["reasonCodes"]} | (
        {"test_review"} if test_reasons else set()
    ))
    return files, {
        "sourceId": item.source_id,
        "project": project,
        "root": root,
        "models": model_reports,
        "unconvertedTests": sorted(test_reasons),
        "reasonCodes": reasons,
        "status": "review_required",
    }


def _convert_body(
    sql: str, known_models: set[str]
) -> tuple[str, set[str], set[str], set[tuple[str, str]]]:
    """Convert one model body; return (body, reason codes, refs, sources)."""
    reasons: set[str] = set()
    if not sql.strip():
        reasons.add("model_sql_missing")
        return "-- TODO: source SQL was not captured; write this model by hand.\nselect 1 as placeholder where 1 = 0\n", reasons, set(), set()

    placeholders: dict[str, str] = {}
    refs: set[str] = set()
    sources: set[tuple[str, str]] = set()

    def ref(name: str) -> str:
        token = f"zz_dbt_ref_{len(placeholders)}"
        placeholders[token] = "{{ ref('" + name + "') }}"
        refs.add(name)
        return token

    def source(schema: str, table: str) -> str:
        token = f"zz_dbt_src_{len(placeholders)}"
        placeholders[token] = "{{ source('" + schema + "', '" + table + "') }}"
        sources.add((schema, table))
        return token

    text = _JINJA_CONFIG.sub("", sql)
    text = _JINJA_REF.sub(lambda match: ref(match.group(1)), text)
    text = _JINJA_SOURCE.sub(lambda match: source(match.group(1), match.group(2)), text)
    text = _BACKTICK_TABLE.sub(
        lambda match: ref(match.group(3)) if match.group(3) in known_models else source(match.group(2), match.group(3)),
        text,
    )
    if "{{" in text or "{%" in text:
        reasons.add("jinja_macro_review")
        return _commented(sql, "Jinja beyond ref/source/config needs manual translation."), reasons, refs, sources

    item = BigQueryObject("dbt.model", "model", ObjectKind.SQL_SCRIPT, sql=text)
    converted = SqlConverter().convert(item, TargetDialect.TSQL).target_text
    if not converted or not converted.strip():
        reasons.add("sql_conversion_failed")
        return _commented(sql, "GoogleSQL could not be converted to T-SQL."), reasons, refs, sources
    body = _PLACEHOLDER.sub(lambda match: placeholders.get(match.group(1), match.group(0)), converted)
    return body.strip() + "\n", reasons, refs, sources


def _commented(sql: str, reason: str) -> str:
    lines = [f"-- TODO: MANUAL REVIEW - {reason}", "-- Original source:"]
    lines.extend(f"-- {line}" for line in sql.splitlines())
    lines.append("select 1 as placeholder where 1 = 0")
    return "\n".join(lines) + "\n"
