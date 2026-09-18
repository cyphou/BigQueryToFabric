import json
from pathlib import Path

from bqtofabric.assessment import run_assessment
from bqtofabric.inventory import JsonInventoryProvider
from bqtofabric.mapping import FabricTarget
from bqtofabric.models import BigQueryInventory
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


def test_assessment_reports_origin_and_deterministic_discovery_coverage() -> None:
    source = json.loads(FIXTURE.read_text(encoding="utf-8"))
    objects = source["datasets"][0]["objects"]
    objects[1]["discovered_from"] = "bigquery_api"
    objects[2]["discovered_from"] = "external_payload"

    report = run_assessment(BigQueryInventory.from_dict(source))

    assert report.evidence_summary["retail-analytics.sales.customers"]["discovered_from"] == "inventory"
    assert report.evidence_summary["retail-analytics.sales.orders"]["discovered_from"] == "bigquery_api"
    assert report.evidence_summary["retail-analytics.sales.daily_sales"]["discovered_from"] == "external_payload"
    assert report.evidence_summary["retail-analytics.sales.clickstream"]["discovered_from"] == "inventory"
    assert report.discovery_coverage == {
        "bigquery_api": 1,
        "external_payload": 1,
        "inventory": 2,
    }


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


def test_sql_redesign_requires_manual_plan_review() -> None:
    inventory = type(JsonInventoryProvider(FIXTURE).load()).from_dict({
        "project_id": "sql-review",
        "components": [{
            "source_id": "sql-review.script",
            "name": "script",
            "kind": "sql_script",
            "sql": "BEGIN TRANSACTION; UPDATE sales.orders SET total = total + 1; COMMIT TRANSACTION;",
        }],
    })
    report = run_assessment(inventory)
    plan = build_plan(inventory, report)

    assert plan.items[0].manual_review is True


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


def test_parity_evidence_is_assessed_without_cloud_execution() -> None:
    inventory = type(JsonInventoryProvider(FIXTURE).load()).from_dict({
        "project_id": "parity",
        "datasets": [{
            "source_id": "parity.data",
            "name": "data",
            "location": "EU",
            "objects": [{
                "source_id": "parity.data.orders",
                "name": "orders",
                "kind": "table",
                "dataset": "data",
                "columns": [{"name": "id", "data_type": "INT64"}],
                "properties": {
                    "parity": {
                        "schema": {"status": "passed"},
                        "type": {"status": "passed"},
                        "row_count": {"status": "failed", "source": 10, "target": 9},
                        "checksum": {"status": "not_run", "algorithm": "sha256"},
                    }
                },
            }],
        }],
    })

    report = run_assessment(inventory)

    assert report.parity_summary["parity.data.orders"]["status"] == "failed"
    assert any(finding.code == "PARITY_FAILED" for finding in report.findings)


def test_dataset_access_entry_requires_effective_access_review() -> None:
    inventory = type(JsonInventoryProvider(FIXTURE).load()).from_dict({
        "project_id": "security-review",
        "datasets": [{
            "source_id": "security-review.analytics",
            "name": "analytics",
            "location": "EU",
            "objects": [{
                "source_id": "security-review.analytics.access.0000",
                "name": "analytics-access-0000",
                "kind": "security_policy",
                "dataset": "analytics",
                "properties": {
                    "evidence_scope": "dataset_access_entry",
                    "policy_type": "role",
                    "role": "READER",
                },
            }],
        }],
    })

    report = run_assessment(inventory)
    findings = [
        finding for finding in report.findings
        if finding.code == "SECURITY_EFFECTIVE_ACCESS_REVIEW"
    ]

    assert len(findings) == 1
    assert findings[0].severity == "FAIL"


def test_streaming_dataflow_requires_transitive_downstream_review() -> None:
    inventory = type(JsonInventoryProvider(FIXTURE).load()).from_dict({
        "project_id": "streaming-chain",
        "components": [
            {
                "source_id": "streaming-chain.ingest",
                "name": "ingest",
                "kind": "dataflow_job",
                "properties": {"streaming": True},
            },
            {
                "source_id": "streaming-chain.curated",
                "name": "curated",
                "kind": "spark_job",
                "dependencies": ["streaming-chain.ingest"],
            },
            {
                "source_id": "streaming-chain.gold",
                "name": "gold",
                "kind": "dataform_workflow",
                "dependencies": ["streaming-chain.curated"],
            },
        ],
    })

    report = run_assessment(inventory)
    plan = build_plan(inventory, report)
    plan_items = {item.source_id: item for item in plan.items}

    assert [
        finding.source_id
        for finding in report.findings
        if finding.code == "STREAMING_DOWNSTREAM_REVIEW"
    ] == ["streaming-chain.curated", "streaming-chain.gold"]
    assert plan_items["streaming-chain.ingest"].manual_review is True
    assert plan_items["streaming-chain.curated"].manual_review is True
    assert plan_items["streaming-chain.gold"].manual_review is True