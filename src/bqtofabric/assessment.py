"""Compatibility assessment for a canonical BigQuery inventory."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass

from .mapping import MappingDecision, map_component
from .models import BigQueryInventory, BigQueryObject, Column, ObjectKind
from .parity import assess_parity
from .sql_assessment import SqlAssessment, assess_sql
from .strategy import StrategyRecommendation, recommend_strategy
from .type_mapping import Compatibility, TypeMapping, map_type


@dataclass(frozen=True, slots=True)
class AssessmentFinding:
    severity: str
    source_id: str
    message: str
    code: str = ""
    category: str = ""


@dataclass(frozen=True, slots=True)
class AssessmentReport:
    project_id: str
    score: int
    component_summary: dict[str, int]
    target_summary: dict[str, int]
    compatibility_summary: dict[str, int]
    decisions: tuple[MappingDecision, ...]
    strategy: StrategyRecommendation
    type_mappings: tuple[TypeMapping, ...]
    sql_assessments: tuple[SqlAssessment, ...]
    findings: tuple[AssessmentFinding, ...]
    evidence_summary: dict[str, dict[str, object]]
    evidence_coverage: int
    parity_summary: dict[str, dict[str, object]]
    discovery_coverage: dict[str, int]


def run_assessment(inventory: BigQueryInventory) -> AssessmentReport:
    preferences = inventory.metadata.get("preferences", {})
    typed_preferences = preferences if isinstance(preferences, dict) else {}
    streaming_consumers = _streaming_consumers(inventory)
    decisions = tuple(map_component(item, typed_preferences) for item in inventory.objects())
    mapped_types = tuple(
        map_type(column.data_type)
        for item in inventory.objects()
        for column in _walk_columns(item.columns)
    )
    sql_assessments = tuple(
        result
        for item, decision in zip(inventory.objects(), decisions, strict=True)
        if (result := assess_sql(item, decision)) is not None
    )
    findings: list[AssessmentFinding] = []
    evidence_scores: list[int] = []
    evidence_summary: dict[str, dict[str, object]] = {}
    parity_summary: dict[str, dict[str, object]] = {}
    readiness = {
        Compatibility.DIRECT: 100,
        Compatibility.TRANSFORM: 80,
        Compatibility.REDESIGN: 50,
        Compatibility.UNSUPPORTED: 0,
    }
    for decision in decisions:
        evidence_scores.append(readiness[decision.compatibility])
        if decision.compatibility is Compatibility.REDESIGN:
            findings.append(AssessmentFinding(
                "WARN", decision.source_id, decision.rationale, "MAPPING_REDESIGN", "mapping"
            ))
        elif decision.compatibility is Compatibility.UNSUPPORTED:
            findings.append(AssessmentFinding(
                "FAIL", decision.source_id, decision.rationale, "MAPPING_UNSUPPORTED", "mapping"
            ))
        for action in decision.actions:
            findings.append(AssessmentFinding(
                "WARN", decision.source_id, action, "ACTION_REQUIRED", "mapping"
            ))
        if decision.source_id in streaming_consumers:
            findings.append(AssessmentFinding(
                "WARN",
                decision.source_id,
                "Upstream streaming ingestion requires deduplication, idempotency, and "
                "out-of-order delivery review.",
                "STREAMING_DOWNSTREAM_REVIEW",
                "processing",
            ))
    for index, item in enumerate(inventory.objects()):
        parity = assess_parity(item.properties, applicable=bool(item.columns))
        parity_summary[item.source_id] = parity
        if parity["status"] == "failed":
            findings.append(AssessmentFinding(
                "FAIL", item.source_id, "Parity evidence failed.", "PARITY_FAILED", "parity"
            ))
        if (
            item.kind is ObjectKind.SECURITY_POLICY
            and item.properties.get("evidence_scope") == "dataset_access_entry"
        ):
            findings.append(AssessmentFinding(
                "FAIL",
                item.source_id,
                "Dataset ACL entries are not proof of effective project, organization, group, or "
                "inherited IAM access and require security review.",
                "SECURITY_EFFECTIVE_ACCESS_REVIEW",
                "security",
            ))
        required = _required_evidence(item.kind)
        missing = _missing_evidence(item)
        present = tuple(field_name for field_name in required if field_name not in missing)
        coverage = round(100 * len(present) / len(required)) if required else 100
        evidence_summary[item.source_id] = {
            "kind": item.kind.value,
            "discovered_from": item.discovered_from,
            "required": list(required),
            "present": list(present),
            "missing": list(missing),
            "coverage": coverage,
        }
        evidence_scores[index] = max(
            0,
            readiness[decisions[index].compatibility] - round((100 - coverage) / 4),
        )
        if item.discovered_from == "external_payload" and missing:
            findings.append(AssessmentFinding(
                "FAIL",
                item.source_id,
                f"{item.kind.value} is missing required offline evidence: {', '.join(missing)}. "
                "The live adapter is not implemented, so offline evidence must be completed.",
                "EXTERNAL_PAYLOAD_INCOMPLETE_ADAPTER",
                "adapter",
            ))
        findings.extend(
            AssessmentFinding(
                "FAIL" if item.kind is ObjectKind.SECURITY_POLICY else "WARN",
                item.source_id,
                f"Assessment evidence missing: {field_name}.",
                "SECURITY_EVIDENCE_MISSING" if item.kind is ObjectKind.SECURITY_POLICY
                else "EVIDENCE_MISSING",
                "security" if item.kind is ObjectKind.SECURITY_POLICY else "evidence",
            )
            for field_name in missing
        )
    for mapping in mapped_types:
        evidence_scores.append(readiness[mapping.compatibility])
        if mapping.compatibility in {Compatibility.REDESIGN, Compatibility.UNSUPPORTED}:
            findings.append(AssessmentFinding(
                "WARN" if mapping.compatibility is Compatibility.REDESIGN else "FAIL",
                mapping.source_type,
                mapping.note,
                "TYPE_REDESIGN" if mapping.compatibility is Compatibility.REDESIGN
                else "TYPE_UNSUPPORTED",
                "schema",
            ))
    for sql_result in sql_assessments:
        evidence_scores.append(readiness[sql_result.compatibility])
        if sql_result.compatibility is Compatibility.REDESIGN:
            findings.append(AssessmentFinding(
                "WARN",
                sql_result.source_id,
                "; ".join(sql_result.notes) or "SQL requires manual redesign.",
                "SQL_REDESIGN",
                "sql",
            ))
    strategy = recommend_strategy(inventory, decisions)
    component_summary = dict(sorted(Counter(item.kind.value for item in inventory.objects()).items()))
    target_summary = dict(sorted(Counter(item.target.value for item in decisions).items()))
    compatibility_summary = dict(
        sorted(Counter(item.compatibility.value for item in decisions).items())
    )
    discovery_coverage = dict(
        sorted(Counter(getattr(item, "discovered_from", "") for item in inventory.objects()).items())
    )
    return AssessmentReport(
        inventory.project_id,
        round(sum(evidence_scores) / len(evidence_scores)) if evidence_scores else 0,
        component_summary,
        target_summary,
        compatibility_summary,
        decisions,
        strategy,
        mapped_types,
        sql_assessments,
        tuple(findings),
        dict(sorted(evidence_summary.items())),
        round(sum(item["coverage"] for item in evidence_summary.values()) / len(evidence_summary))
        if evidence_summary else 100,
        dict(sorted(parity_summary.items())),
        discovery_coverage,
    )


def _walk_columns(columns: tuple[Column, ...]) -> Iterator[Column]:
    for column in columns:
        yield column
        yield from _walk_columns(column.fields)


def _streaming_consumers(inventory: BigQueryInventory) -> set[str]:
    objects = {item.source_id: item for item in inventory.objects()}
    streaming_sources = {
        item.source_id
        for item in objects.values()
        if item.kind is ObjectKind.DATAFLOW_JOB and item.properties.get("streaming") is True
    }
    consumers: set[str] = set()
    remaining = set(streaming_sources)
    while remaining:
        dependency = remaining.pop()
        direct_consumers = {
            item.source_id
            for item in objects.values()
            if dependency in item.dependencies and item.source_id not in consumers
        }
        consumers.update(direct_consumers)
        remaining.update(direct_consumers)
    return consumers


def _missing_evidence(item: BigQueryObject) -> tuple[str, ...]:
    return tuple(
        field_name
        for field_name in _required_evidence(item.kind)
        if not _has_evidence(item.properties.get(field_name))
    )


def _required_evidence(kind: ObjectKind) -> tuple[str, ...]:
    required: dict[ObjectKind, tuple[str, ...]] = {
        ObjectKind.SPARK_JOB: ("language", "runtime_version"),
        ObjectKind.DATAPROC_JOB: ("language", "runtime_version"),
        ObjectKind.DATAFLOW_JOB: ("streaming", "portable", "connector_compatible"),
        ObjectKind.COMPOSER_DAG: ("operators", "runtime_version", "connections"),
        ObjectKind.DATAFORM_WORKFLOW: ("models", "assertions", "incremental"),
        ObjectKind.LOOKER_ASSET: ("explores", "measures", "joins"),
        ObjectKind.BQML_MODEL: ("model_type", "features", "evaluation_metrics"),
        ObjectKind.VERTEX_AI_PIPELINE: ("pipeline_steps", "models", "endpoints"),
        ObjectKind.SECURITY_POLICY: ("policy_type",),
        ObjectKind.CLOUD_SQL_DATABASE: ("engine", "version", "replication"),
        ObjectKind.SPANNER_DATABASE: ("dialect", "replication", "change_streams"),
    }
    return required.get(kind, ())


def _has_evidence(value: object) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, (str, bytes, list, tuple, dict, set)):
        return bool(value)
    return True
