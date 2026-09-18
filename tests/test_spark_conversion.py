from bqtofabric.models import BigQueryObject, ObjectKind
from bqtofabric.spark_conversion import convert_spark_job


def test_spark_conversion_emits_one_lake_substitutions() -> None:
    item = BigQueryObject(
        source_id="demo.spark.enrichment",
        name="enrichment",
        kind=ObjectKind.SPARK_JOB,
        properties={
            "language": "python",
            "runtime_version": "3.5",
            "uses_gcs": True,
            "uses_bigquery_connector": True,
            "streaming": True,
        },
    )

    conversion = convert_spark_job(item)

    assert conversion["target"] == "fabric_notebook"
    assert conversion["runtime"] == "3.5"
    assert len(conversion["substitutions"]) == 2
    assert conversion["status"] == "review_required"