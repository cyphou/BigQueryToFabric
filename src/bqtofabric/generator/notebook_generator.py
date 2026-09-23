"""Generate production-ready Lakehouse notebooks from Dataproc/Dataform workloads."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ..artifact_validation import NotebookValidator
from ..assessment import AssessmentReport
from ..converter.models import SparkCodeLanguage
from ..converter.spark_converter import SparkConverter
from ..mapping import FabricTarget, MappingDecision
from ..models import BigQueryInventory, BigQueryObject, ObjectKind


@dataclass(frozen=True, slots=True)
class NotebookCell:
    """Represents a Jupyter notebook cell."""

    cell_type: str  # "code", "markdown"
    source: list[str]
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class FabricNotebook:
    """Complete Jupyter notebook definition."""

    title: str
    description: str
    source_id: str
    source_kind: ObjectKind
    cells: tuple[NotebookCell, ...]
    metadata: dict[str, Any] | None = None
    valid: bool = True
    warnings: tuple[str, ...] = ()

    def to_ipynb_dict(self) -> dict[str, Any]:
        """Convert to Jupyter .ipynb format (nbformat 4)."""
        return {
            "cells": [
                {
                    "cell_type": cell.cell_type,
                    "source": cell.source,
                    "metadata": cell.metadata or {},
                    **({"execution_count": None, "outputs": []} if cell.cell_type == "code" else {}),
                }
                for cell in self.cells
            ],
            "metadata": {
                "kernelspec": {"display_name": "Synapse PySpark", "language": "python", "name": "synapsepyspark"},
                "language_info": {
                    "name": "python",
                    "version": "3.11.0",
                    "mimetype": "text/x-python",
                    "codemirror_mode": {"name": "ipython", "version": 3},
                    "pygments_lexer": "ipython3",
                    "nbconvert_exporter": "python",
                    "file_extension": ".py",
                },
                **(self.metadata or {}),
            },
            "nbformat": 4,
            "nbformat_minor": 4,
        }


class NotebookGenerator:
    """Generate Fabric Lakehouse notebooks."""

    def __init__(self, inventory: BigQueryInventory, assessment: AssessmentReport) -> None:
        """Initialize with inventory and assessment data."""
        self.inventory = inventory
        self.assessment = assessment
        self.objects = {obj.source_id: obj for obj in inventory.objects()}

    def generate_notebook(self, item: BigQueryObject, decision: MappingDecision) -> FabricNotebook | None:
        """Generate a notebook for a Dataproc or Dataform object."""
        if item.kind not in {ObjectKind.SPARK_JOB, ObjectKind.DATAPROC_JOB, ObjectKind.DATAFORM_WORKFLOW}:
            return None

        cells: list[NotebookCell] = []
        warnings: list[str] = []

        # Cell 1: Markdown header with metadata
        title_md = self._build_title_cell(item, decision)
        cells.append(title_md)

        # Cell 2: Spark configuration (%configure must be alone and first in its cell)
        cells.append(self._build_configure_cell())
        cells.append(self._build_parameter_cell(item))

        # Cell 3+: Converted code
        code_cells = self._build_code_cells(item, decision, warnings)
        cells.extend(code_cells)

        # Cell N: Sink to Lakehouse
        sink_cell = self._build_sink_cell(item, decision)
        cells.append(sink_cell)

        # Cell N+1: Warnings and checklist
        warnings_cell = self._build_warnings_cell(item, decision)
        cells.append(warnings_cell)

        notebook = FabricNotebook(
            title=f"Notebook: {item.name}",
            description=f"Generated from {item.kind.value} {item.source_id}",
            source_id=item.source_id,
            source_kind=item.kind,
            cells=tuple(cells),
            metadata={"tags": ["auto-generated", item.kind.value]},
        )
        validation = NotebookValidator(notebook).validate()
        warnings.extend(validation.errors)
        return replace(notebook, valid=validation.valid, warnings=tuple(warnings))

    def _build_title_cell(self, item: BigQueryObject, decision: MappingDecision) -> NotebookCell:
        """Build the markdown header cell."""
        lines = [
            f"# {item.name}\n",
            "\n",
            "**Generated Fabric Lakehouse Notebook**\n",
            "\n",
            "| Property | Value |\n",
            "|---|---|\n",
            f"| **Source ID** | `{item.source_id}` |\n",
            f"| **Source Kind** | {item.kind.value} |\n",
            f"| **Target** | {decision.target.value} |\n",
            f"| **Compatibility** | {decision.compatibility.value} |\n",
            f"| **Dataset** | {item.dataset} |\n",
            "\n",
            "**Description:**\n",
            f"{decision.rationale}\n",
            "\n",
            "**Source Dependencies:**\n",
        ]
        if item.dependencies:
            for dep in sorted(item.dependencies):
                lines.append(f"- `{dep}`\n")
        else:
            lines.append("- None\n")

        return NotebookCell(cell_type="markdown", source=lines)

    def _build_configure_cell(self) -> NotebookCell:
        """Build the %configure cell, which Fabric requires to stand alone."""
        return NotebookCell(
            cell_type="code",
            source=[
                "%configure -f\n",
                "{\n",
                '    "conf": {\n',
                '        "spark.sql.shuffle.partitions": "200",\n',
                '        "spark.sql.adaptive.enabled": "true",\n',
                '        "spark.sql.files.ignoreCorruptFiles": "false"\n',
                "    }\n",
                "}\n",
            ],
        )

    def _build_parameter_cell(self, item: BigQueryObject) -> NotebookCell:
        """Build the configuration parameter cell."""
        runtime = item.properties.get("runtime_version", "3.11")
        py_version = "3.11" if "3.1" in str(runtime) else "3.9"
        return NotebookCell(
            cell_type="code",
            source=[
                "# Configuration parameters\n",
                "# Modify these values before executing the notebook\n",
                "\n",
                'INPUT_PATH = "/Shortcuts/onelake_gcs_bucket/input"\n',
                'OUTPUT_PATH = "/Lakehouse/Tables/output_table"\n',
                "PARTITION_DATE = None  # Set to override default date partition\n",
                f"# Runtime: Python {py_version}\n",
            ],
        )

    def _build_code_cells(
        self, item: BigQueryObject, decision: MappingDecision, warnings: list[str]
    ) -> list[NotebookCell]:
        """Build code cells from converted Spark/SQL code."""
        cells: list[NotebookCell] = []

        # Import cell
        import_lines = [
            "from pyspark.sql import SparkSession\n",
            "from pyspark.sql.functions import col, when, year, month, dayofmonth\n",
            "from pyspark.sql.types import StructType, StructField, StringType, LongType, DoubleType\n",
            "import json\n",
            "\n",
            "# Initialize Spark session\n",
            "spark = SparkSession.getActiveSession() or SparkSession.builder.getOrCreate()\n",
        ]
        cells.append(NotebookCell(cell_type="code", source=import_lines))

        source_code = item.properties.get("code")
        if isinstance(source_code, str) and source_code.strip():
            cells.append(self._build_converted_code_cell(item, source_code, warnings))
        elif item.sql:
            sql_lines = [
                f"# Source SQL from {item.source_id}\n",
                "# TODO: MANUAL REVIEW - Validate SQL syntax and adjust for Fabric\n",
                "\n",
                "source_sql = \"\"\"\n",
                *[f"{line}\n" for line in item.sql.split("\n")],
                "\"\"\"\n",
                "\n",
                "df_source = spark.sql(source_sql)\n",
                "print(f\"Loaded {df_source.count()} rows\")\n",
            ]
            cells.append(NotebookCell(cell_type="code", source=sql_lines))
        else:
            warnings.append(
                "Source logic was not carried over; the notebook loads from INPUT_PATH "
                "and requires the original transformation to be reimplemented."
            )
            cells.append(NotebookCell(cell_type="code", source=[
                f"# TODO: MANUAL REVIEW - Source logic from {item.source_id} was not converted.\n",
                "# Point INPUT_PATH at the migrated source and reimplement the original job.\n",
                "\n",
                "df_source = spark.read.format('delta').load(INPUT_PATH)\n",
            ]))

        # Transformation placeholder
        transform_lines = [
            "# Apply transformations\n",
            "# TODO: MANUAL REVIEW - Add custom transformation logic\n",
            "\n",
            "df_transformed = df_source\n",
            "# Example transformation:\n",
            "# df_transformed = df_source.filter(col('is_active') == True)\n",
        ]
        cells.append(NotebookCell(cell_type="code", source=transform_lines))

        return cells

    def _build_converted_code_cell(
        self, item: BigQueryObject, source_code: str, warnings: list[str]
    ) -> NotebookCell:
        """Emit the converted source body so the notebook carries the original logic."""
        language = str(item.properties.get("language", "python")).strip().lower()
        spark_language = (
            SparkCodeLanguage.SCALA if "scala" in language else SparkCodeLanguage.PYSPARK
        )
        conversion = SparkConverter().convert(item.source_id, source_code, spark_language)

        warnings.extend(warning.message for warning in conversion.warnings)
        warnings.extend(step.step for step in conversion.manual_steps)

        if not conversion.target_text.strip():
            warnings.append(
                f"{spark_language.value} source could not be converted; the original body "
                "is preserved as a comment and must be reimplemented."
            )
            return NotebookCell(cell_type="code", source=[
                (
                    f"# TODO: MANUAL REVIEW - {spark_language.value} source from "
                    f"{item.source_id} has no automatic conversion path.\n"
                ),
                "# Original source retained for reference:\n",
                *[f"# {line}\n" for line in source_code.splitlines()],
                "\n",
                "df_source = spark.read.format('delta').load(INPUT_PATH)\n",
            ])

        lines = [
            f"# Converted from {item.source_id}\n",
            "# TODO: MANUAL REVIEW - Verify the converted logic against the source job.\n",
            "\n",
            *[f"{line}\n" for line in conversion.target_text.splitlines()],
        ]
        # The converted body owns the pipeline, so expose its result under the name the
        # sink cell expects without assuming the source defined it.
        if "df_source" not in conversion.target_text:
            lines.extend([
                "\n",
                "# TODO: MANUAL REVIEW - Point df_source at the DataFrame this job produces.\n",
                "df_source = spark.read.format('delta').load(INPUT_PATH)\n",
            ])
            warnings.append(
                "Converted code does not define df_source; the sink cell needs to be bound "
                "to the DataFrame the job produces."
            )
        return NotebookCell(cell_type="code", source=lines)

    def _build_sink_cell(self, item: BigQueryObject, decision: MappingDecision) -> NotebookCell:
        """Build the Lakehouse sink cell."""
        lines = [
            "# Write to Lakehouse\n",
            f"# Destination table: {item.name}\n",
            "\n",
            f"output_table_name = '{item.name}'\n",
            "output_path = OUTPUT_PATH\n",
            "\n",
            "df_transformed.write\\\n",
            "    .format('delta')\\\n",
            "    .mode('overwrite')\\\n",
            "    .option('mergeSchema', 'true')\\\n",
            "    .option('path', output_path)\\\n",
            "    .save()\n",
            "\n",
            "print(f'Successfully wrote {df_transformed.count()} rows to {output_table_name}')\n",
        ]

        return NotebookCell(cell_type="code", source=lines)

    def _build_warnings_cell(self, item: BigQueryObject, decision: MappingDecision) -> NotebookCell:
        """Build the warnings and validation checklist cell."""
        lines = [
            "# Validation Checklist\n",
            "\n",
            "## ⚠️ Manual Review Required\n",
            "\n",
        ]

        # Add compatibility warnings
        if decision.compatibility.value == "transform":
            lines.append(f"- **Transform Required**: {decision.rationale}\n")
        elif decision.compatibility.value == "redesign":
            lines.append(f"- **Redesign Required**: {decision.rationale}\n")

        # Add action items
        if decision.actions:
            lines.append("\n## Actions\n\n")
            for action in decision.actions:
                lines.append(f"- [ ] {action}\n")

        # Add conversion warnings with TODO markers
        lines.append("\n## Manual Steps (TODO)\n\n")
        if item.properties.get("uses_gcs"):
            lines.append("- [ ] **TODO**: Replace `gs://` paths with OneLake Shortcuts or relative paths\n")
        if item.properties.get("uses_bigquery_connector"):
            lines.append("- [ ] **TODO**: Update BigQuery connector to use Fabric native BigQuery connector\n")
        if item.properties.get("streaming"):
            lines.append("- [ ] **TODO**: Configure Structured Streaming with proper checkpoint and trigger settings\n")

        # Always add validation TODOs
        lines.extend([
            "- [ ] **TODO**: Review and validate all cell outputs\n",
            "- [ ] **TODO**: Test end-to-end data flow\n",
            "- [ ] **TODO**: Verify error handling and retry logic\n",
        ])

        lines.append("\n## Next Steps\n\n")
        lines.append("1. Review and execute each cell in sequence\n")
        lines.append("2. Validate data lineage and schema\n")
        lines.append("3. Test incremental refresh if applicable\n")
        lines.append("4. Schedule notebook in Data Factory pipeline if needed\n")

        return NotebookCell(cell_type="markdown", source=lines)


def generate_all_notebooks(
    inventory: BigQueryInventory,
    assessment: AssessmentReport,
) -> dict[str, FabricNotebook]:
    """Generate all notebooks from inventory and assessment."""
    gen = NotebookGenerator(inventory, assessment)
    objects = {obj.source_id: obj for obj in inventory.objects()}
    decisions = {dec.source_id: dec for dec in assessment.decisions}

    notebooks: dict[str, FabricNotebook] = {}
    for source_id, decision in decisions.items():
        if decision.target not in {FabricTarget.NOTEBOOK, FabricTarget.LAKEHOUSE}:
            continue
        item = objects.get(source_id)
        if item is None:
            continue
        notebook = gen.generate_notebook(item, decision)
        if notebook is not None:
            notebooks[source_id] = notebook

    return notebooks
