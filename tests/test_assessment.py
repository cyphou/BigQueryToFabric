import json
from pathlib import Path

import pytest

from bqtofabric.assessment import run_assessment
from bqtofabric.inventory import JsonInventoryProvider
from bqtofabric.mapping import FabricTarget
from bqtofabric.models import BigQueryInventory
from bqtofabric.planner import build_plan
from bqtofabric.type_mapping import Compatibility

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
    type_findings = [finding for finding in report.findings if finding.code == "TYPE_REDESIGN"]
    assert type_findings
    assert all(finding.category == "schema" for finding in type_findings)
    # The finding must identify the owning object and column, not the bare type name.
    struct_finding = next(finding for finding in type_findings if "STRUCT" in finding.message)
    assert struct_finding.source_id in targets
    assert struct_finding.source_id != "STRUCT"


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


def test_large_unpartitioned_table_gets_layout_review_findings() -> None:
    inventory = BigQueryInventory.from_dict({
        "project_id": "performance-review",
        "components": [{
            "source_id": "performance-review.large_events",
            "name": "large_events",
            "kind": "table",
            "size_bytes": 10 * 1024**3,
            "columns": [{"name": "event_id", "data_type": "STRING"}],
        }],
    })

    findings = run_assessment(inventory).findings
    codes = {finding.code for finding in findings}

    assert "PERFORMANCE_PARTITION_REVIEW" in codes
    assert "PERFORMANCE_CLUSTERING_REVIEW" in codes
    assert all(finding.category == "performance" for finding in findings if finding.code.startswith("PERFORMANCE_"))


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


def test_javascript_routine_is_never_reported_as_translatable_sql() -> None:
    """A JavaScript UDF has no SQL translation path and must not be marked direct."""
    inventory = type(JsonInventoryProvider(FIXTURE).load()).from_dict({
        "project_id": "sql-lang",
        "components": [{
            "source_id": "sql-lang.hash_id",
            "name": "hash_id",
            "kind": "routine",
            "sql": "CREATE FUNCTION hash_id(value STRING) RETURNS STRING LANGUAGE js AS 'return value;'",
            "properties": {"language": "JAVASCRIPT"},
        }],
    })

    result = run_assessment(inventory).sql_assessments[0]

    assert result.compatibility is Compatibility.REDESIGN
    assert result.converted_sql is None
    assert any("JAVASCRIPT" in note for note in result.notes)


def test_sql_compatibility_never_defaults_to_direct() -> None:
    """Unrecognised-but-parseable GoogleSQL must not be blessed as directly compatible."""
    inventory = type(JsonInventoryProvider(FIXTURE).load()).from_dict({
        "project_id": "sql-default",
        "components": [{
            "source_id": "sql-default.wildcard",
            "name": "wildcard",
            "kind": "view",
            "sql": "SELECT * FROM `project.dataset.events_*` WHERE _TABLE_SUFFIX = '20240101'",
        }],
    })

    result = run_assessment(inventory).sql_assessments[0]

    assert result.compatibility is not Compatibility.DIRECT
    assert any("_TABLE_SUFFIX" in note for note in result.notes)


def test_sql_compatibility_is_never_better_than_the_mapping_decision() -> None:
    """SQL and mapping are two axes of the same component; report the worse one."""
    inventory = JsonInventoryProvider(GCP_FIXTURE).load()
    report = run_assessment(inventory)
    decisions = {decision.source_id: decision for decision in report.decisions}
    order = [
        Compatibility.DIRECT,
        Compatibility.TRANSFORM,
        Compatibility.REDESIGN,
        Compatibility.UNSUPPORTED,
    ]

    for result in report.sql_assessments:
        decision = decisions[result.source_id]
        assert order.index(result.compatibility) >= order.index(decision.compatibility)


def test_score_is_not_diluted_by_schema_width() -> None:
    """A wide table of trivial columns must not raise the portfolio readiness score."""
    base = {
        "project_id": "score-width",
        "components": [
            {
                "source_id": "score-width.wide",
                "name": "wide",
                "kind": "table",
                "columns": [{"name": "id", "data_type": "INT64"}],
            },
            {
                "source_id": "score-width.risky",
                "name": "risky",
                "kind": "composer_dag",
                "properties": {"unsupported_operators": ["KubernetesPodOperator"]},
            },
        ],
    }
    narrow = run_assessment(BigQueryInventory.from_dict(base)).score

    widened = json.loads(json.dumps(base))
    widened["components"][0]["columns"] = [
        {"name": f"c{index}", "data_type": "INT64"} for index in range(100)
    ]
    wide = run_assessment(BigQueryInventory.from_dict(widened)).score

    assert wide == narrow


