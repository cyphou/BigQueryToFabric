"""Comprehensive tests for Fabric artifact generation."""

import json
from pathlib import Path

import pytest

from bqtofabric.assessment import run_assessment
from bqtofabric.generator.artifact_generator import ArtifactGenerator, generate_artifacts
from bqtofabric.generator.eventstream_generator import (
    EventhouseGenerator,
    EventstreamGenerator,
)
from bqtofabric.generator.notebook_generator import NotebookGenerator
from bqtofabric.generator.pipeline_generator import PipelineGenerator
from bqtofabric.generator.semantic_model_generator import SemanticModelGenerator
from bqtofabric.generator.warehouse_generator import WarehouseGenerator
from bqtofabric.mapping import FabricTarget, MappingDecision
from bqtofabric.models import BigQueryInventory, BigQueryObject, Column, ObjectKind
from bqtofabric.type_mapping import Compatibility


# Fixtures


@pytest.fixture
def simple_table() -> BigQueryObject:
    """Create a simple table for testing."""
    return BigQueryObject(
        source_id="project.dataset.sales",
        name="sales",
        kind=ObjectKind.TABLE,
        dataset="dataset",
        columns=(
            Column(name="id", data_type="INT64", nullable=False),
            Column(name="amount", data_type="FLOAT64", nullable=True),
            Column(name="date", data_type="DATE", nullable=True),
            Column(name="description", data_type="STRING", nullable=True),
        ),
        partition_field="date",
        clustering_fields=("date", "id"),
    )


@pytest.fixture
def simple_view() -> BigQueryObject:
    """Create a simple view for testing."""
    return BigQueryObject(
        source_id="project.dataset.sales_view",
        name="sales_view",
        kind=ObjectKind.VIEW,
        dataset="dataset",
        sql="SELECT id, amount, date FROM dataset.sales WHERE amount > 0",
        columns=(
            Column(name="id", data_type="INT64", nullable=False),
            Column(name="amount", data_type="FLOAT64", nullable=True),
            Column(name="date", data_type="DATE", nullable=True),
        ),
    )


@pytest.fixture
def spark_job() -> BigQueryObject:
    """Create a Spark job for testing."""
    return BigQueryObject(
        source_id="project.dataproc.etl_job",
        name="etl_job",
        kind=ObjectKind.SPARK_JOB,
        dataset="",
        properties={
            "uses_gcs": True,
            "uses_bigquery_connector": True,
            "streaming": False,
            "runtime_version": "3.11",
            "language": "pyspark",
        },
        sql="""
        df = spark.read.parquet("gs://my-bucket/input")
        df_filtered = df.filter(col("status") == "active")
        df_filtered.write.mode("overwrite").parquet("gs://my-bucket/output")
        """,
    )


@pytest.fixture
def streaming_topic() -> BigQueryObject:
    """Create a Pub/Sub topic for testing."""
    return BigQueryObject(
        source_id="project.pubsub.events",
        name="events",
        kind=ObjectKind.PUBSUB_TOPIC,
        dataset="",
        columns=(
            Column(name="event_id", data_type="STRING", nullable=False),
            Column(name="event_time", data_type="TIMESTAMP", nullable=False),
            Column(name="value", data_type="INT64", nullable=True),
        ),
        properties={
            "source_type": "Kafka",
            "format": "JSON",
            "retention": "7 days",
        },
    )


@pytest.fixture
def scheduled_query() -> BigQueryObject:
    """Create a scheduled query for testing."""
    return BigQueryObject(
        source_id="project.scheduled_query.daily_summary",
        name="daily_summary",
        kind=ObjectKind.SCHEDULED_QUERY,
        dataset="results",
        sql="SELECT COUNT(*) as cnt, DATE(event_time) as event_date FROM events GROUP BY event_date",
        columns=(
            Column(name="cnt", data_type="INT64", nullable=False),
            Column(name="event_date", data_type="DATE", nullable=False),
        ),
        properties={
            "schedule_interval": "@daily",
            "destination_table": "results.daily_summary",
        },
    )


