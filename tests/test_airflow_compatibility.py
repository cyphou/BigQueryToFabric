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