def test_component_with_fail_blocker_scores_zero() -> None:
    """A blocking finding must not leave the component contributing readiness points."""
    inventory = BigQueryInventory.from_dict({
        "project_id": "score-block",
        "components": [{
            "source_id": "score-block.policy",
            "name": "policy",
            "kind": "security_policy",
            "discovered_from": "bigquery_api",
            "properties": {"evidence_scope": "dataset_access_entry"},
        }],
    })

    report = run_assessment(inventory)

    assert any(finding.severity == "FAIL" for finding in report.findings)
    assert report.score == 0


def test_missing_parity_evidence_is_reported_as_a_finding() -> None:
    """Silence about parity is an evidence gap, not an implicit pass."""
    inventory = BigQueryInventory.from_dict({
        "project_id": "parity-gap",
        "components": [{
            "source_id": "parity-gap.orders",
            "name": "orders",
            "kind": "table",
            "columns": [{"name": "id", "data_type": "INT64"}],
        }],
    })

    report = run_assessment(inventory)

    assert report.parity_summary["parity-gap.orders"]["status"] == "not_run"
    assert any(finding.code == "PARITY_NOT_RUN" for finding in report.findings)


def test_recorded_false_is_evidence_not_absence() -> None:
    """A batch Dataflow job records streaming=false; mapping trusts it, so must evidence."""
    inventory = BigQueryInventory.from_dict({
        "project_id": "bool-evidence",
        "components": [{
            "source_id": "bool-evidence.batch",
            "name": "batch",
            "kind": "dataflow_job",
            "properties": {
                "streaming": False,
                "portable": True,
                "connector_compatible": True,
            },
        }],
    })

    report = run_assessment(inventory)

    assert report.evidence_summary["bool-evidence.batch"]["missing"] == []
    assert report.evidence_summary["bool-evidence.batch"]["coverage"] == 100


def test_core_bigquery_objects_require_evidence() -> None:
    """A listed-but-unexamined table must not report full evidence coverage."""
    inventory = BigQueryInventory.from_dict({
        "project_id": "core-evidence",
        "components": [
            {"source_id": "core-evidence.bare", "name": "bare", "kind": "table"},
            {"source_id": "core-evidence.view", "name": "view", "kind": "view"},
        ],
    })

    report = run_assessment(inventory)

    def missing(source_id: str) -> list[object]:
        value = report.evidence_summary[source_id]["missing"]
        assert isinstance(value, list)
        return value

    assert report.evidence_coverage < 100
    assert "columns" in missing("core-evidence.bare")
    assert "size_bytes" in missing("core-evidence.bare")
    assert "sql" in missing("core-evidence.view")


def test_assisted_evidence_is_never_silently_trusted() -> None:
    """Inferred evidence is usable input, never a cleared gate."""
    inventory = BigQueryInventory.from_dict({
        "project_id": "assisted",
        "components": [{
            "source_id": "assisted.job",
            "name": "job",
            "kind": "dataproc_job",
            "discovered_from": "assisted",
            "properties": {
                "language": "python",
                "runtime_version": "2.1",
                "code": "df = spark.read.parquet('/Shortcuts/raw')\n",
            },
        }],
    })

    report = run_assessment(inventory)
    plan = build_plan(inventory, report)

    # Evidence is complete, so there is no FAIL, but it still cannot pass unreviewed.
    assert report.evidence_summary["assisted.job"]["missing"] == []
    assert any(finding.code == "ASSISTED_EVIDENCE_UNVERIFIED" for finding in report.findings)
    assert plan.items[0].manual_review is True
    assert "assisted_evidence" in plan.items[0].manual_review_reasons


def test_incomplete_assisted_evidence_blocks() -> None:
    """Inference that did not close the gap must fail, like an incomplete adapter."""
    inventory = BigQueryInventory.from_dict({
        "project_id": "assisted-gap",
        "components": [{
            "source_id": "assisted-gap.job",
            "name": "job",
            "kind": "dataproc_job",
            "discovered_from": "assisted",
            "properties": {"language": "python"},
        }],
    })

    report = run_assessment(inventory)

    blockers = [finding for finding in report.findings if finding.severity == "FAIL"]
    assert any(finding.code == "ASSISTED_EVIDENCE_INCOMPLETE" for finding in blockers)
    assert report.score == 0


def test_unknown_provenance_is_rejected() -> None:
    """Provenance is a closed set so an unrecognised source cannot slip through."""
    from bqtofabric.inventory import validate_inventory_document

    document = {
        "project_id": "bad-provenance",
        "components": [{
            "source_id": "bad-provenance.table",
            "name": "table",
            "kind": "table",
            "discovered_from": "vibes",
        }],
    }

    with pytest.raises(ValueError, match="Unknown inventory discovered_from"):
        validate_inventory_document(document)


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
                "code": "df = spark.read.parquet('/Shortcuts/raw')\n",
            },
        }],
    })

    report = run_assessment(complete)

    assert not any("evidence missing" in finding.message for finding in report.findings)
    assert report.evidence_coverage == 100