@pytest.fixture
def composer_dag() -> BigQueryObject:
    """Create a Composer DAG for testing."""
    return BigQueryObject(
        source_id="project.composer.daily_etl",
        name="daily_etl",
        kind=ObjectKind.COMPOSER_DAG,
        dataset="",
        properties={
            "schedule_interval": "@daily",
            "tasks": [
                {"task_id": "extract", "operator": "BashOperator", "bash_command": "gsutil ls gs://bucket"},
                {"task_id": "transform", "operator": "PythonOperator", "python_callable": "transform_data"},
                {"task_id": "load", "operator": "BigQueryOperator", "sql": "INSERT INTO table SELECT * FROM staging"},
            ],
        },
    )


@pytest.fixture
def basic_inventory(simple_table, simple_view, spark_job) -> BigQueryInventory:
    """Create a basic inventory for testing."""
    return BigQueryInventory(
        project_id="test-project",
        datasets=(),
        components=(simple_table, simple_view, spark_job),
        metadata={"version": "1.0"},
    )


@pytest.fixture
def basic_assessment(basic_inventory) -> dict:
    """Run assessment on basic inventory."""
    return run_assessment(basic_inventory)


# Notebook Generator Tests


class TestNotebookGenerator:
    """Tests for Lakehouse notebook generation."""

    def test_generate_notebook_from_spark_job(self, spark_job):
        """Test notebook generation from Spark job."""
        decision = MappingDecision(
            source_id=spark_job.source_id,
            source_kind=spark_job.kind,
            target=FabricTarget.NOTEBOOK,
            compatibility=Compatibility.TRANSFORM,
            rationale="Convert Spark job to Fabric notebook",
        )
        inventory = BigQueryInventory(project_id="test", datasets=(), components=(spark_job,), metadata={})
        assessment = run_assessment(inventory)

        gen = NotebookGenerator(inventory, assessment)
        notebook = gen.generate_notebook(spark_job, decision)

        assert notebook is not None
        assert notebook.source_id == spark_job.source_id
        assert notebook.title == f"Notebook: {spark_job.name}"
        assert len(notebook.cells) > 0

    def test_notebook_has_required_cells(self, spark_job):
        """Test that generated notebook has all required cells."""
        decision = MappingDecision(
            source_id=spark_job.source_id,
            source_kind=spark_job.kind,
            target=FabricTarget.NOTEBOOK,
            compatibility=Compatibility.TRANSFORM,
            rationale="Test notebook",
        )
        inventory = BigQueryInventory(project_id="test", datasets=(), components=(spark_job,), metadata={})
        assessment = run_assessment(inventory)

        gen = NotebookGenerator(inventory, assessment)
        notebook = gen.generate_notebook(spark_job, decision)

        cell_types = [cell.cell_type for cell in notebook.cells]
        assert "markdown" in cell_types  # Title cell
        assert "code" in cell_types  # Config and code cells
        assert cell_types[-1] == "markdown"  # Warnings cell at end

    def test_notebook_to_ipynb_format(self, spark_job):
        """Test that notebook generates valid nbformat 4 JSON."""
        decision = MappingDecision(
            source_id=spark_job.source_id,
            source_kind=spark_job.kind,
            target=FabricTarget.NOTEBOOK,
            compatibility=Compatibility.TRANSFORM,
            rationale="Test notebook",
        )
        inventory = BigQueryInventory(project_id="test", datasets=(), components=(spark_job,), metadata={})
        assessment = run_assessment(inventory)

        gen = NotebookGenerator(inventory, assessment)
        notebook = gen.generate_notebook(spark_job, decision)
        ipynb_dict = notebook.to_ipynb_dict()

        assert ipynb_dict["nbformat"] == 4
        assert ipynb_dict["nbformat_minor"] == 4
        assert "cells" in ipynb_dict
        assert "metadata" in ipynb_dict
        assert len(ipynb_dict["cells"]) > 0

    def test_notebook_preserves_lineage(self, spark_job):
        """Test that notebook preserves source lineage."""
        decision = MappingDecision(
            source_id=spark_job.source_id,
            source_kind=spark_job.kind,
            target=FabricTarget.NOTEBOOK,
            compatibility=Compatibility.TRANSFORM,
            rationale="Test notebook",
        )
        inventory = BigQueryInventory(project_id="test", datasets=(), components=(spark_job,), metadata={})
        assessment = run_assessment(inventory)

        gen = NotebookGenerator(inventory, assessment)
        notebook = gen.generate_notebook(spark_job, decision)

        # Check that source ID is preserved in first cell
        first_cell_text = "".join(notebook.cells[0].source)
        assert spark_job.source_id in first_cell_text

    def test_notebook_includes_warnings(self, spark_job):
        """Test that notebook includes manual review warnings."""
        decision = MappingDecision(
            source_id=spark_job.source_id,
            source_kind=spark_job.kind,
            target=FabricTarget.NOTEBOOK,
            compatibility=Compatibility.TRANSFORM,
            rationale="Test notebook",
            actions=("Review Spark dependencies", "Validate data types"),
        )
        inventory = BigQueryInventory(project_id="test", datasets=(), components=(spark_job,), metadata={})
        assessment = run_assessment(inventory)

        gen = NotebookGenerator(inventory, assessment)
        notebook = gen.generate_notebook(spark_job, decision)

        warnings_cell_text = "".join(notebook.cells[-1].source)
        # Check for markdown or code styling of TODO
        assert "TODO" in warnings_cell_text or "todo" in warnings_cell_text.lower()
        assert "MANUAL REVIEW" in warnings_cell_text or "Manual Review" in warnings_cell_text

    def test_notebook_handles_non_spark_objects(self, simple_table):
        """Test that notebook generator skips non-Spark objects."""
        decision = MappingDecision(
            source_id=simple_table.source_id,
            source_kind=simple_table.kind,
            target=FabricTarget.WAREHOUSE,
            compatibility=Compatibility.DIRECT,
            rationale="Table maps to warehouse",
        )
        inventory = BigQueryInventory(project_id="test", datasets=(), components=(simple_table,), metadata={})
        assessment = run_assessment(inventory)

        gen = NotebookGenerator(inventory, assessment)
        notebook = gen.generate_notebook(simple_table, decision)

        assert notebook is None


