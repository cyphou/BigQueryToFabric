from pathlib import Path

from bqtofabric.assessment import run_assessment
from bqtofabric.inventory import JsonInventoryProvider
from bqtofabric.mapping import FabricTarget
from bqtofabric.models import BigQueryInventory
from bqtofabric.planner import build_plan

FIXTURE = Path(__file__).parent / "fixtures" / "gcp_ecosystem_project.json"


def test_inventory_parses_all_gcp_ecosystem_components() -> None:
    inventory = JsonInventoryProvider(FIXTURE).load()

    assert inventory.schema_version == "1.1"
    assert len(inventory.components) == 18
    assert len(inventory.objects()) == 19


def test_lakehouse_notebook_preference_and_airflow_are_preserved() -> None:
    report = run_assessment(JsonInventoryProvider(FIXTURE).load())
    decisions = {decision.source_id: decision for decision in report.decisions}

    spark = decisions["gcp-data-platform.spark.enrichment"]
    sql = decisions["gcp-data-platform.sql.daily_metrics"]
    airflow = decisions["gcp-data-platform.composer.platform_dag"]

    assert spark.target is FabricTarget.LAKEHOUSE
    assert FabricTarget.NOTEBOOK in spark.supporting_targets
    assert sql.target is FabricTarget.LAKEHOUSE
    assert FabricTarget.NOTEBOOK in sql.supporting_targets
    assert airflow.target is FabricTarget.AIRFLOW_JOB
    assert FabricTarget.LAKEHOUSE in airflow.supporting_targets
    assert report.strategy.primary_target is FabricTarget.LAKEHOUSE
    assert report.component_summary["composer_dag"] == 1
    assert report.target_summary["lakehouse"] >= 3
    assert report.compatibility_summary["unsupported"] == 1
    assert 50 <= report.score <= 90


def test_streaming_bi_ml_and_security_receive_specific_targets() -> None:
    report = run_assessment(JsonInventoryProvider(FIXTURE).load())
    decisions = {decision.source_id: decision for decision in report.decisions}

    assert decisions["gcp-data-platform.pubsub.events"].target is FabricTarget.EVENTHOUSE
    assert FabricTarget.EVENTSTREAM in decisions["gcp-data-platform.pubsub.events"].supporting_targets
    assert decisions["gcp-data-platform.looker.commerce"].target is FabricTarget.SEMANTIC_MODEL
    assert decisions["gcp-data-platform.bqml.churn"].target is FabricTarget.DATA_SCIENCE
    assert FabricTarget.LAKEHOUSE in decisions["gcp-data-platform.bqml.churn"].supporting_targets
    assert decisions["gcp-data-platform.vertex.churn_pipeline"].target is FabricTarget.DATA_SCIENCE
    assert decisions["gcp-data-platform.dataplex.catalog"].target is FabricTarget.PURVIEW
    assert decisions["gcp-data-platform.cloudsql.orders"].target is FabricTarget.SQL_DATABASE
    assert decisions["gcp-data-platform.spanner.global_inventory"].target is FabricTarget.SQL_DATABASE
    assert decisions["gcp-data-platform.security.customer_policy"].target is FabricTarget.MANUAL
    assert any(
        finding.severity == "FAIL" and finding.source_id.endswith("customer_policy")
        for finding in report.findings
    )


def test_nested_types_physical_design_and_security_require_review() -> None:
    inventory = JsonInventoryProvider(FIXTURE).load()
    report = run_assessment(inventory)
    plan = build_plan(inventory, report)
    decisions = {decision.source_id: decision for decision in report.decisions}
    plan_items = {item.source_id: item for item in plan.items}

    table = decisions["gcp-data-platform.analytics.events"]
    assert any("not equivalent" in action for action in table.actions)
    assert any(mapping.source_type == "GEOGRAPHY" for mapping in report.type_mappings)
    assert plan_items["gcp-data-platform.security.customer_policy"].manual_review is True
    assert plan_items["gcp-data-platform.composer.platform_dag"].wave > plan_items[
        "gcp-data-platform.dataform.gold_models"
    ].wave


def test_google_sql_is_parsed_and_assessed_for_spark_translation() -> None:
    report = run_assessment(JsonInventoryProvider(FIXTURE).load())
    sql_result = next(
        item for item in report.sql_assessments
        if item.source_id == "gcp-data-platform.sql.daily_metrics"
    )

    assert sql_result.parsed is True
    assert sql_result.target_language == "spark"
    assert "unnest" in sql_result.features
    assert sql_result.compatibility.value == "transform"


def test_transactions_override_lakehouse_preference() -> None:
    inventory = BigQueryInventory.from_dict({
        "project_id": "transactional",
        "metadata": {"preferences": {"data_target": "lakehouse"}},
        "components": [{
            "source_id": "transactional.sql.atomic_load",
            "name": "atomic_load",
            "kind": "sql_script",
            "properties": {"requires_multi_table_transactions": True},
        }],
    })

    assert run_assessment(inventory).strategy.primary_target is FabricTarget.WAREHOUSE


def test_engineering_mappings_use_component_evidence() -> None:
    inventory = BigQueryInventory.from_dict({
        "project_id": "evidence",
        "metadata": {"preferences": {"preserve_airflow": True}},
        "components": [
            {
                "source_id": "evidence.beam.batch",
                "name": "batch",
                "kind": "dataflow_job",
                "properties": {"portable": True, "connector_compatible": True},
            },
            {
                "source_id": "evidence.composer.custom",
                "name": "custom",
                "kind": "composer_dag",
                "properties": {"custom_plugins": True, "unsupported_operators": ["KubernetesPodOperator"]},
            },
            {
                "source_id": "evidence.dataform.incremental",
                "name": "incremental",
                "kind": "dataform_workflow",
                "properties": {"assertions": True, "incremental": True},
            },
        ],
    })

    decisions = {item.source_id: item for item in run_assessment(inventory).decisions}

    assert decisions["evidence.beam.batch"].target is FabricTarget.DATAFLOW_GEN2
    assert decisions["evidence.composer.custom"].target is FabricTarget.DATA_PIPELINE
    assert decisions["evidence.composer.custom"].compatibility.value == "redesign"
    assert len(decisions["evidence.dataform.incremental"].actions) == 3


def test_spark_mapping_preserves_runtime_and_storage_migration_evidence() -> None:
    inventory = BigQueryInventory.from_dict({
        "project_id": "spark-evidence",
        "components": [{
            "source_id": "spark-evidence.jobs.streaming",
            "name": "streaming",
            "kind": "spark_job",
            "properties": {
                "language": "scala",
                "runtime_version": "3.5",
                "uses_gcs": True,
                "uses_bigquery_connector": True,
                "streaming": True,
            },
        }],
    })

    decision = run_assessment(inventory).decisions[0]

    assert decision.target is FabricTarget.LAKEHOUSE
    assert FabricTarget.NOTEBOOK in decision.supporting_targets
    assert len(decision.actions) == 6
    assert any("OneLake" in action for action in decision.actions)
