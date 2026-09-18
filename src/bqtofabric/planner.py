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
    remaining = set(objects)
    completed: set[str] = set()
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
                plan_items.append(PlanItem(source_id, decisions[source_id].target, wave, True))
            break
        for source_id in ready:
            external = [dep for dep in objects[source_id].dependencies if dep not in objects]
            unresolved.update(f"External dependency {dep} required by {source_id}" for dep in external)
            plan_items.append(PlanItem(
                source_id,
                decisions[source_id].target,
                wave,
                bool(external)
                or decisions[source_id].compatibility.value in {"redesign", "unsupported"}
                or source_id in streaming_review_sources
                or sql_assessments.get(source_id, None) is not None
                and sql_assessments[source_id].compatibility.value in {"redesign", "unsupported"},
            ))
        completed.update(ready)
        remaining.difference_update(ready)
        wave += 1

    return MigrationPlan(
        inventory.project_id,
        assessment.strategy.architecture,
        tuple(plan_items),
        tuple(sorted(unresolved)),
    )