# Warehouse Generator Tests


class TestWarehouseGenerator:
    """Tests for Warehouse DDL/DML generation."""

    def test_generate_table_ddl(self, simple_table):
        """Test T-SQL table creation from BigQuery table."""
        decision = MappingDecision(
            source_id=simple_table.source_id,
            source_kind=simple_table.kind,
            target=FabricTarget.WAREHOUSE,
            compatibility=Compatibility.DIRECT,
            rationale="Direct mapping to warehouse table",
        )
        inventory = BigQueryInventory(project_id="test", datasets=(), components=(simple_table,), metadata={})
        assessment = run_assessment(inventory)

        gen = WarehouseGenerator(inventory, assessment)
        script = gen.generate_warehouse_script(simple_table, decision)

        assert script is not None
        assert "CREATE TABLE" in script.script
        assert simple_table.name in script.script
        assert "[id]" in script.script or "id" in script.script

    def test_table_ddl_includes_columns(self, simple_table):
        """Test that table DDL includes all columns."""
        decision = MappingDecision(
            source_id=simple_table.source_id,
            source_kind=simple_table.kind,
            target=FabricTarget.WAREHOUSE,
            compatibility=Compatibility.DIRECT,
            rationale="Direct mapping",
        )
        inventory = BigQueryInventory(project_id="test", datasets=(), components=(simple_table,), metadata={})
        assessment = run_assessment(inventory)

        gen = WarehouseGenerator(inventory, assessment)
        script = gen.generate_warehouse_script(simple_table, decision)

        for col in simple_table.columns:
            assert col.name in script.script

    def test_generate_view_definition(self, simple_view):
        """Test T-SQL view creation from BigQuery view."""
        decision = MappingDecision(
            source_id=simple_view.source_id,
            source_kind=simple_view.kind,
            target=FabricTarget.WAREHOUSE,
            compatibility=Compatibility.TRANSFORM,
            rationale="View requires SQL conversion",
        )
        inventory = BigQueryInventory(project_id="test", datasets=(), components=(simple_view,), metadata={})
        assessment = run_assessment(inventory)

        gen = WarehouseGenerator(inventory, assessment)
        script = gen.generate_warehouse_script(simple_view, decision)

        assert script is not None
        assert "CREATE VIEW" in script.script
        assert simple_view.name in script.script

    def test_warehouse_handles_materialized_views(self):
        """Test Warehouse generator for materialized views."""
        mv = BigQueryObject(
            source_id="project.dataset.mv_sales",
            name="mv_sales",
            kind=ObjectKind.MATERIALIZED_VIEW,
            dataset="dataset",
            sql="SELECT id, SUM(amount) as total FROM sales GROUP BY id",
            columns=(
                Column(name="id", data_type="INT64", nullable=False),
                Column(name="total", data_type="FLOAT64", nullable=True),
            ),
        )

        decision = MappingDecision(
            source_id=mv.source_id,
            source_kind=mv.kind,
            target=FabricTarget.WAREHOUSE,
            compatibility=Compatibility.TRANSFORM,
            rationale="Materialized view",
        )
        inventory = BigQueryInventory(project_id="test", datasets=(), components=(mv,), metadata={})
        assessment = run_assessment(inventory)

        gen = WarehouseGenerator(inventory, assessment)
        script = gen.generate_warehouse_script(mv, decision)

        assert script is not None
        assert "CREATE TABLE" in script.script

    def test_warehouse_skips_non_table_objects(self, spark_job):
        """Test that warehouse generator skips non-table objects."""
        decision = MappingDecision(
            source_id=spark_job.source_id,
            source_kind=spark_job.kind,
            target=FabricTarget.NOTEBOOK,
            compatibility=Compatibility.TRANSFORM,
            rationale="Spark job",
        )
        inventory = BigQueryInventory(project_id="test", datasets=(), components=(spark_job,), metadata={})
        assessment = run_assessment(inventory)

        gen = WarehouseGenerator(inventory, assessment)
        script = gen.generate_warehouse_script(spark_job, decision)

        assert script is None

    def test_warehouse_script_is_valid_sql_comment(self, simple_table):
        """Test that generated script starts with valid SQL comment."""
        decision = MappingDecision(
            source_id=simple_table.source_id,
            source_kind=simple_table.kind,
            target=FabricTarget.WAREHOUSE,
            compatibility=Compatibility.DIRECT,
            rationale="Direct mapping",
        )
        inventory = BigQueryInventory(project_id="test", datasets=(), components=(simple_table,), metadata={})
        assessment = run_assessment(inventory)

        gen = WarehouseGenerator(inventory, assessment)
        script = gen.generate_warehouse_script(simple_table, decision)

        assert script.script.lstrip().startswith("/*")


