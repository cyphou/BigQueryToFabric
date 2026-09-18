"""Create deterministic migration waves from assessed dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from .assessment import AssessmentReport
from .mapping import FabricTarget
from .models import BigQueryInventory


@dataclass(frozen=True, slots=True)
class PlanItem:
    source_id: str
    target: FabricTarget
    wave: int
    manual_review: bool
    manual_review_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    project_id: str
    architecture: str
    items: tuple[PlanItem, ...]
    unresolved_dependencies: tuple[str, ...]


def build_plan(inventory: BigQueryInventory, assessment: AssessmentReport) -> MigrationPlan:
    objects = {item.source_id: item for item in inventory.objects()}
    decisions = {item.source_id: item for item in assessment.decisions}
    sql_assessments = {item.source_id: item for item in assessment.sql_assessments}
    streaming_review_sources = {
        finding.source_id
        for finding in assessment.findings
        if finding.code == "STREAMING_DOWNSTREAM_REVIEW"
    }
    incomplete_adapter_sources = {
        finding.source_id
        for finding in assessment.findings
        if finding.code == "EXTERNAL_PAYLOAD_INCOMPLETE_ADAPTER"
    }
    remaining = set(objects)
    completed: set[str] = set()
    incomplete_adapter_dependencies: set[str] = set()
    plan_items: list[PlanItem] = []
    unresolved: set[str] = set()
    wave = 1

    while remaining:
        ready = sorted(source_id for source_id in remaining
                       if all(dep in completed or dep not in objects
                              for dep in objects[source_id].dependencies))
        if not ready:
            for source_id in sorted(remaining):
                unresolved.add(f"Cycle or unresolved dependency for {source_id}")
                plan_items.append(PlanItem(
                    source_id,
                    decisions[source_id].target,
                    wave,
                    True,
                    ("cycle_or_unresolved_dependency",),
                ))
            break
        for source_id in ready:
            external = [dep for dep in objects[source_id].dependencies if dep not in objects]
            unresolved.update(f"External dependency {dep} required by {source_id}" for dep in external)
            depends_on_incomplete_adapter = (
                source_id in incomplete_adapter_sources
                or any(dep in incomplete_adapter_dependencies for dep in objects[source_id].dependencies)
            )
            reasons: list[str] = []
            if external:
                reasons.append("external_dependency")
            if decisions[source_id].compatibility.value in {"redesign", "unsupported"}:
                reasons.append("incompatible_mapping")
            if source_id in streaming_review_sources:
                reasons.append("streaming_downstream_review")
            if source_id in incomplete_adapter_sources:
                reasons.append("incomplete_external_adapter")
            elif depends_on_incomplete_adapter:
                reasons.append("depends_on_incomplete_external_adapter")
            sql_assessment = sql_assessments.get(source_id)
            if sql_assessment and sql_assessment.compatibility.value in {"redesign", "unsupported"}:
                reasons.append("sql_incompatibility")
            plan_items.append(PlanItem(
                source_id,
                decisions[source_id].target,
                wave,
                bool(reasons),
                tuple(reasons),
            ))
        incomplete_adapter_dependencies.update(
            source_id
            for source_id in ready
            if source_id in incomplete_adapter_sources
            or any(dep in incomplete_adapter_dependencies for dep in objects[source_id].dependencies)
        )
        completed.update(ready)
        remaining.difference_update(ready)
        wave += 1

    return MigrationPlan(
        inventory.project_id,
        assessment.strategy.architecture,
        tuple(plan_items),
        tuple(sorted(unresolved)),
    )
