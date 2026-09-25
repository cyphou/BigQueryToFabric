"""Create deterministic migration waves from assessed dependencies."""

from __future__ import annotations

from collections import Counter
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
class MigrationWave:
    """A reviewer-facing migration decision derived from ordered plan items."""

    wave: int
    source_ids: tuple[str, ...]
    target_summary: tuple[tuple[str, int], ...]
    dependency_waves: tuple[int, ...]
    status: str
    manual_review_count: int
    approval_status: str = "pending_review"
    owner: str = "unassigned"
    effort_band: str = "S"
    blockers: tuple[str, ...] = ()
    entry_criteria: tuple[str, ...] = ()
    exit_criteria: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    project_id: str
    architecture: str
    items: tuple[PlanItem, ...]
    unresolved_dependencies: tuple[str, ...]
    waves: tuple[MigrationWave, ...] = ()


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
    incomplete_dataform_sources = {
        finding.source_id
        for finding in assessment.findings
        if finding.code == "DATAFORM_COMPILATION_DETAILS_UNAVAILABLE"
    }
    parity_failed_sources = {
        finding.source_id
        for finding in assessment.findings
        if finding.code == "PARITY_FAILED"
    }
    security_review_sources = {
        finding.source_id
        for finding in assessment.findings
        if finding.code in {"SECURITY_EFFECTIVE_ACCESS_REVIEW", "SECURITY_EVIDENCE_MISSING"}
    }
    missing_evidence_sources = {
        finding.source_id
        for finding in assessment.findings
        if finding.code == "EVIDENCE_MISSING"
    }
    assisted_evidence_sources = {
        finding.source_id
        for finding in assessment.findings
        if finding.code in {"ASSISTED_EVIDENCE_UNVERIFIED", "ASSISTED_EVIDENCE_INCOMPLETE"}
    }
    remaining = set(objects)
    completed: set[str] = set()
    incomplete_adapter_dependencies: set[str] = set()
    incomplete_dataform_dependencies: set[str] = set()
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
            depends_on_incomplete_external_adapter = (
                source_id in incomplete_adapter_sources
                or any(dep in incomplete_adapter_dependencies for dep in objects[source_id].dependencies)
            )
            depends_on_incomplete_dataform_compilation = (
                source_id in incomplete_dataform_sources
                or any(dep in incomplete_dataform_dependencies for dep in objects[source_id].dependencies)
            )
            reasons: list[str] = []
            if external:
                reasons.append("external_dependency")
            if decisions[source_id].compatibility.value in {"redesign", "unsupported"}:
                reasons.append("incompatible_mapping")
            if source_id in streaming_review_sources:
                reasons.append("streaming_downstream_review")
            # Independent checks: a component can require review for several reasons at
            # once, and suppressing the others would understate the cause counts.
            if source_id in incomplete_adapter_sources:
                reasons.append("incomplete_external_adapter")
            if source_id in incomplete_dataform_sources:
                reasons.append("incomplete_dataform_compilation")
            if (
                depends_on_incomplete_external_adapter
                and source_id not in incomplete_adapter_sources
            ):
                reasons.append("depends_on_incomplete_external_adapter")
            if (
                depends_on_incomplete_dataform_compilation
                and source_id not in incomplete_dataform_sources
            ):
                reasons.append("depends_on_incomplete_dataform_compilation")
            if source_id in parity_failed_sources:
                reasons.append("parity_failed")
            if source_id in security_review_sources:
                reasons.append("security_review")
            if source_id in missing_evidence_sources:
                reasons.append("missing_required_evidence")
            if source_id in assisted_evidence_sources:
                reasons.append("assisted_evidence")
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
        incomplete_dataform_dependencies.update(
            source_id
            for source_id in ready
            if source_id in incomplete_dataform_sources
            or any(dep in incomplete_dataform_dependencies for dep in objects[source_id].dependencies)
        )
        completed.update(ready)
        remaining.difference_update(ready)
        wave += 1

    plan_items_tuple = tuple(plan_items)
    plan = MigrationPlan(
        inventory.project_id,
        assessment.strategy.architecture,
        plan_items_tuple,
        tuple(sorted(unresolved)),
    )
    return MigrationPlan(
        plan.project_id,
        plan.architecture,
        plan.items,
        plan.unresolved_dependencies,
        build_migration_waves(plan, inventory),
    )


def build_migration_waves(
    plan: MigrationPlan, inventory: BigQueryInventory
) -> tuple[MigrationWave, ...]:
    """Group plan items into deterministic, reviewer-facing migration waves."""
    objects = {item.source_id: item for item in inventory.objects()}
    item_by_source = {item.source_id: item for item in plan.items}
    grouped: dict[int, list[PlanItem]] = {}
    for item in plan.items:
        grouped.setdefault(item.wave, []).append(item)

    waves: list[MigrationWave] = []
    for wave_number in sorted(grouped):
        items = sorted(grouped[wave_number], key=lambda item: item.source_id)
        source_ids = tuple(item.source_id for item in items)
        target_counts = Counter(item.target.value for item in items)
        dependency_waves = sorted({
            item_by_source[dependency].wave
            for item in items
            for dependency in objects[item.source_id].dependencies
            if dependency in item_by_source and item_by_source[dependency].wave < wave_number
        })
        blockers = sorted({
            f"{item.source_id}:{reason}"
            for item in items
            for reason in item.manual_review_reasons
        })
        blockers.extend(sorted(
            message for message in plan.unresolved_dependencies
            if any(source_id in message for source_id in source_ids)
        ))
        blockers = sorted(set(blockers))
        status = "blocked" if blockers else "ready_for_review"
        waves.append(MigrationWave(
            wave=wave_number,
            source_ids=source_ids,
            target_summary=tuple(sorted(target_counts.items())),
            dependency_waves=tuple(dependency_waves),
            status=status,
            manual_review_count=sum(item.manual_review for item in items),
            effort_band=_effort_band(items, blockers),
            blockers=tuple(blockers),
            entry_criteria=(
                "All dependency waves are resolved before approval.",
                "Required source evidence is present or explicitly marked for review.",
            ),
            exit_criteria=(
                "All wave artifacts pass structural validation.",
                "Parity evidence is supplied or explicitly accepted as not_applicable.",
            ),
        ))
    return tuple(waves)


def _effort_band(items: list[PlanItem], blockers: list[str]) -> str:
    """Estimate a coarse review effort without pretending to measure delivery cost."""
    score = len(items) + len(blockers)
    score += sum(item.target.value in {"manual", "data_pipeline", "eventstream"} for item in items)
    if score >= 12:
        return "XL"
    if score >= 7:
        return "L"
    if score >= 3:
        return "M"
    return "S"