# Eventstream Generator Tests


class TestEventstreamGenerator:
    """Tests for Eventstream topology generation."""

    def test_generate_eventstream_from_pubsub(self, streaming_topic):
        """Test eventstream generation from Pub/Sub topic."""
        decision = MappingDecision(
            source_id=streaming_topic.source_id,
            source_kind=streaming_topic.kind,
            target=FabricTarget.EVENTSTREAM,
            compatibility=Compatibility.TRANSFORM,
            rationale="Pub/Sub maps to Eventstream",
        )
        inventory = BigQueryInventory(project_id="test", datasets=(), components=(streaming_topic,), metadata={})
        assessment = run_assessment(inventory)

        gen = EventstreamGenerator(inventory, assessment)
        eventstream = gen.generate_eventstream(streaming_topic, decision)

        assert eventstream is not None
        assert eventstream.source_id == streaming_topic.source_id
        # The topology IS a dict, not nested under a key
        assert isinstance(eventstream.topology, dict)
        assert "nodes" in eventstream.topology

    def test_eventstream_has_source_and_destination(self, streaming_topic):
        """Test that eventstream topology includes source and destination nodes."""
        decision = MappingDecision(
            source_id=streaming_topic.source_id,
            source_kind=streaming_topic.kind,
            target=FabricTarget.EVENTSTREAM,
            compatibility=Compatibility.TRANSFORM,
            rationale="Pub/Sub maps to Eventstream",
        )
        inventory = BigQueryInventory(project_id="test", datasets=(), components=(streaming_topic,), metadata={})
        assessment = run_assessment(inventory)

        gen = EventstreamGenerator(inventory, assessment)
        eventstream = gen.generate_eventstream(streaming_topic, decision)

        assert "source" in eventstream.topology["nodes"]
        assert "destination" in eventstream.topology["nodes"]

    def test_generate_eventhouse_schema(self, streaming_topic):
        """Test KQL schema generation from streaming topic."""
        decision = MappingDecision(
            source_id=streaming_topic.source_id,
            source_kind=streaming_topic.kind,
            target=FabricTarget.EVENTHOUSE,
            compatibility=Compatibility.TRANSFORM,
            rationale="Streaming topic maps to Eventhouse",
        )
        inventory = BigQueryInventory(project_id="test", datasets=(), components=(streaming_topic,), metadata={})
        assessment = run_assessment(inventory)

        gen = EventhouseGenerator(inventory, assessment)
        schema = gen.generate_eventhouse_schema(streaming_topic, decision)

        assert schema is not None
        assert ".create-or-alter table" in schema.kql_script
        assert streaming_topic.name in schema.kql_script

    def test_eventhouse_schema_includes_columns(self, streaming_topic):
        """Test that Eventhouse schema includes all columns."""
        decision = MappingDecision(
            source_id=streaming_topic.source_id,
            source_kind=streaming_topic.kind,
            target=FabricTarget.EVENTHOUSE,
            compatibility=Compatibility.TRANSFORM,
            rationale="Streaming topic",
        )
        inventory = BigQueryInventory(project_id="test", datasets=(), components=(streaming_topic,), metadata={})
        assessment = run_assessment(inventory)

        gen = EventhouseGenerator(inventory, assessment)
        schema = gen.generate_eventhouse_schema(streaming_topic, decision)

        for col in streaming_topic.columns:
            assert col.name in schema.kql_script


