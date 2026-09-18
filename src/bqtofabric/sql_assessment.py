"""Structured GoogleSQL compatibility assessment backed by sqlglot AST parsing."""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot.errors import ParseError

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


_TRANSFORM_FEATURES = {
    "qualify": "QUALIFY requires translation or validation in the selected target dialect.",
    "unnest": "UNNEST requires explicit nested-data handling and row-count parity checks.",
    "pivot": "PIVOT syntax and null behavior require target-dialect validation.",
    "unpivot": "UNPIVOT syntax and null behavior require target-dialect validation.",
}
_REDESIGN_FEATURES = {
    "command": "The parser identified a dialect command that requires manual script redesign.",
    "transaction": "Transaction boundaries must be redesigned for the selected Fabric engine.",
}


def assess_sql(item: BigQueryObject, decision: MappingDecision) -> SqlAssessment | None:
    if not item.sql:
        return None
    target_language = "spark" if decision.target is FabricTarget.LAKEHOUSE else "tsql"
    try:
        statements = sqlglot.parse(item.sql, read="bigquery")
    except ParseError as error:
        return SqlAssessment(
            item.source_id,
            False,
            target_language,
            Compatibility.REDESIGN,
            (),
            (f"GoogleSQL parse failed: {error.errors[0].get('description', str(error))}",),
        )

    parsed_statements = tuple(statement for statement in statements if statement is not None)
    if not parsed_statements:
        return SqlAssessment(
            item.source_id,
            False,
            target_language,
            Compatibility.REDESIGN,
            (),
            ("GoogleSQL did not contain an executable statement.",),
        )
    features = tuple(sorted({node.key for statement in parsed_statements for node in statement.walk()}))
    notes = tuple(
        message
        for feature, message in {**_TRANSFORM_FEATURES, **_REDESIGN_FEATURES}.items()
        if feature in features
    )
    compatibility = Compatibility.DIRECT
    if any(feature in features for feature in _REDESIGN_FEATURES):
        compatibility = Compatibility.REDESIGN
    elif any(feature in features for feature in _TRANSFORM_FEATURES):
        compatibility = Compatibility.TRANSFORM

    converted_sql: str | None = None
    try:
        converted_sql = "\n\n".join(
            sqlglot.transpile(item.sql, read="bigquery", write=target_language)
        )
    except (ParseError, ValueError) as error:
        compatibility = Compatibility.REDESIGN
        notes += (f"Translation to {target_language} requires manual redesign: {error}",)
    return SqlAssessment(
        item.source_id,
        True,
        target_language,
        compatibility,
        features,
        notes,
        converted_sql,
    )
