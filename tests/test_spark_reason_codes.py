import json
from pathlib import Path

from bqtofabric.cli import main
from bqtofabric.models import BigQueryObject, ObjectKind
from bqtofabric.spark_conversion import SPARK_REASON_CODES, convert_spark_job

FIXTURE = Path(__file__).parent / "fixtures" / "gcp_ecosystem_project.json"

PYSPARK_JOB = """
from pyspark.sql import SparkSession
spark = SparkSession.builder.appName("etl").getOrCreate()
df = spark.read.parquet("gs://raw-bucket/events/")
query = "SELECT * FROM " + table_name
spark.sql(query).write.mode("overwrite").saveAsTable("events")
"""


def _job(**properties: object) -> BigQueryObject:
    return BigQueryObject("p.dataproc.etl", "etl", ObjectKind.DATAPROC_JOB, properties=dict(properties))


def test_missing_code_and_runtime_have_stable_reason_codes() -> None:
    record = convert_spark_job(_job())

    assert record["reasonCodes"] == ["runtime_version_missing", "source_code_missing"]
    assert "conversion" not in record


def test_supplied_code_reports_converter_verdict_and_reasons() -> None:
    record = convert_spark_job(_job(code=PYSPARK_JOB, language="python", runtime_version="2.2"))

    assert record["conversion"]["rewrites"] >= 1
    assert record["conversion"]["compatibility"] in {"transform", "redesign", "unsupported"}
    assert "dynamic_sql" in record["reasonCodes"]
    assert "source_code_missing" not in record["reasonCodes"]
    assert set(record["reasonCodes"]) <= SPARK_REASON_CODES


def test_reference_conversions_use_only_documented_codes_and_notebooks_validate(tmp_path: Path) -> None:
    assert main(["generate", str(FIXTURE), "--output", str(tmp_path)]) == 0
    fabric = tmp_path / "fabric"

    conversions = json.loads((fabric / "spark-conversions.json").read_text(encoding="utf-8"))
    validation = json.loads((fabric / "artifact-validation.json").read_text(encoding="utf-8"))
    notebooks = [item for item in validation["artifacts"] if item["path"].endswith(".ipynb")]

    assert conversions["conversions"]
    for record in conversions["conversions"]:
        assert record["reasonCodes"], record["sourceId"]
        assert set(record["reasonCodes"]) <= SPARK_REASON_CODES
    assert notebooks
    assert all(item["status"] == "passed" for item in notebooks)