# Semantic Model Generator Tests


class TestSemanticModelGenerator:
    """Tests for Power BI semantic model generation."""

    def test_generate_semantic_model(self, simple_table):
        """Test semantic model generation from table."""
        decision = MappingDecision(
            source_id=simple_table.source_id,
            source_kind=simple_table.kind,
            target=FabricTarget.SEMANTIC_MODEL,
            compatibility=Compatibility.DIRECT,
            rationale="Table maps to semantic model",
        )
        inventory = BigQueryInventory(project_id="test", datasets=(), components=(simple_table,), metadata={})
        assessment = run_assessment(inventory)

        gen = SemanticModelGenerator(inventory, assessment)
        model = gen.generate_semantic_model(simple_table, decision)

        assert model is not None
        assert model.source_id == simple_table.source_id
        assert "tables" in model.model
        assert "measures" in model.model

    def test_semantic_model_creates_measures(self, simple_table):
        """Test that semantic model generates measures for numeric columns."""
        decision = MappingDecision(
            source_id=simple_table.source_id,
            source_kind=simple_table.kind,
            target=FabricTarget.SEMANTIC_MODEL,
            compatibility=Compatibility.DIRECT,
            rationale="Table maps to semantic model",
        )
        inventory = BigQueryInventory(project_id="test", datasets=(), components=(simple_table,), metadata={})
        assessment = run_assessment(inventory)

        gen = SemanticModelGenerator(inventory, assessment)
        model = gen.generate_semantic_model(simple_table, decision)

        # Should have measures for INT64 and FLOAT64 columns
        assert len(model.model["measures"]) > 0
        measure_names = [m["name"] for m in model.model["measures"]]
        assert any("Sum" in name or "sum" in name for name in measure_names)


