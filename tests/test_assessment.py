from pathlib import Path

from bqtofabric.assessment import run_assessment
from bqtofabric.inventory import JsonInventoryProvider
from bqtofabric.mapping import FabricTarget
from bqtofabric.planner import build_plan

FIXTURE = Path(__file__).parent / "fixtures" / "mixed_project.json"


def test_assessment_routes_mixed_workloads_and_explains_strategy() -> None:
    inventory = JsonInventoryProvider(FIXTURE).load()
    report = run_assessment(inventory)
    targets = {decision.source_id: decision.target for decision in report.decisions}

    assert targets["retail-analytics.sales.customers"] is FabricTarget.WAREHOUSE
    assert targets["retail-analytics.sales.orders"] is FabricTarget.LAKEHOUSE
    assert targets["retail-analytics.sales.clickstream"] is FabricTarget.EVENTHOUSE
    assert report.strategy.architecture == "hybrid"
    assert report.strategy.primary_target is FabricTarget.WAREHOUSE
    assert any(finding.source_id == "STRUCT" for finding in report.findings)


def test_plan_orders_view_after_its_table_dependency() -> None:
    inventory = JsonInventoryProvider(FIXTURE).load()
    report = run_assessment(inventory)
    plan = build_plan(inventory, report)
    waves = {item.source_id: item.wave for item in plan.items}

    assert waves["retail-analytics.sales.orders"] < waves["retail-analytics.sales.daily_sales"]
    assert plan.unresolved_dependencies == ()