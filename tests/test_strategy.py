"""Strategy selection must follow feasibility evidence, not target identity."""

from bqtofabric.mapping import Compatibility, FabricTarget, MappingDecision
from bqtofabric.models import BigQueryInventory, ObjectKind
from bqtofabric.strategy import recommend_strategy


def _decision(
    source_id: str,
    target: FabricTarget,
    compatibility: Compatibility = Compatibility.DIRECT,
) -> MappingDecision:
    return MappingDecision(
        source_id=source_id,
        source_kind=ObjectKind.TABLE,
        target=target,
        compatibility=compatibility,
        rationale="test",
    )


def _inventory(**metadata: object) -> BigQueryInventory:
    return BigQueryInventory(
        project_id="strategy", datasets=(), components=(), metadata=dict(metadata)
    )


def test_equal_component_counts_do_not_default_to_lakehouse() -> None:
    """Identical evidence on both sides must not be broken by target identity."""
    decisions = (
        _decision("a", FabricTarget.WAREHOUSE),
        _decision("b", FabricTarget.LAKEHOUSE),
    )

    result = recommend_strategy(_inventory(), decisions)

    assert result.scores[FabricTarget.WAREHOUSE] == result.scores[FabricTarget.LAKEHOUSE]


def test_redesign_targets_carry_less_weight_than_direct_ones() -> None:
    """Aspirational targets must not outvote demonstrably feasible ones."""
    decisions = (
        _decision("a", FabricTarget.WAREHOUSE, Compatibility.DIRECT),
        _decision("b", FabricTarget.LAKEHOUSE, Compatibility.REDESIGN),
    )

    result = recommend_strategy(_inventory(), decisions)

    assert result.scores[FabricTarget.WAREHOUSE] > result.scores[FabricTarget.LAKEHOUSE]
    assert result.primary_target is FabricTarget.WAREHOUSE


def test_unsupported_decisions_contribute_no_weight() -> None:
    """A target that cannot run the workload is not evidence for that target."""
    decisions = (_decision("a", FabricTarget.LAKEHOUSE, Compatibility.UNSUPPORTED),)

    result = recommend_strategy(_inventory(), decisions)

    assert result.scores[FabricTarget.LAKEHOUSE] == 0


def test_multi_table_transactions_pin_warehouse_over_any_score() -> None:
    """A declared hard constraint must not be outvoted by accumulated weights."""
    inventory = BigQueryInventory.from_dict({
        "project_id": "strategy",
        "components": [{
            "source_id": "strategy.ledger",
            "name": "ledger",
            "kind": "table",
            "properties": {"requires_multi_table_transactions": True},
        }],
        "metadata": {"team_skill": "spark"},
    })
    decisions = tuple(
        _decision(f"lake-{index}", FabricTarget.LAKEHOUSE) for index in range(20)
    )

    result = recommend_strategy(inventory, decisions)

    assert result.primary_target is FabricTarget.WAREHOUSE
    assert any("constraint pins" in signal.reason for signal in result.signals)


def test_preference_signal_is_symmetric_across_data_targets() -> None:
    """Warehouse and Lakehouse preferences must carry the same weight."""
    lakehouse = recommend_strategy(
        _inventory(preferences={"data_target": "lakehouse"}), ()
    )
    warehouse = recommend_strategy(
        _inventory(preferences={"data_target": "warehouse"}), ()
    )

    assert lakehouse.scores[FabricTarget.LAKEHOUSE] == warehouse.scores[FabricTarget.WAREHOUSE]
    assert lakehouse.primary_target is FabricTarget.LAKEHOUSE
    assert warehouse.primary_target is FabricTarget.WAREHOUSE


def test_tie_break_is_recorded_as_an_explicit_signal() -> None:
    """An unexplained bias is not an explanation; ties must be stated."""
    decisions = (
        _decision("a", FabricTarget.WAREHOUSE),
        _decision("b", FabricTarget.LAKEHOUSE),
    )

    result = recommend_strategy(_inventory(), decisions)

    assert any("Tie broken toward" in signal.reason for signal in result.signals)


def test_scores_only_report_candidate_primary_targets() -> None:
    """Reporting scores for targets that were never candidates misleads readers."""
    result = recommend_strategy(_inventory(), (_decision("a", FabricTarget.PURVIEW),))

    assert set(result.scores) == {
        FabricTarget.WAREHOUSE,
        FabricTarget.LAKEHOUSE,
        FabricTarget.EVENTHOUSE,
    }


def test_architecture_is_hybrid_only_when_multiple_data_targets_are_used() -> None:
    single = recommend_strategy(_inventory(), (_decision("a", FabricTarget.WAREHOUSE),))
    mixed = recommend_strategy(
        _inventory(),
        (_decision("a", FabricTarget.WAREHOUSE), _decision("b", FabricTarget.EVENTHOUSE)),
    )

    assert single.architecture == "warehouse"
    assert mixed.architecture == "hybrid"