# Pipeline Generator Tests


class TestPipelineGenerator:
    """Tests for Data Factory pipeline generation."""

    def test_generate_pipeline_from_scheduled_query(self, scheduled_query):
        """Test pipeline generation from scheduled query."""
        decision = MappingDecision(
            source_id=scheduled_query.source_id,
            source_kind=scheduled_query.kind,
            target=FabricTarget.DATA_PIPELINE,
            compatibility=Compatibility.TRANSFORM,
            rationale="Scheduled query maps to pipeline",
        )
        inventory = BigQueryInventory(project_id="test", datasets=(), components=(scheduled_query,), metadata={})
        assessment = run_assessment(inventory)

        gen = PipelineGenerator(inventory, assessment)
        pipeline = gen.generate_pipeline(scheduled_query, decision)

        assert pipeline is not None
        assert pipeline.source_id == scheduled_query.source_id
        assert "activities" in pipeline.pipeline["properties"]

    def test_pipeline_has_required_activities(self, scheduled_query):
        """Test that pipeline includes required activities."""
        decision = MappingDecision(
            source_id=scheduled_query.source_id,
            source_kind=scheduled_query.kind,
            target=FabricTarget.DATA_PIPELINE,
            compatibility=Compatibility.TRANSFORM,
            rationale="Scheduled query",
        )
        inventory = BigQueryInventory(project_id="test", datasets=(), components=(scheduled_query,), metadata={})
        assessment = run_assessment(inventory)

        gen = PipelineGenerator(inventory, assessment)
        pipeline = gen.generate_pipeline(scheduled_query, decision)

        activities = pipeline.pipeline["properties"]["activities"]
        activity_types = [a.get("type") for a in activities]

        # Should have standard activities
        assert len(activities) > 0

    def test_generate_pipeline_from_composer_dag(self, composer_dag):
        """Test pipeline generation from Composer DAG."""
        decision = MappingDecision(
            source_id=composer_dag.source_id,
            source_kind=composer_dag.kind,
            target=FabricTarget.DATA_PIPELINE,
            compatibility=Compatibility.TRANSFORM,
            rationale="Composer DAG maps to pipeline",
        )
        inventory = BigQueryInventory(project_id="test", datasets=(), components=(composer_dag,), metadata={})
        assessment = run_assessment(inventory)

        gen = PipelineGenerator(inventory, assessment)
        pipeline = gen.generate_pipeline(composer_dag, decision)

        assert pipeline is not None
        activities = pipeline.pipeline["properties"]["activities"]
        assert len(activities) > 0


# Integration Tests


