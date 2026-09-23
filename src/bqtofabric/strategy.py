"""Explainable selection of the primary Microsoft Fabric target."""

from __future__ import annotations

from dataclasses import dataclass

from .mapping import FabricTarget, MappingDecision
from .models import BigQueryInventory
from .type_mapping import Compatibility


@dataclass(frozen=True, slots=True)
class StrategySignal:
    target: FabricTarget
    weight: int
    reason: str


@dataclass(frozen=True, slots=True)
class StrategyRecommendation:
    primary_target: FabricTarget
    architecture: str
    scores: dict[FabricTarget, int]
    signals: tuple[StrategySignal, ...]


_CANDIDATE_TARGETS = (
    FabricTarget.WAREHOUSE,
    FabricTarget.LAKEHOUSE,
    FabricTarget.EVENTHOUSE,
)

# A target is only as good as the evidence that the workload can actually run there.
_COMPATIBILITY_WEIGHT = {
    Compatibility.DIRECT: 3,
    Compatibility.TRANSFORM: 2,
    Compatibility.REDESIGN: 1,
    Compatibility.UNSUPPORTED: 0,
}


def recommend_strategy(
    inventory: BigQueryInventory, decisions: tuple[MappingDecision, ...]
) -> StrategyRecommendation:
    signals: list[StrategySignal] = []
    for decision in decisions:
        weight = _COMPATIBILITY_WEIGHT[decision.compatibility]
        signals.append(StrategySignal(
            decision.target,
            weight,
            f"{decision.rationale} (weight {weight} from {decision.compatibility.value} "
            "compatibility)",
        ))

    preferences = inventory.metadata.get("preferences", {})
    preferred = preferences.get("data_target") if isinstance(preferences, dict) else None
    if preferred == "lakehouse":
        signals.append(StrategySignal(
            FabricTarget.LAKEHOUSE,
            3,
            "Lakehouse is the stated preferred data target.",
        ))
    elif preferred == "warehouse":
        signals.append(StrategySignal(
            FabricTarget.WAREHOUSE,
            3,
            "Warehouse is the stated preferred data target.",
        ))

    if inventory.metadata.get("team_skill") == "spark":
        signals.append(StrategySignal(FabricTarget.LAKEHOUSE, 4, "The delivery team primarily uses Spark."))
    if inventory.metadata.get("team_skill") == "sql":
        signals.append(StrategySignal(FabricTarget.WAREHOUSE, 4, "The delivery team primarily uses SQL."))

    scores = {target: 0 for target in _CANDIDATE_TARGETS}
    for signal in signals:
        if signal.target in scores:
            scores[signal.target] += signal.weight

    requires_transactions = any(
        item.properties.get("requires_multi_table_transactions") for item in inventory.objects()
    )
    best = max(scores.values())
    tied = [target for target in _CANDIDATE_TARGETS if scores[target] == best]

    if requires_transactions:
        # A stated multi-table transaction requirement is a constraint, not a vote.
        primary = FabricTarget.WAREHOUSE
        signals.append(StrategySignal(
            FabricTarget.WAREHOUSE,
            0,
            "Multi-table transactions require Warehouse; this constraint pins the primary "
            f"target regardless of the workload scores {dict(sorted(scores.items()))}.",
        ))
    else:
        primary = tied[0]
        if len(tied) > 1:
            signals.append(StrategySignal(
                primary,
                0,
                "Tie broken toward "
                f"{primary.value} among {[target.value for target in tied]} by declaration "
                "order; no workload evidence separates them.",
            ))

    active = {decision.target for decision in decisions if decision.target not in {FabricTarget.MANUAL}}
    architecture = "hybrid" if len(active & set(_CANDIDATE_TARGETS)) > 1 else primary.value
    return StrategyRecommendation(primary, architecture, scores, tuple(signals))
