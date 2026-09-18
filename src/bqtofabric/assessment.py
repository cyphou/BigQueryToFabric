"""Compatibility assessment for a canonical BigQuery inventory."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass

from .mapping import MappingDecision, map_component
from .models import BigQueryInventory, Column
from .sql_assessment import SqlAssessment, assess_sql
from .strategy import StrategyRecommendation, recommend_strategy
from .type_mapping import Compatibility, TypeMapping, map_type


@dataclass(frozen=True, slots=True)
class AssessmentFinding:
    severity: str
    source_id: str
    message: str


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


def run_assessment(inventory: BigQueryInventory) -> AssessmentReport:
    preferences = inventory.metadata.get("preferences", {})
    typed_preferences = preferences if isinstance(preferences, dict) else {}
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
    readiness = {
        Compatibility.DIRECT: 100,
        Compatibility.TRANSFORM: 80,
        Compatibility.REDESIGN: 50,
        Compatibility.UNSUPPORTED: 0,
    }
    for decision in decisions:
        evidence_scores.append(readiness[decision.compatibility])
        if decision.compatibility is Compatibility.REDESIGN:
            findings.append(AssessmentFinding("WARN", decision.source_id, decision.rationale))
        elif decision.compatibility is Compatibility.UNSUPPORTED:
            findings.append(AssessmentFinding("FAIL", decision.source_id, decision.rationale))
        for action in decision.actions:
            findings.append(AssessmentFinding("WARN", decision.source_id, action))
    for mapping in mapped_types:
        evidence_scores.append(readiness[mapping.compatibility])
        if mapping.compatibility in {Compatibility.REDESIGN, Compatibility.UNSUPPORTED}:
            findings.append(AssessmentFinding(
                "WARN" if mapping.compatibility is Compatibility.REDESIGN else "FAIL",
                mapping.source_type,
                mapping.note,
            ))
    for sql_result in sql_assessments:
        evidence_scores.append(readiness[sql_result.compatibility])
        if sql_result.compatibility is Compatibility.REDESIGN:
            findings.append(AssessmentFinding(
                "WARN",
                sql_result.source_id,
                "; ".join(sql_result.notes) or "SQL requires manual redesign.",
            ))
    strategy = recommend_strategy(inventory, decisions)
    component_summary = dict(sorted(Counter(item.kind.value for item in inventory.objects()).items()))
    target_summary = dict(sorted(Counter(item.target.value for item in decisions).items()))
    compatibility_summary = dict(
        sorted(Counter(item.compatibility.value for item in decisions).items())
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
    )


def _walk_columns(columns: tuple[Column, ...]) -> Iterator[Column]:
    for column in columns:
        yield column
        yield from _walk_columns(column.fields)