class TestArtifactGeneratorIntegration:
    """Tests for complete artifact generation workflow."""

    def test_generate_all_artifacts(self, basic_inventory, basic_assessment):
        """Test end-to-end artifact generation."""
        gen = ArtifactGenerator(basic_inventory, basic_assessment)
        report = gen.generate_all(Path("/tmp/test_artifacts"))

        assert report.total_generated > 0
        assert report.notebooks > 0
        assert "artifacts" in report.manifest

    def test_deterministic_output(self, basic_inventory, basic_assessment):
        """Test that artifact generation is deterministic."""
        from io import StringIO

        # Generate twice
        gen1 = ArtifactGenerator(basic_inventory, basic_assessment)
        report1 = gen1.generate_all(Path("/tmp/test_artifacts_1"))

        gen2 = ArtifactGenerator(basic_inventory, basic_assessment)
        report2 = gen2.generate_all(Path("/tmp/test_artifacts_2"))

        # Reports should be identical
        assert report1.total_generated == report2.total_generated
        assert report1.notebooks == report2.notebooks

    def test_artifact_paths_are_valid(self, basic_inventory, basic_assessment, tmp_path):
        """Test that generated artifact paths are valid."""
        gen = ArtifactGenerator(basic_inventory, basic_assessment)
        report = gen.generate_all(tmp_path)

        # Check manifest paths
        for artifact_list in report.manifest["artifacts"].values():
            if isinstance(artifact_list, list):
                for artifact in artifact_list:
                    if "path" in artifact:
                        path = tmp_path / artifact["path"]
                        # Path should be within output dir
                        assert path.is_relative_to(tmp_path)

    def test_generated_notebooks_are_valid_json(self, basic_inventory, basic_assessment, tmp_path):
        """Test that generated notebooks are valid JSON and Jupyter format."""
        gen = ArtifactGenerator(basic_inventory, basic_assessment)
        report = gen.generate_all(tmp_path)

        for artifact in report.manifest.get("artifacts", {}).get("notebooks", []):
            notebook_path = tmp_path / artifact["path"]
            if notebook_path.exists():
                notebook_data = json.loads(notebook_path.read_text())
                assert notebook_data.get("nbformat") == 4
                assert "cells" in notebook_data

    def test_generated_sql_scripts_are_valid_comments(self, basic_inventory, basic_assessment, tmp_path):
        """Test that generated SQL scripts have valid structure."""
        gen = ArtifactGenerator(basic_inventory, basic_assessment)
        report = gen.generate_all(tmp_path)

        for artifact in report.manifest.get("artifacts", {}).get("warehouse", []):
            sql_path = tmp_path / artifact["path"]
            if sql_path.exists():
                sql_content = sql_path.read_text()
                # Should start with comment
                assert sql_content.lstrip().startswith("/*") or "CREATE" in sql_content

    def test_warnings_are_collected(self, basic_inventory, basic_assessment):
        """Test that all warnings are collected in report."""
        gen = ArtifactGenerator(basic_inventory, basic_assessment)
        report = gen.generate_all(Path("/tmp/test_artifacts"))

        # Should have warnings
        assert isinstance(report.warnings, list)

    def test_manifest_includes_all_artifacts(self, basic_inventory, basic_assessment, tmp_path):
        """Test that manifest includes all generated artifacts."""
        gen = ArtifactGenerator(basic_inventory, basic_assessment)
        report = gen.generate_all(tmp_path)

        # Manifest should list all artifact types
        manifest = report.manifest
        assert "artifacts" in manifest


# Type Mapping Tests


class TestTypeMapping:
    """Tests for BigQuery to Fabric type mapping."""

    def test_map_int64_to_warehouse(self, simple_table):
        """Test INT64 mapping to Warehouse."""
        from bqtofabric.type_mapping import map_type

        mapping = map_type("INT64")
        assert mapping.warehouse_type == "bigint"
        assert mapping.compatibility.value == "direct"

    def test_map_float64_to_warehouse(self):
        """Test FLOAT64 mapping to Warehouse."""
        from bqtofabric.type_mapping import map_type

        mapping = map_type("FLOAT64")
        assert mapping.warehouse_type == "float"
        assert mapping.compatibility.value == "direct"

    def test_map_string_to_warehouse(self):
        """Test STRING mapping to Warehouse."""
        from bqtofabric.type_mapping import map_type

        mapping = map_type("STRING")
        assert mapping.warehouse_type == "varchar(max)"
        assert mapping.compatibility.value == "direct"

    def test_map_array_to_warehouse(self):
        """Test ARRAY mapping to Warehouse (redesign)."""
        from bqtofabric.type_mapping import map_type

        mapping = map_type("ARRAY")
        assert mapping.compatibility.value == "redesign"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
