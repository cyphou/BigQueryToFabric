"""Generate production-ready Warehouse DDL/DML from BigQuery tables and views."""

from __future__ import annotations

from dataclasses import dataclass

from ..assessment import AssessmentReport
from ..mapping import FabricTarget, MappingDecision
from ..models import BigQueryInventory, BigQueryObject, Column, ObjectKind
from ..type_mapping import map_type


@dataclass(frozen=True, slots=True)
class WarehouseScript:
    """Complete T-SQL script for Warehouse."""

    name: str
    description: str
    source_id: str
    source_kind: ObjectKind
    script: str
    warnings: tuple[str, ...] = ()


class WarehouseGenerator:
    """Generate Fabric Warehouse T-SQL DDL/DML."""

    def __init__(self, inventory: BigQueryInventory, assessment: AssessmentReport) -> None:
        """Initialize with inventory and assessment data."""
        self.inventory = inventory
        self.assessment = assessment
        self.objects = {obj.source_id: obj for obj in inventory.objects()}

    def generate_warehouse_script(
        self, item: BigQueryObject, decision: MappingDecision
    ) -> WarehouseScript | None:
        """Generate a T-SQL script for a table, view, or scheduled query."""
        if item.kind not in {
            ObjectKind.TABLE,
            ObjectKind.VIEW,
            ObjectKind.MATERIALIZED_VIEW,
            ObjectKind.SCHEDULED_QUERY,
        }:
            return None

        lines: list[str] = []
        warnings: list[str] = []

        # Header comment
        lines.extend(self._build_header(item, decision))

        # Schema creation
        schema_name = item.dataset or "dbo"
        lines.append("-- Create schema if it does not exist\n")
        lines.extend(self._build_schema_creation(schema_name))

        # Table/View creation
        if item.kind in {ObjectKind.TABLE, ObjectKind.MATERIALIZED_VIEW}:
            lines.extend(self._build_table_creation(item, schema_name, warnings))
        elif item.kind is ObjectKind.VIEW:
            lines.extend(self._build_view_creation(item, schema_name, warnings))
        elif item.kind is ObjectKind.SCHEDULED_QUERY:
            lines.extend(self._build_scheduled_query_artifacts(item, schema_name, warnings))

        script = "\n".join(lines)
        return WarehouseScript(
            name=f"warehouse_{item.name}",
            description=f"Generated from {item.kind.value} {item.source_id}",
            source_id=item.source_id,
            source_kind=item.kind,
            script=script,
            warnings=tuple(warnings),
        )

    def _build_header(self, item: BigQueryObject, decision: MappingDecision) -> list[str]:
        """Build SQL header comment."""
        return [
            "/*\n",
            "  Generated Fabric Warehouse Script\n",
            f"  Source: {item.source_id}\n",
            f"  Kind: {item.kind.value}\n",
            f"  Dataset: {item.dataset}\n",
            f"  Compatibility: {decision.compatibility.value}\n",
            f"  Rationale: {decision.rationale}\n",
            "*/\n",
            "\n",
        ]

    def _build_schema_creation(self, schema_name: str) -> list[str]:
        """Build schema creation SQL."""
        return [
            f"IF NOT EXISTS (SELECT * FROM sys.schemas WHERE name = '{schema_name}')\n",
            "BEGIN\n",
            f"  CREATE SCHEMA [{schema_name}]\n",
            "END\n",
            "GO\n",
            "\n",
        ]

    def _build_table_creation(self, item: BigQueryObject, schema: str, warnings: list[str]) -> list[str]:
        """Build CREATE TABLE statement."""
        lines = [
            f"-- Create table: {item.name}\n",
            f"-- BigQuery size: {item.size_bytes or 'unknown'} bytes\n",
        ]

        if item.partition_field:
            lines.append(f"-- Partitioning column: {item.partition_field}\n")
        if item.clustering_fields:
            lines.append(f"-- Clustering columns: {', '.join(item.clustering_fields)}\n")

        lines.extend([
            "\n",
            f"IF OBJECT_ID(N'[{schema}].[{item.name}]', N'U') IS NOT NULL\n",
            f"  DROP TABLE [{schema}].[{item.name}]\n",
            "GO\n",
            "\n",
            f"CREATE TABLE [{schema}].[{item.name}] (\n",
        ])

        # Build column definitions
        col_defs: list[str] = []
        for col in item.columns:
            col_type = self._map_column_type(col, warnings)
            nullable = "NOT NULL" if not col.nullable else "NULL"
            col_def = f"  [{col.name}] {col_type} {nullable}"
            if col.description:
                col_def += f" -- {col.description}"
            col_defs.append(col_def)

        lines.append(",\n".join(col_defs))

        # Add primary key if detectable
        if item.clustering_fields:
            lines.append(f",\n  PRIMARY KEY NONCLUSTERED ({', '.join(f'[{f}]' for f in item.clustering_fields)})\n")
        else:
            lines.append("\n")

        lines.extend([
            ")\n",
            "GO\n",
            "\n",
        ])

        # Add indexing recommendation for clustering columns
        if item.clustering_fields:
            for field in item.clustering_fields:
                lines.extend([
                    "-- Recommended index for clustering column\n",
                    f"CREATE NONCLUSTERED INDEX IX_{item.name}_{field}\n",
                    f"  ON [{schema}].[{item.name}] ([{field}])\n",
                    "GO\n",
                    "\n",
                ])

        return lines

    def _build_view_creation(self, item: BigQueryObject, schema: str, warnings: list[str]) -> list[str]:
        """Build CREATE VIEW statement."""
        lines = [
            f"-- Create view: {item.name}\n",
            "\n",
            f"IF OBJECT_ID(N'[{schema}].[{item.name}]', N'V') IS NOT NULL\n",
            f"  DROP VIEW [{schema}].[{item.name}]\n",
            "GO\n",
            "\n",
            f"CREATE VIEW [{schema}].[{item.name}]\n",
            "AS\n",
        ]

        if item.sql:
            # Convert BigQuery SQL to T-SQL
            converted_sql = self._convert_sql_to_tsql(item.sql, warnings)
            lines.extend([f"{line}\n" for line in converted_sql.split("\n")])
        else:
            lines.append("-- TODO: MANUAL REVIEW - Add view definition from source\n")
            warnings.append("View SQL not provided; manual SQL definition required")

        lines.extend([
            "GO\n",
            "\n",
        ])

        return lines

    def _build_scheduled_query_artifacts(self, item: BigQueryObject, schema: str, warnings: list[str]) -> list[str]:
        """Build artifacts for scheduled queries."""
        lines = [
            f"-- Scheduled Query: {item.name}\n",
            "-- TODO: MANUAL REVIEW - Implement as Fabric Data Pipeline trigger\n",
            "\n",
            "-- Create destination table for scheduled query results\n",
        ]

        table_name = f"{item.name}_result"
        lines.extend([
            f"IF OBJECT_ID(N'[{schema}].[{table_name}]', N'U') IS NOT NULL\n",
            f"  DROP TABLE [{schema}].[{table_name}]\n",
            "GO\n",
            "\n",
            f"CREATE TABLE [{schema}].[{table_name}] (\n",
        ])

        if item.columns:
            col_defs: list[str] = []
            for col in item.columns:
                col_type = self._map_column_type(col, warnings)
                nullable = "NOT NULL" if not col.nullable else "NULL"
                col_defs.append(f"  [{col.name}] {col_type} {nullable}")

            lines.append(",\n".join(col_defs))

        lines.extend([
            ",\n  [_load_timestamp] DATETIME2 DEFAULT GETUTCDATE()\n",
            ")\n",
            "GO\n",
            "\n",
            "-- Merge or insert logic would go here\n",
            "-- See Data Factory pipeline for orchestration\n",
            "\n",
        ])

        warnings.append("Scheduled query: configure Data Factory Data Pipeline for scheduling")

        return lines

    def _map_column_type(self, col: Column, warnings: list[str]) -> str:
        """Map BigQuery column type to T-SQL type."""
        type_mapping = map_type(col.data_type)

        if type_mapping.warehouse_type is None:
            warnings.append(f"Column {col.name}: {col.data_type} maps to {type_mapping.compatibility.value}")
            return "varchar(max) -- REVIEW TYPE MAPPING"

        return type_mapping.warehouse_type

    def _convert_sql_to_tsql(self, bq_sql: str, warnings: list[str]) -> str:
        """Convert BigQuery SQL to T-SQL (basic conversion)."""
        sql = bq_sql

        # Common BigQuery → T-SQL conversions
        replacements = [
            ("EXCEPT", "EXCEPT ALL"),  # BigQuery EXCEPT is EXCEPT ALL in T-SQL
            ("ARRAY_AGG", "STRING_AGG"),  # Array aggregation
            ("TIMESTAMP_MILLIS", "DATEADD(ms, ?, '1970-01-01')"),  # Timestamp conversion
            ("CURRENT_TIMESTAMP()", "GETUTCDATE()"),  # Current timestamp
            ("CURRENT_DATE()", "CAST(GETUTCDATE() AS DATE)"),  # Current date
            ("DATE_ADD", "DATEADD"),  # Date arithmetic
            ("_PARTITIONTIME", "[_partition_time]"),  # Partition column
        ]

        for bq_pattern, tsql_pattern in replacements:
            if bq_pattern in sql:
                sql = sql.replace(bq_pattern, tsql_pattern)
                warnings.append(f"SQL conversion: replaced {bq_pattern} with {tsql_pattern}")

        # Check for unsupported patterns
        if "STRUCT<" in sql or "ARRAY<" in sql:
            warnings.append("SQL contains nested types (STRUCT/ARRAY); flatten may be required")

        sql += "\n-- TODO: MANUAL REVIEW - Validate T-SQL syntax"

        return sql


def generate_all_warehouse_scripts(
    inventory: BigQueryInventory,
    assessment: AssessmentReport,
) -> dict[str, WarehouseScript]:
    """Generate all warehouse scripts from inventory and assessment."""
    gen = WarehouseGenerator(inventory, assessment)
    objects = {obj.source_id: obj for obj in inventory.objects()}
    decisions = {dec.source_id: dec for dec in assessment.decisions}

    scripts: dict[str, WarehouseScript] = {}
    for source_id, decision in decisions.items():
        if decision.target not in {FabricTarget.WAREHOUSE, FabricTarget.SQL_DATABASE}:
            continue
        item = objects.get(source_id)
        if item is None:
            continue
        script = gen.generate_warehouse_script(item, decision)
        if script is not None:
            scripts[source_id] = script

    return scripts
