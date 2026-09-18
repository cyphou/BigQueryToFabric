from pathlib import Path

from bqtofabric.assessment import run_assessment
from bqtofabric.inventory import JsonInventoryProvider
from bqtofabric.mapping import FabricTarget
from bqtofabric.planner import build_plan

FIXTURE = Path(__file__).parent / "fixtures" / "mixed_project.json"
GCP_FIXTURE = Path(__file__).parent / "fixtures" / "gcp_ecosystem_project.json"


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
    assert any(finding.code == "TYPE_REDESIGN" and finding.category == "schema"
               for finding in report.findings)


def test_plan_orders_view_after_its_table_dependency() -> None:
    inventory = JsonInventoryProvider(FIXTURE).load()
    report = run_assessment(inventory)
    plan = build_plan(inventory, report)
    waves = {item.source_id: item.wave for item in plan.items}

    assert waves["retail-analytics.sales.orders"] < waves["retail-analytics.sales.daily_sales"]
    assert plan.unresolved_dependencies == ()


def test_sql_assessment_keeps_structured_target_conversion() -> None:
    inventory = JsonInventoryProvider(FIXTURE).load()
    report = run_assessment(inventory)
    sql_result = next(
        result for result in report.sql_assessments
        if result.source_id == "retail-analytics.sales.daily_sales"
    )

    assert sql_result.converted_sql is not None
    assert "SELECT" in sql_result.converted_sql.upper()
    assert "[sales]" in sql_result.converted_sql


def test_assessment_penalizes_missing_family_evidence() -> None:
    inventory = JsonInventoryProvider(GCP_FIXTURE).load()
    report = run_assessment(inventory)

    spark_findings = [
        finding for finding in report.findings
        if finding.source_id == "gcp-data-platform.spark.enrichment"
    ]

    assert report.score < 90
    evidence = report.evidence_summary["gcp-data-platform.spark.enrichment"]
    assert evidence["coverage"] == 0
    assert report.evidence_coverage < 100
    assert any("language" in finding.message for finding in spark_findings)
    assert any("runtime_version" in finding.message for finding in spark_findings)
    evidence_findings = [finding for finding in spark_findings if "evidence missing" in finding.message]
    assert evidence_findings
    assert all(finding.code == "EVIDENCE_MISSING" for finding in evidence_findings)


def test_assessment_accepts_complete_family_evidence() -> None:
    inventory = JsonInventoryProvider(GCP_FIXTURE).load()
    component = next(
        item for item in inventory.components if item.kind.value == "spark_job"
    )
    complete = type(inventory).from_dict({
        "project_id": inventory.project_id,
        "metadata": inventory.metadata,
        "components": [{
            "source_id": component.source_id,
            "name": component.name,
            "kind": component.kind.value,
            "properties": {
                "language": "python",
                "runtime_version": "3.5",
            },
        }],
    })

    report = run_assessment(complete)

    assert not any("evidence missing" in finding.message for finding in report.findings)
    assert report.evidence_coverage == 100