"""Explainable selection of the primary Microsoft Fabric target."""

from __future__ import annotations

from dataclasses import dataclass

from .mapping import FabricTarget, MappingDecision
from .models import BigQueryInventory


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


def recommend_strategy(
    inventory: BigQueryInventory, decisions: tuple[MappingDecision, ...]
) -> StrategyRecommendation:
    signals: list[StrategySignal] = []
    for decision in decisions:
        weight = 3 if decision.target in {FabricTarget.EVENTHOUSE, FabricTarget.LAKEHOUSE} else 2
        signals.append(StrategySignal(decision.target, weight, decision.rationale))

    preferences = inventory.metadata.get("preferences", {})
    if isinstance(preferences, dict) and preferences.get("data_target") == "lakehouse":
        signals.append(StrategySignal(
            FabricTarget.LAKEHOUSE,
            3,
            "Lakehouse is the preferred data target when stronger workload constraints do not override it.",
        ))

    if any(item.properties.get("requires_multi_table_transactions") for item in inventory.objects()):
        signals.append(StrategySignal(FabricTarget.WAREHOUSE, 20, "Multi-table transactions require Warehouse."))
    if inventory.metadata.get("team_skill") == "spark":
        signals.append(StrategySignal(FabricTarget.LAKEHOUSE, 4, "The delivery team primarily uses Spark."))
    if inventory.metadata.get("team_skill") == "sql":
        signals.append(StrategySignal(FabricTarget.WAREHOUSE, 4, "The delivery team primarily uses SQL."))

    scores = {target: 0 for target in FabricTarget}
    for signal in signals:
        scores[signal.target] += signal.weight
    primary = max(
        (FabricTarget.WAREHOUSE, FabricTarget.LAKEHOUSE, FabricTarget.EVENTHOUSE),
        key=lambda target: (scores[target], -list(FabricTarget).index(target)),
    )
    active = {decision.target for decision in decisions if decision.target not in {FabricTarget.MANUAL}}
    architecture = "hybrid" if len(active & {
        FabricTarget.WAREHOUSE, FabricTarget.LAKEHOUSE, FabricTarget.EVENTHOUSE
    }) > 1 else primary.value
    return StrategyRecommendation(primary, architecture, scores, tuple(signals))
