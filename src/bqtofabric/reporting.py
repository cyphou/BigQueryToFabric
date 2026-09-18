"""Deterministic migration reports and dry-run Fabric artifact generation."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .airflow_compatibility import assess_airflow_compatibility
from .artifact_validation import validate_directory
from .assessment import AssessmentReport
from .dataform_conversion import convert_dataform_workflow
from .deployment_manifest import build_manifest
from .fabric_artifacts import build_specialized_artifacts
from .mapping import FabricTarget, MappingDecision
from .models import BigQueryInventory
from .planner import MigrationPlan, PlanItem
from .spark_conversion import convert_spark_job


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_reports(
    output_dir: str | Path,
    inventory: BigQueryInventory,
    assessment: AssessmentReport,
    plan: MigrationPlan,
    include_fabric_artifacts: bool = False,
) -> tuple[Path, ...]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    assessment_path = root / "assessment.json"
    _write_json(assessment_path, asdict(assessment))
    written.append(assessment_path)

    plan_path = root / "migration-plan.json"
    _write_json(plan_path, asdict(plan))
    written.append(plan_path)

    mapping_path = root / "component-mapping.csv"
    with mapping_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow((
            "source_id", "source_kind", "target", "supporting_targets",
            "compatibility", "rationale", "actions",
        ))
        for decision in sorted(assessment.decisions, key=lambda item: item.source_id):
            writer.writerow((
                decision.source_id,
                decision.source_kind,
                decision.target,
                ";".join(target.value for target in decision.supporting_targets),
                decision.compatibility,
                decision.rationale,
                ";".join(decision.actions),
            ))
    written.append(mapping_path)

    markdown_path = root / "migration-plan.md"
    lines = [
        f"# Migration plan: {plan.project_id}",
        "",
        f"- Readiness score: {assessment.score}/100",
        f"- Evidence coverage: {assessment.evidence_coverage}%",
        f"- Primary target: {assessment.strategy.primary_target.value}",
        f"- Architecture: {plan.architecture}",
        "",
        "## Portfolio summary",
        "",
        f"- Components: {sum(assessment.component_summary.values())}",
        "- Source types: " + ", ".join(
            f"{kind}={count}" for kind, count in assessment.component_summary.items()
        ),
        "- Primary targets: " + ", ".join(
            f"{target}={count}" for target, count in assessment.target_summary.items()
        ),
        "- Compatibility: " + ", ".join(
            f"{level}={count}" for level, count in assessment.compatibility_summary.items()
        ),
        "",
        "## Component assessment",
        "",
        "| GCP component | Primary target | Supporting targets | Compatibility |",
        "|---|---|---|---|",
    ]
    for decision in sorted(assessment.decisions, key=lambda item: item.source_id):
        supporting = ", ".join(target.value for target in decision.supporting_targets) or "-"
        lines.append(
            f"| `{decision.source_id}` | {decision.target.value} | {supporting} | "
            f"{decision.compatibility.value} |"
        )
    lines.extend([
        "",
        "## Evidence coverage",
        "",
        "| Component | Coverage | Missing evidence |",
        "|---|---:|---|",
    ])
    for source_id, evidence in assessment.evidence_summary.items():
        missing = ", ".join(evidence["missing"]) or "-"
        lines.append(f"| `{source_id}` | {evidence['coverage']}% | {missing} |")
    lines.extend([
        "",
        "## Parity evidence",
        "",
        "| Component | Status |",
        "|---|---|",
    ])
    for source_id, parity in assessment.parity_summary.items():
        lines.append(f"| `{source_id}` | {parity['status']} |")
    lines.extend([
        "",
        "## Migration waves",
        "",
        "| Wave | BigQuery object | Fabric target | Manual review | Review reasons |",
        "|---:|---|---|---|---|",
    ])
    for item in plan.items:
        reasons = ", ".join(item.manual_review_reasons) or "-"
        lines.append(f"| {item.wave} | `{item.source_id}` | {item.target.value} | "
                     f"{'yes' if item.manual_review else 'no'} | {reasons} |")
    if plan.unresolved_dependencies:
        lines.extend(("", "## Unresolved dependencies", ""))
        lines.extend(f"- {message}" for message in plan.unresolved_dependencies)
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    written.append(markdown_path)

    lineage_path = root / "lineage.mmd"
    graph = ["flowchart LR"]
    for item in sorted(inventory.objects(), key=lambda value: value.source_id):
        node = _mermaid_id(item.source_id)
        graph.append(f'    {node}["{item.source_id}"]')
        for dependency in sorted(item.dependencies):
            graph.append(f"    {_mermaid_id(dependency)} --> {node}")
    lineage_path.write_text("\n".join(graph) + "\n", encoding="utf-8")
    written.append(lineage_path)

    if include_fabric_artifacts:
        written.extend(_write_fabric_artifacts(root / "fabric", inventory, assessment, plan))
    return tuple(written)


def _mermaid_id(source_id: str) -> str:
    return "n_" + "".join(character if character.isalnum() else "_" for character in source_id)


def _write_fabric_artifacts(
    root: Path, inventory: BigQueryInventory, assessment: AssessmentReport, plan: MigrationPlan
) -> tuple[Path, ...]:
    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    targets = {decision.source_id: decision.target for decision in assessment.decisions}

    sql_lines = ["-- Generated migration skeleton. Review before execution."]
    for item in sorted(inventory.objects(), key=lambda value: value.source_id):
        if targets[item.source_id] is FabricTarget.WAREHOUSE and item.columns:
            sql_lines.append(f"-- TODO: CREATE TABLE [{item.dataset}].[{item.name}] with mapped types")
    sql_path = root / "warehouse.sql"
    sql_path.write_text("\n".join(sql_lines) + "\n", encoding="utf-8")
    written.append(sql_path)

    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {"language": "markdown"},
                "source": ["# BigQuery to Fabric Lakehouse migration skeleton\n"],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {"language": "python"},
                "outputs": [],
                "source": ["# TODO: use a Fabric Pipeline Copy activity to land BigQuery data.\n"],
            },
        ],
        "metadata": {"language_info": {"name": "python"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    notebook_path = root / "lakehouse_transform.ipynb"
    _write_json(notebook_path, notebook)
    written.append(notebook_path)

    pipeline = {
        "displayName": f"{inventory.project_id}-migration",
        "mode": "dry-run",
        "activities": [
            {"name": "copy_bigquery_to_onelake", "type": "Copy", "status": "skeleton"},
            {"name": "validate_parity", "type": "Notebook", "status": "skeleton"},
        ],
    }
    pipeline_path = root / "pipeline.json"
    _write_json(pipeline_path, pipeline)
    written.append(pipeline_path)

    sql_conversions = {
        "mode": "dry-run",
        "conversions": [
            {
                "sourceId": result.source_id,
                "targetDialect": result.target_language,
                "compatibility": result.compatibility.value,
                "features": list(result.features),
                "warnings": list(result.notes),
                "convertedSql": result.converted_sql,
            }
            for result in sorted(assessment.sql_assessments, key=lambda item: item.source_id)
        ],
    }
    sql_conversions_path = root / "sql-conversions.json"
    _write_json(sql_conversions_path, sql_conversions)
    written.append(sql_conversions_path)

    spark_conversions = {
        "mode": "dry-run",
        "conversions": [
            convert_spark_job(item)
            for item in sorted(inventory.objects(), key=lambda value: value.source_id)
            if item.kind.value in {"spark_job", "dataproc_job"}
        ],
    }
    spark_conversions_path = root / "spark-conversions.json"
    _write_json(spark_conversions_path, spark_conversions)
    written.append(spark_conversions_path)

    dataform_conversions = {
        "mode": "dry-run",
        "conversions": [
            convert_dataform_workflow(item)
            for item in sorted(inventory.objects(), key=lambda value: value.source_id)
            if item.kind.value == "dataform_workflow"
        ],
    }
    dataform_conversions_path = root / "dataform-conversions.json"
    _write_json(dataform_conversions_path, dataform_conversions)
    written.append(dataform_conversions_path)

    airflow_compatibility = {
        "mode": "dry-run",
        "reports": [
            assess_airflow_compatibility(item)
            for item in sorted(inventory.objects(), key=lambda value: value.source_id)
            if item.kind.value == "composer_dag"
        ],
    }
    airflow_compatibility_path = root / "airflow-compatibility.json"
    _write_json(airflow_compatibility_path, airflow_compatibility)
    written.append(airflow_compatibility_path)

    for artifact_type, artifact in build_specialized_artifacts(
        inventory, assessment.decisions
    ).items():
        artifact_path = root / f"{artifact_type}.json"
        _write_json(artifact_path, artifact)
        written.append(artifact_path)

    plan_items = {item.source_id: item for item in plan.items}
    objects = {item.source_id: item for item in inventory.objects()}
    orchestration = {
        "mode": "dry-run",
        "candidates": [
            {
                "sourceId": decision.source_id,
                "wave": plan_items[decision.source_id].wave,
                "dependencies": list(objects[decision.source_id].dependencies),
                "primaryTarget": decision.target.value,
                "supportingTargets": [target.value for target in decision.supporting_targets],
                "actions": list(decision.actions),
            }
            for decision in sorted(assessment.decisions, key=lambda item: item.source_id)
            if decision.target in {FabricTarget.AIRFLOW_JOB, FabricTarget.DATA_PIPELINE}
            or FabricTarget.DATA_PIPELINE in decision.supporting_targets
        ],
    }
    orchestration_path = root / "orchestration.json"
    _write_json(orchestration_path, orchestration)
    written.append(orchestration_path)

    target_manifest = {
        "mode": "dry-run",
        "projectId": inventory.project_id,
        "stageReadiness": _stage_readiness_summary(assessment.decisions, plan_items),
        "entries": [
            {
                "sourceId": decision.source_id,
                "sourceKind": decision.source_kind.value,
                "processingStage": _processing_stage(decision.source_kind.value),
                "wave": plan_items[decision.source_id].wave,
                "dependencies": list(objects[decision.source_id].dependencies),
                "manualReview": plan_items[decision.source_id].manual_review,
                "manualReviewReasons": list(plan_items[decision.source_id].manual_review_reasons),
                "primaryTarget": decision.target.value,
                "supportingTargets": [target.value for target in decision.supporting_targets],
                "compatibility": decision.compatibility.value,
                "actions": list(decision.actions),
                "artifactKind": _artifact_kind(decision.target),
            }
            for decision in sorted(assessment.decisions, key=lambda item: item.source_id)
        ],
    }
    target_manifest_path = root / "target-manifest.json"
    _write_json(target_manifest_path, target_manifest)
    written.append(target_manifest_path)

    validation_path = root / "artifact-validation.json"
    _write_json(validation_path, validate_directory(root))
    written.append(validation_path)

    parity_path = root / "parity-evidence.json"
    _write_json(parity_path, {
        "mode": "offline-evidence",
        "projectId": inventory.project_id,
        "objects": [
            {"sourceId": source_id, **parity}
            for source_id, parity in assessment.parity_summary.items()
        ],
    })
    written.append(parity_path)

    manifest_path = root / "deployment-manifest.json"
    _write_json(manifest_path, build_manifest(inventory, assessment, plan))
    written.append(manifest_path)
    return tuple(written)


def _artifact_kind(target: FabricTarget) -> str:
    artifact_kinds = {
        FabricTarget.AIRFLOW_JOB: "airflow_package",
        FabricTarget.DATAFLOW_GEN2: "dataflow_gen2_definition",
        FabricTarget.DATA_PIPELINE: "fabric_pipeline",
        FabricTarget.EVENTHOUSE: "eventhouse_kql",
        FabricTarget.EVENTSTREAM: "eventstream_definition",
        FabricTarget.SEMANTIC_MODEL: "semantic_model_definition",
        FabricTarget.DATA_SCIENCE: "data_science_workbench",
        FabricTarget.PURVIEW: "purview_governance_mapping",
        FabricTarget.SQL_DATABASE: "sql_database_migration_spec",
        FabricTarget.ONELAKE_SHORTCUT: "onelake_shortcut_spec",
        FabricTarget.WAREHOUSE: "warehouse_ddl",
        FabricTarget.LAKEHOUSE: "lakehouse_notebook",
        FabricTarget.NOTEBOOK: "fabric_notebook",
        FabricTarget.POWER_BI_REPORT: "power_bi_report_spec",
        FabricTarget.MANUAL: "manual_migration_record",
    }
    return artifact_kinds[target]


def _processing_stage(source_kind: str) -> str:
    stages = {
        "gcs_source": "ingestion",
        "pubsub_topic": "ingestion",
        "stream": "ingestion",
        "external_table": "ingestion",
        "dataflow_job": "ingestion",
        "table": "storage",
        "view": "transformation",
        "materialized_view": "transformation",
        "sql_script": "transformation",
        "spark_job": "transformation",
        "dataproc_job": "transformation",
        "dataform_workflow": "transformation",
        "routine": "transformation",
        "procedure": "transformation",
        "scheduled_query": "orchestration",
        "bigquery_job": "orchestration",
        "composer_dag": "orchestration",
        "workflow": "orchestration",
        "looker_asset": "consumption",
        "bqml_model": "consumption",
        "vertex_ai_pipeline": "consumption",
        "dataplex_asset": "governance",
        "security_policy": "governance",
        "connection": "integration",
        "cloud_sql_database": "operational",
        "spanner_database": "operational",
    }
    return stages.get(source_kind, "other")


def _stage_readiness_summary(
    decisions: tuple[MappingDecision, ...], plan_items: dict[str, PlanItem]
) -> dict[str, dict[str, int]]:
    weights = {"direct": 100, "transform": 80, "redesign": 50, "unsupported": 0}
    summaries: dict[str, dict[str, int]] = {}
    for decision in decisions:
        stage = _processing_stage(decision.source_kind.value)
        summary = summaries.setdefault(stage, {
            "total": 0,
            "direct": 0,
            "transform": 0,
            "redesign": 0,
            "unsupported": 0,
            "manualReview": 0,
            "readiness": 0,
        })
        summary["total"] += 1
        summary[decision.compatibility.value] += 1
        if plan_items[decision.source_id].manual_review:
            summary["manualReview"] += 1
    for summary in summaries.values():
        summary["readiness"] = round(
            sum(summary[compatibility] * weight for compatibility, weight in weights.items())
            / summary["total"]
        )
    return dict(sorted(summaries.items()))
