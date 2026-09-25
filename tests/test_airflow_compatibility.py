from bqtofabric.airflow_compatibility import assess_airflow_compatibility
from bqtofabric.models import BigQueryObject, ObjectKind


def test_airflow_compatibility_blocks_custom_plugins_and_unsupported_operators() -> None:
    item = BigQueryObject(
        source_id="demo.composer.pipeline",
        name="pipeline",
        kind=ObjectKind.COMPOSER_DAG,
        properties={
            "operators": ["BigQueryInsertJobOperator"],
            "unsupported_operators": ["KubernetesPodOperator"],
            "connections": ["bigquery_default"],
            "custom_plugins": True,
        },
    )

    report = assess_airflow_compatibility(item)

    assert report["target"] == "fabric_pipeline"
    assert report["status"] == "redesign_required"
    assert report["unsupportedOperators"] == ["KubernetesPodOperator"]


def test_airflow_compatibility_reports_operational_contract_signals() -> None:
    item = BigQueryObject(
        source_id="demo.composer.operational",
        name="operational",
        kind=ObjectKind.COMPOSER_DAG,
        properties={
            "operators": ["BigQueryOperator", "S3KeySensor"],
            "providers": ["apache-airflow-providers-google", "apache-airflow-providers-amazon"],
            "sensors": ["S3KeySensor"],
            "pools": ["warehouse_pool"],
            "connections": ["bigquery_default"],
            "sla": "4h",
            "retries": 3,
            "retry_delay": "00:05:00",
            "schedule_interval": "@daily",
        },
    )

    report = assess_airflow_compatibility(item)

    assert report["providers"] == [
        "apache-airflow-providers-amazon",
        "apache-airflow-providers-google",
    ]
    assert report["sensors"] == ["S3KeySensor"]
    assert report["pools"] == ["warehouse_pool"]
    assert report["sla"] == "4h"
    assert report["retries"] == 3
    assert report["retryDelay"] == "00:05:00"
    assert report["schedule"] == "@daily"