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
    "STRING": TypeMapping("STRING", "varchar(max)", "string", Compatibility.TRANSFORM,
        "Profile actual string lengths before accepting varchar(max) in Warehouse."),
    "BYTES": TypeMapping("BYTES", "varbinary(max)", "binary", Compatibility.DIRECT),
    "DATE": TypeMapping("DATE", "date", "date", Compatibility.DIRECT),
    # BigQuery DATETIME is civil time with no zone; Spark timestamp is instant-based and
    # session-timezone dependent, so an unconsidered mapping silently shifts values.
    "DATETIME": TypeMapping("DATETIME", "datetime2", "timestamp", Compatibility.TRANSFORM,
        "DATETIME has no time zone; Spark timestamp applies session-timezone semantics. "
        "Choose timestamp_ntz or an explicit civil representation deliberately."),
    "TIME": TypeMapping("TIME", "time", "string", Compatibility.TRANSFORM),
    "TIMESTAMP": TypeMapping("TIMESTAMP", "datetime2", "timestamp", Compatibility.TRANSFORM,
        "Normalize BigQuery UTC semantics explicitly."),
    "INTERVAL": TypeMapping("INTERVAL", None, "string", Compatibility.REDESIGN,
        "INTERVAL has no portable target equivalent; model the component parts explicitly."),
    "RANGE": TypeMapping("RANGE", None, "struct", Compatibility.REDESIGN,
        "RANGE must be modelled as explicit start and end columns."),
    "JSON": TypeMapping("JSON", "varchar(max)", "string", Compatibility.TRANSFORM,
        "Preserve raw JSON in Bronze and project typed fields in Silver."),
    "GEOGRAPHY": TypeMapping("GEOGRAPHY", None, "string", Compatibility.REDESIGN,
        "Store WKT/GeoJSON and validate required geospatial operations."),
    "ARRAY": TypeMapping("ARRAY", None, "array", Compatibility.REDESIGN,
        "Keep nested data in Lakehouse or normalize into child tables."),
    "STRUCT": TypeMapping("STRUCT", None, "struct", Compatibility.REDESIGN,
        "Keep nested data in Lakehouse or flatten with explicit lineage."),
}


# The REST API and hand-authored inventories still use legacy type names.
_LEGACY_TYPE_NAMES = {
    "INTEGER": "INT64",
    "FLOAT": "FLOAT64",
    "BOOLEAN": "BOOL",
    "RECORD": "STRUCT",
    "DECIMAL": "NUMERIC",
    "BIGDECIMAL": "BIGNUMERIC",
}


def map_type(source_type: str) -> TypeMapping:
    """Map a BigQuery type name, tolerating legacy and parameterized spellings."""
    normalized = source_type.upper().strip().split("<", 1)[0].split("(", 1)[0].strip()
    normalized = _LEGACY_TYPE_NAMES.get(normalized, normalized)
    mapping = _TYPE_MAPPINGS.get(normalized)
    if mapping is None:
        return TypeMapping(
            source_type,
            None,
            None,
            Compatibility.UNSUPPORTED,
            "Unrecognized BigQuery type; confirm whether this is a discovery gap or a "
            "genuinely unsupported type.",
        )
    if normalized != source_type.upper().strip():
        # Preserve the caller's spelling so findings cite what the inventory recorded.
        return TypeMapping(
            source_type,
            mapping.warehouse_type,
            mapping.lakehouse_type,
            mapping.compatibility,
            mapping.note,
        )
    return mapping
