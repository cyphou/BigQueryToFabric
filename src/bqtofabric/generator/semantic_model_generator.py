"""Generate Power BI semantic model scaffolding for analytics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..assessment import AssessmentReport
from ..mapping import FabricTarget, MappingDecision
from ..models import BigQueryInventory, BigQueryObject, Column, ObjectKind


@dataclass(frozen=True, slots=True)
class SemanticModelDefinition:
    """Complete Power BI semantic model definition."""

    name: str
    description: str
    source_id: str
    source_kind: ObjectKind
    model: dict[str, Any]
    warnings: tuple[str, ...] = ()
    valid: bool = True


class SemanticModelGenerator:
    """Generate Power BI semantic models."""

    def __init__(self, inventory: BigQueryInventory, assessment: AssessmentReport) -> None:
        """Initialize with inventory and assessment data."""
        self.inventory = inventory
        self.assessment = assessment
        self.objects = {obj.source_id: obj for obj in inventory.objects()}
        self.decisions = {dec.source_id: dec for dec in assessment.decisions}

    def generate_semantic_model(
        self, item: BigQueryObject, decision: MappingDecision
    ) -> SemanticModelDefinition | None:
        """Generate a Power BI semantic model for a table or view."""
        if item.kind not in {
            ObjectKind.TABLE,
            ObjectKind.VIEW,
            ObjectKind.MATERIALIZED_VIEW,
        }:
            return None

        warnings: list[str] = []
        model: dict[str, Any] = {
            "name": item.name,
            "description": decision.rationale,
            "compatibilityLevel": 1604,
            "sourceId": item.source_id,
            "sourceKind": item.kind.value,
        }

        # Define tables
        model["tables"] = self._build_tables(item, decision, warnings)

        # Define measures
        model["measures"] = self._build_measures(item, warnings)

        # Define relationships
        model["relationships"] = self._build_relationships(item, warnings)

        # Define hierarchies
        model["hierarchies"] = self._build_hierarchies(item, warnings)

        # Connection properties
        model["connections"] = [
            {
                "connectionType": "DirectQuery" if item.kind is ObjectKind.VIEW else "Import",
                "mode": "directLake" if item.kind is ObjectKind.TABLE else None,
                "sourceType": decision.target.value,
                "connectionString": "Data Source=$(FABRIC_WORKSPACE_ID);Initial Catalog=$(FABRIC_LAKEHOUSE_ID);",
                "credentials": "managedIdentity",
            }
        ]

        model["warnings"] = [
            "TODO: MANUAL REVIEW - Configure connection credentials",
            "TODO: MANUAL REVIEW - Test measures and relationships",
            "TODO: MANUAL REVIEW - Add calculated columns and custom hierarchies",
        ]

        return SemanticModelDefinition(
            name=f"semantic_model_{item.name}",
            description=f"Generated from {item.kind.value} {item.source_id}",
            source_id=item.source_id,
            source_kind=item.kind,
            model=model,
            warnings=tuple(warnings),
        )

    def _build_tables(
        self, item: BigQueryObject, decision: MappingDecision, warnings: list[str]
    ) -> list[dict[str, Any]]:
        """Build table definitions from columns."""
        tables: list[dict[str, Any]] = []

        table: dict[str, Any] = {
            "name": item.name,
            "isHidden": False,
            "source": {
                "type": "m",
                "expression": f'"{decision.target.value}.{item.dataset}.{item.name}"',
            },
            "columns": [],
        }

        # Add columns
        for col in item.columns:
            column_def = self._build_column(col, warnings)
            table["columns"].append(column_def)

        # Add row-level security note
        if item.properties.get("access_filters"):
            warnings.append(f"Table {item.name}: Row-level security configured; map to Fabric roles")

        tables.append(table)
        return tables

    def _build_column(self, col: Column, warnings: list[str]) -> dict[str, Any]:
        """Build column definition with Power BI data type."""
        # Map to Power BI data types
        type_map = {
            "BOOL": "true/false",
            "INT64": "Whole Number",
            "FLOAT64": "Decimal Number",
            "NUMERIC": "Decimal Number",
            "BIGNUMERIC": "Decimal Number",
            "STRING": "Text",
            "BYTES": "Binary",
            "DATE": "Date",
            "DATETIME": "Date/Time",
            "TIMESTAMP": "Date/Time",
            "JSON": "Text",
            "ARRAY": "Text",
            "STRUCT": "Text",
        }

        normalized_type = col.data_type.upper().split("<", 1)[0]
        pbi_type = type_map.get(normalized_type, "Text")

        if normalized_type not in type_map:
            warnings.append(f"Column {col.name}: type {col.data_type} mapped to {pbi_type}")

        return {
            "name": col.name,
            "dataType": pbi_type,
            "isHidden": False,
            "expression": col.name,
            "description": col.description or f"Generated from {col.data_type}",
        }

    def _build_measures(self, item: BigQueryObject, warnings: list[str]) -> list[dict[str, Any]]:
        """Auto-generate common measures from numeric columns."""
        measures: list[dict[str, Any]] = []

        for col in item.columns:
            if col.data_type.upper() in {"INT64", "FLOAT64", "NUMERIC", "BIGNUMERIC"}:
                # Sum measure
                measures.append({
                    "name": f"Sum of {col.name}",
                    "expression": f"SUM('{item.name}'[{col.name}])",
                    "isHidden": False,
                    "formatString": "0.00",
                    "displayFolder": "Summary Metrics",
                })

                # Average measure
                measures.append({
                    "name": f"Average of {col.name}",
                    "expression": f"AVERAGE('{item.name}'[{col.name}])",
                    "isHidden": False,
                    "formatString": "0.00",
                    "displayFolder": "Summary Metrics",
                })

                # Count measure
                measures.append({
                    "name": f"Count of {col.name}",
                    "expression": f"COUNTBLANK('{item.name}'[{col.name}])",
                    "isHidden": False,
                    "displayFolder": "Summary Metrics",
                })

        # Add row count measure
        measures.append({
            "name": "Row Count",
            "expression": f"COUNTA('{item.name}'[{item.columns[0].name}])",
            "isHidden": False,
            "displayFolder": "Summary Metrics",
        })

        if measures:
            warnings.append(f"Generated {len(measures)} placeholder measures; customize as needed")

        return measures

    def _build_relationships(self, item: BigQueryObject, warnings: list[str]) -> list[dict[str, Any]]:
        """Build relationships based on detected foreign keys."""
        relationships: list[dict[str, Any]] = []

        # Check for detected relationships in properties
        detected_fks = item.properties.get("detected_foreign_keys", [])
        for fk_def in detected_fks:
            relationships.append({
                "name": f"fk_{fk_def.get('column', 'unknown')}",
                "fromTable": item.name,
                "fromColumn": fk_def.get("column"),
                "toTable": fk_def.get("referenced_table", "Review"),
                "toColumn": fk_def.get("referenced_column", "Review"),
                "crossFilteringBehavior": "both",
                "isActive": False,  # Default to inactive; requires manual review
                "status": "REVIEW_REQUIRED",
            })

        if detected_fks:
            warnings.append(
                f"Detected {len(detected_fks)} potential foreign keys; manually review and activate relationships"
            )

        return relationships

    def _build_hierarchies(self, item: BigQueryObject, warnings: list[str]) -> list[dict[str, Any]]:
        """Build hierarchies from temporal and categorical columns."""
        hierarchies: list[dict[str, Any]] = []

        # Detect date columns for hierarchy
        date_columns = [col for col in item.columns if col.data_type.upper() in {"DATE", "DATETIME", "TIMESTAMP"}]

        for date_col in date_columns:
            hierarchies.append({
                "name": f"{date_col.name} Hierarchy",
                "displayFolder": "Time Hierarchies",
                "levels": [
                    {"name": "Year", "column": date_col.name, "expression": f"YEAR('{item.name}'[{date_col.name}])"},
                    {"name": "Quarter", "column": date_col.name, "expression": f"QUARTER('{item.name}'[{date_col.name}])"},
                    {"name": "Month", "column": date_col.name, "expression": f"MONTH('{item.name}'[{date_col.name}])"},
                    {"name": "Day", "column": date_col.name, "expression": f"DAY('{item.name}'[{date_col.name}])"},
                ],
            })

        if date_columns:
            warnings.append(f"Created {len(date_columns)} date hierarchies; customize levels as needed")

        return hierarchies


def generate_all_semantic_models(
    inventory: BigQueryInventory,
    assessment: AssessmentReport,
) -> dict[str, SemanticModelDefinition]:
    """Generate all semantic models from inventory and assessment."""
    gen = SemanticModelGenerator(inventory, assessment)
    objects = {obj.source_id: obj for obj in inventory.objects()}
    decisions = {dec.source_id: dec for dec in assessment.decisions}

    models: dict[str, SemanticModelDefinition] = {}
    for source_id, decision in decisions.items():
        if decision.target not in {FabricTarget.SEMANTIC_MODEL, FabricTarget.WAREHOUSE, FabricTarget.LAKEHOUSE}:
            continue
        item = objects.get(source_id)
        if item is None or item.kind not in {ObjectKind.TABLE, ObjectKind.VIEW, ObjectKind.MATERIALIZED_VIEW}:
            continue
        model = gen.generate_semantic_model(item, decision)
        if model is not None:
            models[source_id] = model

    return models