def test_assessment_does_not_treat_unknown_runtime_as_evidence() -> None:
    inventory = BigQueryInventory.from_dict({
        "project_id": "dataproc-unknown-runtime",
        "components": [{
            "source_id": "dataproc-unknown-runtime.job",
            "name": "job",
            "kind": "dataproc_job",
            "properties": {
                "language": "python",
                "runtime_version": "unknown",
                "code": "df = spark.read.parquet('/Shortcuts/raw')\n",
            },
        }],
    })

    report = run_assessment(inventory)
    evidence = report.evidence_summary["dataproc-unknown-runtime.job"]

    assert evidence["missing"] == ["runtime_version"]


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


def test_incomplete_external_spark_adapter_requires_transitive_review() -> None:
    inventory = BigQueryInventory.from_dict({
        "project_id": "external-adapter-chain",
        "components": [
            {
                "source_id": "external-adapter-chain.transform",
                "name": "transform",
                "kind": "spark_job",
                "discovered_from": "external_payload",
            },
            {
                "source_id": "external-adapter-chain.curated",
                "name": "curated",
                "kind": "table",
                "dependencies": ["external-adapter-chain.transform"],
            },
            {
                "source_id": "external-adapter-chain.reporting",
                "name": "reporting",
                "kind": "view",
                "dependencies": ["external-adapter-chain.curated"],
            },
        ],
    })

    report = run_assessment(inventory)
    plan = build_plan(inventory, report)
    adapter_findings = [
        finding
        for finding in report.findings
        if finding.code == "EXTERNAL_PAYLOAD_INCOMPLETE_ADAPTER"
    ]
    plan_items = {item.source_id: item for item in plan.items}

    assert len(adapter_findings) == 1
    assert adapter_findings[0].severity == "FAIL"
    assert adapter_findings[0].source_id == "external-adapter-chain.transform"
    assert "language" in adapter_findings[0].message
    assert "runtime_version" in adapter_findings[0].message
    assert plan_items["external-adapter-chain.transform"].manual_review is True
    assert plan_items["external-adapter-chain.curated"].manual_review is True
    assert plan_items["external-adapter-chain.reporting"].manual_review is True
    assert plan_items["external-adapter-chain.transform"].manual_review_reasons == (
        "incomplete_external_adapter",
        "missing_required_evidence",
    )
    assert plan_items["external-adapter-chain.curated"].manual_review_reasons == (
        "depends_on_incomplete_external_adapter",
        "missing_required_evidence",
    )
    assert plan_items["external-adapter-chain.reporting"].manual_review_reasons == (
        "depends_on_incomplete_external_adapter",
        "missing_required_evidence",
    )
    assert plan.unresolved_dependencies == ()


def test_incomplete_dataform_compilation_requires_transitive_review() -> None:
    inventory = BigQueryInventory.from_dict({
        "project_id": "dataform-compilation-chain",
        "components": [
            {
                "source_id": "dataform-compilation-chain.compilation.result-001",
                "name": "result-001",
                "kind": "dataform_workflow",
                "discovered_from": "dataform_api",
                "properties": {"discovery_incomplete": True, "lineage_status": "unavailable"},
            },
            {
                "source_id": "dataform-compilation-chain.reporting",
                "name": "reporting",
                "kind": "view",
                "dependencies": ["dataform-compilation-chain.compilation.result-001"],
            },
        ],
    })

    report = run_assessment(inventory)
    plan = build_plan(inventory, report)
    plan_items = {item.source_id: item for item in plan.items}

    assert any(
        finding.code == "DATAFORM_COMPILATION_DETAILS_UNAVAILABLE"
        and finding.source_id == "dataform-compilation-chain.compilation.result-001"
        for finding in report.findings
    )
    assert plan_items["dataform-compilation-chain.compilation.result-001"].manual_review_reasons == (
        "incomplete_dataform_compilation",
        "missing_required_evidence",
    )
    assert plan_items["dataform-compilation-chain.reporting"].manual_review_reasons == (
        "depends_on_incomplete_dataform_compilation",
        "missing_required_evidence",
    )


def test_composer_empty_connection_inventory_is_complete_evidence() -> None:
    inventory = BigQueryInventory.from_dict({
        "project_id": "composer-evidence",
        "components": [{
            "source_id": "composer-evidence.daily",
            "name": "daily",
            "kind": "composer_dag",
            "properties": {
                "operators": ["BigQueryOperator"],
                "runtime_version": "2.5.0",
                "connections": [],
            },
        }],
    })

    report = run_assessment(inventory)

    assert report.evidence_summary["composer-evidence.daily"]["missing"] == []


def test_dataform_false_capabilities_are_complete_evidence() -> None:
    inventory = BigQueryInventory.from_dict({
        "project_id": "dataform-evidence",
        "components": [{
            "source_id": "dataform-evidence.workflow",
            "name": "workflow",
            "kind": "dataform_workflow",
            "properties": {"models": [], "assertions": False, "incremental": False},
        }],
    })

    report = run_assessment(inventory)

    assert report.evidence_summary["dataform-evidence.workflow"]["missing"] == []