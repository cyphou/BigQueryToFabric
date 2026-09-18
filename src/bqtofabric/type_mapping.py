"""BigQuery to Fabric type compatibility rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Compatibility(StrEnum):
    DIRECT = "direct"
    TRANSFORM = "transform"
    REDESIGN = "redesign"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class TypeMapping:
    source_type: str
    warehouse_type: str | None
    lakehouse_type: str | None
    compatibility: Compatibility
    note: str = ""


_TYPE_MAPPINGS = {
    "BOOL": TypeMapping("BOOL", "bit", "boolean", Compatibility.DIRECT),
    "INT64": TypeMapping("INT64", "bigint", "long", Compatibility.DIRECT),
    "FLOAT64": TypeMapping("FLOAT64", "float", "double", Compatibility.DIRECT),
    "NUMERIC": TypeMapping("NUMERIC", "decimal(38,9)", "decimal(38,9)", Compatibility.DIRECT),
    "BIGNUMERIC": TypeMapping(
        "BIGNUMERIC",
        "decimal(38,18)",
        "decimal(38,18)",
        Compatibility.TRANSFORM,
        "BigQuery precision can exceed Fabric decimal precision; profile values before casting.",
    ),
    "STRING": TypeMapping("STRING", "varchar(max)", "string", Compatibility.DIRECT),
    "BYTES": TypeMapping("BYTES", "varbinary(max)", "binary", Compatibility.DIRECT),
    "DATE": TypeMapping("DATE", "date", "date", Compatibility.DIRECT),
    "DATETIME": TypeMapping("DATETIME", "datetime2", "timestamp", Compatibility.DIRECT),
    "TIME": TypeMapping("TIME", "time", "string", Compatibility.TRANSFORM),
    "TIMESTAMP": TypeMapping("TIMESTAMP", "datetime2", "timestamp", Compatibility.TRANSFORM,
        "Normalize BigQuery UTC semantics explicitly."),
    "JSON": TypeMapping("JSON", "varchar(max)", "string", Compatibility.TRANSFORM,
        "Preserve raw JSON in Bronze and project typed fields in Silver."),
    "GEOGRAPHY": TypeMapping("GEOGRAPHY", None, "string", Compatibility.REDESIGN,
        "Store WKT/GeoJSON and validate required geospatial operations."),
    "ARRAY": TypeMapping("ARRAY", None, "array", Compatibility.REDESIGN,
        "Keep nested data in Lakehouse or normalize into child tables."),
    "STRUCT": TypeMapping("STRUCT", None, "struct", Compatibility.REDESIGN,
        "Keep nested data in Lakehouse or flatten with explicit lineage."),
}


def map_type(source_type: str) -> TypeMapping:
    normalized = source_type.upper().split("<", 1)[0]
    return _TYPE_MAPPINGS.get(
        normalized,
        TypeMapping(source_type, None, None, Compatibility.UNSUPPORTED, "Unknown BigQuery type."),
    )
