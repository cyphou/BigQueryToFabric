"""Structured GoogleSQL compatibility assessment backed by the SQL converter."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .converter.models import CompatibilityLevel, TargetDialect
from .converter.sql_converter import SqlConverter
from .mapping import FabricTarget, MappingDecision
from .models import BigQueryObject
from .type_mapping import Compatibility


@dataclass(frozen=True, slots=True)
class SqlAssessment:
    source_id: str
    parsed: bool
    target_language: str
    compatibility: Compatibility
    features: tuple[str, ...]
    notes: tuple[str, ...]
    converted_sql: str | None = None


_COMPATIBILITY_ORDER = (
    Compatibility.DIRECT,
    Compatibility.TRANSFORM,
    Compatibility.REDESIGN,
    Compatibility.UNSUPPORTED,
)

# GoogleSQL constructs sqlglot may transpile without raising, but whose target
# semantics differ. Absence of an error is not evidence of a faithful translation.
_SEMANTIC_RISKS: tuple[tuple[str, str, Compatibility], ...] = (
    (
        r"_TABLE_SUFFIX|`[^`]*\*`",
        (
            "Wildcard tables and _TABLE_SUFFIX have no direct target equivalent; "
            "enumerate the partitions explicitly."
        ),
        Compatibility.REDESIGN,
    ),
    (
        r"(?i)\bSELECT\s+\*\s+(EXCEPT|REPLACE)\b",
        "SELECT * EXCEPT/REPLACE must be expanded into an explicit column list.",
        Compatibility.REDESIGN,
    ),
    (
        r"(?i)\bEXTERNAL_QUERY\s*\(",
        "EXTERNAL_QUERY federation must be redesigned as a Fabric connection.",
        Compatibility.REDESIGN,
    ),
    (
        r"(?i)\bNET\.[A-Z_]+\s*\(",
        "NET.* functions have no target equivalent and must be reimplemented.",
        Compatibility.REDESIGN,
    ),
    (
        r"(?i)\bST_[A-Z_]+\s*\(",
        "GEOGRAPHY functions have no direct target equivalent.",
        Compatibility.REDESIGN,
    ),
    (
        r"(?i)\bSAFE\.[A-Z_]+\s*\(",
        "SAFE. prefixed calls return NULL on error; the target raises instead.",
        Compatibility.TRANSFORM,
    ),
    (
        r"(?i)\bSAFE_CAST\s*\(",
        "SAFE_CAST returns NULL on failure; verify the target cast behaves the same.",
        Compatibility.TRANSFORM,
    ),
    (
        r"(?i)\bUNNEST\s*\(",
        "UNNEST changes row multiplicity; verify row counts against the source.",
        Compatibility.TRANSFORM,
    ),
    (
        r"(?i)\bNOT\s+IN\s*\(",
        "NOT IN with NULL values yields no rows; confirm the target NULL semantics.",
        Compatibility.TRANSFORM,
    ),
    (
        r"(?i)\bMERGE\s+INTO\b",
        "MERGE semantics and matched-row handling differ; validate before use.",
        Compatibility.TRANSFORM,
    ),
    (
        r"(?i)\bTABLESAMPLE\b",
        "TABLESAMPLE sampling semantics differ between engines.",
        Compatibility.TRANSFORM,
    ),
    (
        r"(?i)\bINTERVAL\b",
        "INTERVAL arithmetic differs between GoogleSQL and the target dialect.",
        Compatibility.TRANSFORM,
    ),
)


def _worst(*levels: Compatibility) -> Compatibility:
    """Return the least favourable compatibility level supplied."""
    return max(levels, key=_COMPATIBILITY_ORDER.index)


def assess_sql(item: BigQueryObject, decision: MappingDecision) -> SqlAssessment | None:
    """Assess GoogleSQL against the mapped Fabric target.

    Compatibility never defaults to ``direct``: it is the least favourable of the
    converter verdict, the detected semantic risks, and the mapping decision.
    """
    if not item.sql:
        return None

    is_lakehouse = decision.target is FabricTarget.LAKEHOUSE
    target_language = "spark" if is_lakehouse else "tsql"
    dialect = TargetDialect.SPARK_SQL if is_lakehouse else TargetDialect.TSQL

    language = str(item.properties.get("language", "") or "").strip().upper()
    if language and language != "SQL":
        return SqlAssessment(
            source_id=item.source_id,
            parsed=False,
            target_language=target_language,
            compatibility=Compatibility.REDESIGN,
            features=(f"language:{language.lower()}",),
            notes=(
                (
                    f"{language} routine bodies have no SQL translation path; "
                    "reimplement the logic in the target engine."
                ),
            ),
        )

    result = SqlConverter().convert(item, dialect)
    compatibility = Compatibility(str(result.compatibility_level))
    parsed = bool(result.target_text) or (
        result.compatibility_level is not CompatibilityLevel.REDESIGN
    )

    notes = [warning.message for warning in result.warnings]
    notes.extend(step.step for step in getattr(result, "manual_steps", ()))

    for pattern, message, level in _SEMANTIC_RISKS:
        if re.search(pattern, item.sql):
            compatibility = _worst(compatibility, level)
            notes.append(message)

    # The mapping decision already reflects non-SQL evidence; never report better
    # SQL compatibility than the component as a whole.
    compatibility = _worst(compatibility, decision.compatibility)

    return SqlAssessment(
        source_id=item.source_id,
        parsed=parsed,
        target_language=target_language,
        compatibility=compatibility,
        features=tuple(result.detected_patterns),
        notes=tuple(dict.fromkeys(notes)),
        converted_sql=result.target_text or None,
    )
