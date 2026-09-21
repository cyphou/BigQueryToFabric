"""Generate production-ready Eventstream topologies and Eventhouse schemas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..assessment import AssessmentReport
from ..mapping import FabricTarget, MappingDecision
from ..models import BigQueryInventory, BigQueryObject, ObjectKind


@dataclass(frozen=True, slots=True)
class EventstreamTopology:
    """Complete Eventstream definition."""

    name: str
    description: str
    source_id: str
    source_kind: ObjectKind
    topology: dict[str, Any]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EventhouseSchema:
    """Complete Eventhouse KQL schema."""

    name: str
    description: str
    source_id: str
    source_kind: ObjectKind
    kql_script: str
    warnings: tuple[str, ...] = ()


class EventstreamGenerator:
    """Generate Fabric Eventstream topologies."""

    def __init__(self, inventory: BigQueryInventory, assessment: AssessmentReport) -> None:
        """Initialize with inventory and assessment data."""
        self.inventory = inventory
        self.assessment = assessment
        self.objects = {obj.source_id: obj for obj in inventory.objects()}

    def generate_eventstream(self, item: BigQueryObject, decision: MappingDecision) -> EventstreamTopology | None:
        """Generate an Eventstream topology for a streaming object."""
        if item.kind not in {
            ObjectKind.STREAM,
            ObjectKind.PUBSUB_TOPIC,
            ObjectKind.SPARK_JOB,
        }:
            return None

        warnings: list[str] = []
        topology: dict[str, Any] = {
            "mode": "dry-run",
            "version": "1.0",
            "sourceId": item.source_id,
            "sourceKind": item.kind.value,
            "metadata": {
                "title": item.name,
                "description": decision.rationale,
                "createdFrom": item.discovered_from,
            },
            "nodes": {},
            "edges": [],
        }

        # Build source node
        source_node = self._build_source_node(item, decision, warnings)
        topology["nodes"]["source"] = source_node

        # Build transformation nodes if applicable
        transform_node = self._build_transform_node(item, warnings)
        if transform_node:
            topology["nodes"]["transform"] = transform_node
            topology["edges"].append({"from": "source", "to": "transform"})

        # Build destination node
        dest_node = self._build_destination_node(item, decision, warnings)
        topology["nodes"]["destination"] = dest_node
        topology["edges"].append({"from": "transform" if transform_node else "source", "to": "destination"})

        # Add properties
        topology["properties"] = {
            "retention": item.properties.get("retention", "7 days"),
            "format": item.properties.get("format", "JSON"),
            "compression": item.properties.get("compression", "GZIP"),
        }

        return EventstreamTopology(
            name=f"eventstream_{item.name}",
            description=f"Generated from {item.kind.value} {item.source_id}",
            source_id=item.source_id,
            source_kind=item.kind,
            topology=topology,
            warnings=tuple(warnings),
        )

    def _build_source_node(
        self, item: BigQueryObject, decision: MappingDecision, warnings: list[str]
    ) -> dict[str, Any]:
        """Build source node based on item properties."""
        source_type = "EventHub"  # Default to Event Hubs

        if item.kind is ObjectKind.PUBSUB_TOPIC:
            source_type = "Kafka"  # Map Pub/Sub to Kafka
            warnings.append("Pub/Sub mapped to Kafka; configure Confluent connector or native Event Hubs")

        if item.kind is ObjectKind.STREAM:
            source_type = item.properties.get("source_type", "EventHub")

        return {
            "type": "source",
            "sourceType": source_type,
            "connectionId": f"conn_{item.source_id}",
            "topicOrQueue": item.name,
            "consumerGroup": "$Default",
            "dataFormat": item.properties.get("format", "JSON"),
            "properties": {
                "startFrom": "Latest",
                "eventSerializationType": "Json",
            },
            "warnings": [
                f"TODO: MANUAL REVIEW - Configure {source_type} connection details",
                "TODO: MANUAL REVIEW - Validate consumer group and partition assignment",
            ],
        }

    def _build_transform_node(self, item: BigQueryObject, warnings: list[str]) -> dict[str, Any] | None:
        """Build transformation node if streaming job has transformations."""
        if not item.properties.get("has_transformations"):
            return None

        warnings.append("TODO: MANUAL REVIEW - Add transformation operators (filter, aggregate, etc.)")

        return {
            "type": "operator",
            "operatorType": "Filter",
            "condition": "# TODO: Define filter condition",
            "input": "source",
            "properties": {
                "description": "Filter events based on criteria",
            },
        }

    def _build_destination_node(
        self, item: BigQueryObject, decision: MappingDecision, warnings: list[str]
    ) -> dict[str, Any]:
        """Build destination node (Eventhouse or Lakehouse)."""
        return {
            "type": "destination",
            "destinationType": "Eventhouse",
            "target": {
                "workspaceId": "${FABRIC_WORKSPACE_ID}",
                "eventHouseId": "${EVENTHOUSE_ID}",
                "tableName": item.name,
            },
            "mappings": {
                "ingestionMapping": f"ingestion_mapping_{item.name}",
                "format": item.properties.get("format", "JSON"),
            },
            "warnings": [
                "TODO: MANUAL REVIEW - Create Eventhouse and configure ingestion mapping",
                "TODO: MANUAL REVIEW - Define schema and validation rules",
            ],
        }


class EventhouseGenerator:
    """Generate Fabric Eventhouse schemas."""

    def __init__(self, inventory: BigQueryInventory, assessment: AssessmentReport) -> None:
        """Initialize with inventory and assessment data."""
        self.inventory = inventory
        self.assessment = assessment
        self.objects = {obj.source_id: obj for obj in inventory.objects()}

    def generate_eventhouse_schema(self, item: BigQueryObject, decision: MappingDecision) -> EventhouseSchema | None:
        """Generate a Eventhouse KQL schema for a streaming object."""
        if item.kind not in {ObjectKind.STREAM, ObjectKind.PUBSUB_TOPIC}:
            return None

        warnings: list[str] = []
        lines: list[str] = []

        # Header
        lines.extend([
            "// Generated Eventhouse Schema\n",
            f"// Source: {item.source_id}\n",
            f"// Kind: {item.kind.value}\n",
            f"// Compatibility: {decision.compatibility.value}\n",
            "\n",
        ])

        # Create table
        table_name = item.name
        lines.extend([
            f".create-or-alter table {table_name} (\n",
        ])

        # Build column definitions
        if item.columns:
            col_defs: list[str] = []
            for col in item.columns:
                kql_type = self._map_to_kql_type(col.data_type, warnings)
                col_defs.append(f"  {col.name}: {kql_type}")

            lines.append(",\n".join(col_defs))

        # Add ingestion timestamp
        lines.extend([
            ",\n",
            "  _ingestion_time: datetime\n",
            ")\n",
            "\n",
        ])

        # Retention policy
        lines.extend([
            "// Set retention policy\n",
            f".alter-merge table {table_name} policy retention softdelete = 90d\n",
            "\n",
        ])

        # Ingestion mapping
        lines.extend(self._build_ingestion_mapping(item, warnings))

        # Create materialized view for hourly aggregation
        lines.extend(self._build_materialized_view(item, warnings))

        kql_script = "".join(lines)
        return EventhouseSchema(
            name=f"eventhouse_{item.name}",
            description=f"Generated from {item.kind.value} {item.source_id}",
            source_id=item.source_id,
            source_kind=item.kind,
            kql_script=kql_script,
            warnings=tuple(warnings),
        )

    def _map_to_kql_type(self, bq_type: str, warnings: list[str]) -> str:
        """Map BigQuery type to KQL type."""
        type_map = {
            "BOOL": "bool",
            "INT64": "long",
            "FLOAT64": "real",
            "STRING": "string",
            "BYTES": "dynamic",
            "DATE": "datetime",
            "DATETIME": "datetime",
            "TIMESTAMP": "datetime",
            "JSON": "dynamic",
            "ARRAY": "dynamic",
            "STRUCT": "dynamic",
        }

        normalized = bq_type.upper().split("<", 1)[0]
        kql_type = type_map.get(normalized, "dynamic")

        if normalized not in type_map:
            warnings.append(f"Column type {bq_type} mapped to 'dynamic'; may require casting")

        return kql_type

    def _build_ingestion_mapping(self, item: BigQueryObject, warnings: list[str]) -> list[str]:
        """Build ingestion mapping definition."""
        lines = [
            "// Define ingestion mapping\n",
            f".create table {item.name} ingestion json mapping 'ingestion_mapping_{item.name}'\n",
        ]

        if item.columns:
            lines.append("(\n")
            mappings: list[str] = []
            for col in item.columns:
                mappings.append(f"  '{col.name}' = '$.{col.name}'")
            lines.append(",\n".join(mappings))
            lines.append("\n)\n")
        else:
            lines.append("// TODO: MANUAL REVIEW - Define column mappings\n")
            warnings.append("Ingestion mapping: no columns defined; manual definition required")

        lines.append("\n")
        return lines

    def _build_materialized_view(self, item: BigQueryObject, warnings: list[str]) -> list[str]:
        """Build materialized view for common aggregations."""
        lines = [
            "// Create materialized view for hourly aggregation\n",
            f".create-or-alter materialized-view with (backfill=true, folder='Generated') {item.name}_hourly_stats\n",
            f"on table {item.name}\n",
            "{\n",
            f"  {item.name}\n",
            "  | where todatetime(_ingestion_time) >= ago(7d)\n",
            "  | summarize count() by bin(_ingestion_time, 1h)\n",
            "}\n",
            "\n",
        ]

        warnings.append("Materialized view created for hourly aggregation; customize aggregation logic")

        return lines


def generate_all_eventstreams(
    inventory: BigQueryInventory,
    assessment: AssessmentReport,
) -> dict[str, EventstreamTopology]:
    """Generate all eventstream topologies from inventory and assessment."""
    gen = EventstreamGenerator(inventory, assessment)
    objects = {obj.source_id: obj for obj in inventory.objects()}
    decisions = {dec.source_id: dec for dec in assessment.decisions}

    eventstreams: dict[str, EventstreamTopology] = {}
    for source_id, decision in decisions.items():
        if decision.target not in {FabricTarget.EVENTSTREAM, FabricTarget.EVENTHOUSE}:
            continue
        item = objects.get(source_id)
        if item is None:
            continue
        eventstream = gen.generate_eventstream(item, decision)
        if eventstream is not None:
            eventstreams[source_id] = eventstream

    return eventstreams


def generate_all_eventhouse_schemas(
    inventory: BigQueryInventory,
    assessment: AssessmentReport,
) -> dict[str, EventhouseSchema]:
    """Generate all eventhouse schemas from inventory and assessment."""
    gen = EventhouseGenerator(inventory, assessment)
    objects = {obj.source_id: obj for obj in inventory.objects()}
    decisions = {dec.source_id: dec for dec in assessment.decisions}

    schemas: dict[str, EventhouseSchema] = {}
    for source_id, decision in decisions.items():
        if decision.target not in {FabricTarget.EVENTHOUSE, FabricTarget.EVENTSTREAM}:
            continue
        item = objects.get(source_id)
        if item is None:
            continue
        schema = gen.generate_eventhouse_schema(item, decision)
        if schema is not None:
            schemas[source_id] = schema

    return schemas
