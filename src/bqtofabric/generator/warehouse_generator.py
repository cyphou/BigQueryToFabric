"""Generate production-ready Warehouse DDL/DML from BigQuery tables and views."""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

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
    valid: bool = True


@dataclass(frozen=True, slots=True)
class TsqlValidationResult:
    """Result of validating T-SQL for Fabric Warehouse compatibility."""

    valid: bool
    reason: str | None = None
    recommendation: str | None = None
    unsupported_features: list[str] = field(default_factory=list)


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
        valid = True

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
            view_lines, valid = self._build_view_creation(item, schema_name, warnings)
            lines.extend(view_lines)
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
            valid=valid,
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
            f"  PRINT 'Existing table [{schema}].[{item.name}] preserved.'\n",
            "ELSE\n",
            "BEGIN\n",
            f"  CREATE TABLE [{schema}].[{item.name}] (\n",
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

        lines.append(",\n".join(f"  {column.strip()}" for column in col_defs))

        lines.append("\n")

        lines.extend([
            "  )\n",
            "END\n",
            "GO\n",
            "\n",
        ])

        if item.clustering_fields:
            index_name = f"idx_{'_'.join(item.clustering_fields)}"
            columns = ", ".join(item.clustering_fields)
            lines.append(
                f"-- Suggested index: CREATE INDEX {index_name} ON {item.name}({columns})\n\n"
            )

        return lines

    def _build_view_creation(
        self, item: BigQueryObject, schema: str, warnings: list[str]
    ) -> tuple[list[str], bool]:
        """Build CREATE VIEW statement."""
        lines = [
            f"-- Create view: {item.name}\n",
            "-- Existing views are preserved; review and explicitly replace them if required.\n",
            "\n",
        ]
        valid = True

        if item.sql:
            validation = self._validate_t_sql_semantics(item.sql)
            if not validation.valid:
                valid = False
                lines.append("# VALIDATION PENDING\n")
                warnings.append(
                    "REDESIGN: View SQL syntax requires manual review for Fabric Warehouse "
                    "compatibility."
                )
                if validation.reason:
                    warnings.append(f"Validation: {validation.reason}")
            escaped_sql = item.sql.replace("'", "''")
            lines.extend([
                f"IF OBJECT_ID(N'[{schema}].[{item.name}]', N'V') IS NULL\n",
                "BEGIN\n",
                f"  EXEC(N'CREATE VIEW [{schema}].[{item.name}] AS {escaped_sql}')\n",
                "END\n",
                "ELSE\n",
                f"  PRINT 'Existing view [{schema}].[{item.name}] preserved.'\n",
            ])
        else:
            lines.append("-- TODO: MANUAL REVIEW - Add view definition from source\n")
            warnings.append("View SQL not provided; manual SQL definition required")
            valid = False

        lines.extend([
            "GO\n",
            "\n",
        ])

        return lines, valid

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
            f"  PRINT 'Existing table [{schema}].[{table_name}] preserved.'\n",
            "ELSE\n",
            "BEGIN\n",
            f"  CREATE TABLE [{schema}].[{table_name}] (\n",
        ])

        col_defs: list[str] = []
        if item.columns:
            for col in item.columns:
                col_type = self._map_column_type(col, warnings)
                nullable = "NOT NULL" if not col.nullable else "NULL"
                col_defs.append(f"  [{col.name}] {col_type} {nullable}")

        col_defs.append("  [_load_timestamp] DATETIME2 DEFAULT GETUTCDATE()")
        lines.append(",\n".join(col_defs))

        lines.extend([
            "\n  )\n",
            "END\n",
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

    def _validate_t_sql_semantics(self, sql: str) -> TsqlValidationResult:
        """Validate SQL features that Fabric Warehouse does not support."""
        try:
            statements = sqlglot.parse(sql, read="tsql")
        except ParseError as error:
            return TsqlValidationResult(
                valid=False,
                reason=str(error),
                recommendation="Rewrite the SQL using Fabric Warehouse T-SQL syntax.",
                unsupported_features=["parse error"],
            )

        unsupported: list[str] = []
        for statement in statements:
            if statement is None:
                continue
            for node in statement.walk():
                if isinstance(node, exp.Except) and node.args.get("distinct") is False:
                    unsupported.append("EXCEPT ALL")
                elif isinstance(node, exp.Intersect) and node.args.get("distinct") is False:
                    unsupported.append("INTERSECT ALL")
                elif isinstance(node, exp.Qualify):
                    unsupported.append("QUALIFY")
                elif isinstance(node, exp.Window) and not self._is_supported_window_frame(node):
                    unsupported.append("window frame")
                elif node.key in {"unnest", "array", "struct", "pivotany", "match_recognize"}:
                    unsupported.append(node.key.upper())

        if unsupported:
            features = list(dict.fromkeys(unsupported))
            return TsqlValidationResult(
                valid=False,
                reason=f"Unsupported Fabric Warehouse feature: {', '.join(features)}.",
                recommendation="Rewrite the query using supported Fabric Warehouse T-SQL constructs.",
                unsupported_features=features,
            )
        return TsqlValidationResult(valid=True)

    @staticmethod
    def _is_supported_window_frame(window: exp.Window) -> bool:
        """Allow only ROWS frames bounded by UNBOUNDED PRECEDING/FOLLOWING."""
        specification = window.args.get("spec")
        if specification is None:
            return True
        return (
            specification.args.get("kind") == "ROWS"
            and specification.args.get("start") == "UNBOUNDED"
            and specification.args.get("start_side") == "PRECEDING"
            and specification.args.get("end") in {None, "UNBOUNDED"}
            and specification.args.get("end_side") in {None, "FOLLOWING"}
        )


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
