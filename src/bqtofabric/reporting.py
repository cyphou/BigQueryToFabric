"""Deterministic migration reports and dry-run Fabric artifact generation."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .assessment import AssessmentReport
from .mapping import FabricTarget
from .models import BigQueryInventory
from .planner import MigrationPlan


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
        "## Migration waves",
        "",
        "| Wave | BigQuery object | Fabric target | Manual review |",
        "|---:|---|---|---|",
    ])
    for item in plan.items:
        lines.append(f"| {item.wave} | `{item.source_id}` | {item.target.value} | "
                     f"{'yes' if item.manual_review else 'no'} |")
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
        written.extend(_write_fabric_artifacts(root / "fabric", inventory, assessment))
    return tuple(written)


def _mermaid_id(source_id: str) -> str:
    return "n_" + "".join(character if character.isalnum() else "_" for character in source_id)


def _write_fabric_artifacts(
    root: Path, inventory: BigQueryInventory, assessment: AssessmentReport
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

    orchestration = {
        "mode": "dry-run",
        "candidates": [
            {
                "sourceId": decision.source_id,
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
        "entries": [
            {
                "sourceId": decision.source_id,
                "sourceKind": decision.source_kind.value,
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
