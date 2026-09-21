"""Core SQL conversion engine: GoogleSQL AST analysis and transpilation."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from typing import Any, cast

import sqlglot
from sqlglot.errors import ParseError
from sqlglot.expressions import (
    Expression,
    Join,
)

from ..models import BigQueryObject, ObjectKind
from .models import (
    CompatibilityLevel,
    ConversionWarning,
    ManualStep,
    SqlConversion,
    TargetDialect,
)
from .target_routing import route_to_dialect


@dataclass(frozen=True, slots=True)
class MultiStatementConversionResult:
    """Result of converting multiple SQL statements."""

    statements: list[SqlConversion]
    compatibility: CompatibilityLevel
    warnings: list[ConversionWarning]

    @property
    def compatibility_level(self) -> CompatibilityLevel:
        """Provide the legacy compatibility attribute for converter callers."""
        return self.compatibility

    def to_dict(self) -> dict[str, Any]:
        """Serialize the aggregate result for artifact output."""
        return {
            "statements": [
                {
                    "statement_index": statement.metadata["statement_index"],
                    "source_id": statement.source_id,
                    "source_text": statement.source_text,
                    "target_text": statement.target_text,
                    "compatibility": statement.compatibility_level,
                }
                for statement in self.statements
            ],
            "compatibility": self.compatibility,
            "warnings": [warning.message for warning in self.warnings],
        }


class SqlConverter:
    """Convert GoogleSQL to target dialects (T-SQL, Spark SQL, PySpark) with AST analysis."""

    def __init__(self) -> None:
        """Initialize converter with dialect mappings."""
        self.dialect_map = {
            TargetDialect.TSQL: "tsql",
            TargetDialect.SPARK_SQL: "spark",
            TargetDialect.PYSPARK: "python",  # Uses spark dialect with Python context.
        }

    def convert(
        self,
        obj: BigQueryObject,
        target_dialect: TargetDialect | None = None,
        preferences: dict[str, Any] | None = None,
    ) -> SqlConversion | MultiStatementConversionResult:
        """
        Convert a BigQuery SQL object to the target dialect.

        Args:
            obj: BigQuery object with SQL to convert.
            target_dialect: Target dialect. If None, use routing logic.
            preferences: Routing preferences (e.g., force_warehouse, force_lakehouse).

        Returns:
            SqlConversion with target text, compatibility, warnings, and manual steps.
        """
        if not obj.sql:
            return SqlConversion(
                source_id=obj.source_id,
                target_dialect=target_dialect or TargetDialect.SPARK_SQL,
                source_text="",
                target_text="",
                compatibility_level=CompatibilityLevel.DIRECT,
                rationale="No SQL text to convert.",
            )

        # Determine target dialect if not specified.
        if target_dialect is None:
            routing = route_to_dialect(obj, preferences)
            target_dialect = routing.recommended_target
            routing_rationale = routing.rationale
        else:
            routing_rationale = ""

        if len(self._split_statements(obj.sql)) > 1:
            return self.convert_multiple(obj.sql, target_dialect)

        # Parse source SQL.
        try:
            statements = sqlglot.parse(obj.sql, read="bigquery")
            if not statements or statements[0] is None:
                return SqlConversion(
                    source_id=obj.source_id,
                    target_dialect=target_dialect,
                    source_text=obj.sql,
                    target_text="",
                    compatibility_level=CompatibilityLevel.REDESIGN,
                    warnings=(
                        ConversionWarning(
                            "GoogleSQL did not parse; manual review required.",
                            category="syntax",
                            severity="error",
                        ),
                    ),
                    rationale="Parse failure.",
                )
        except ParseError as error:
            return SqlConversion(
                source_id=obj.source_id,
                target_dialect=target_dialect,
                source_text=obj.sql,
                target_text="",
                compatibility_level=CompatibilityLevel.REDESIGN,
                warnings=(
                    ConversionWarning(
                        f"GoogleSQL parse error: {error.errors[0].get('description', str(error))}",
                        category="syntax",
                        severity="error",
                    ),
                ),
                rationale="GoogleSQL syntax error.",
            )

        # Analyze patterns and compatibility.
        stmt = statements[0]
        patterns = self._detect_patterns(stmt)
        warnings, manual_steps, compat_level = self._analyze_compatibility(
            stmt, target_dialect, patterns
        )

        # Perform conversion.
        target_text = ""
        try:
            target_text = self._transpile_statement(stmt, target_dialect)
        except (ParseError, ValueError, NotImplementedError) as error:
            if compat_level not in {CompatibilityLevel.REDESIGN, CompatibilityLevel.UNSUPPORTED}:
                compat_level = CompatibilityLevel.REDESIGN
            warnings = warnings + (
                ConversionWarning(
                    f"Transpilation failed: {error!s}",
                    category="transpilation",
                    severity="error",
                ),
            )

        # Add target-specific transformations.
        if target_text and compat_level not in {CompatibilityLevel.UNSUPPORTED}:
            target_text = self._apply_target_specific_fixes(target_text, target_dialect, patterns)

        return SqlConversion(
            source_id=obj.source_id,
            target_dialect=target_dialect,
            source_text=obj.sql,
            target_text=target_text,
            compatibility_level=compat_level,
            warnings=warnings,
            manual_steps=manual_steps,
            rationale=routing_rationale or f"Converted for {target_dialect} target.",
            detected_patterns=patterns,
        )

    def convert_multiple(
        self,
        statements_text: str,
        target_dialect: TargetDialect = TargetDialect.TSQL,
    ) -> MultiStatementConversionResult:
        """Convert SQL statements independently without merging their transaction scope."""
        statements = self._split_statements(statements_text)
        conversions: list[SqlConversion] = []
        warnings: list[ConversionWarning] = []

        for index, statement_text in enumerate(statements, start=1):
            obj = BigQueryObject(
                source_id=f"statement_{index}",
                name=f"statement_{index}",
                kind=ObjectKind.SQL_SCRIPT,
                sql=statement_text,
            )
            conversion = cast(SqlConversion, self.convert(obj, target_dialect))
            conversions.append(
                replace(
                    conversion,
                    source_id=f"statement_{index}",
                    metadata={"statement_index": index},
                )
            )
            warnings.extend(conversion.warnings)

        has_dml = any("dml" in conversion.detected_patterns for conversion in conversions)
        has_failure = any(
            conversion.compatibility_level
            in {CompatibilityLevel.REDESIGN, CompatibilityLevel.UNSUPPORTED}
            for conversion in conversions
        )
        if has_dml:
            warnings.append(
                ConversionWarning(
                    "Multi-statement DML is unsupported in T-SQL/Spark; require separate "
                    "transactions or a stored procedure.",
                    category="semantics",
                    severity="error",
                )
            )
            conversions = [replace(conversion, target_text="") for conversion in conversions]

        compatibility = (
            CompatibilityLevel.REDESIGN
            if has_dml or has_failure
            else CompatibilityLevel.DIRECT
            if all(
                conversion.compatibility_level == CompatibilityLevel.DIRECT
                for conversion in conversions
            )
            else CompatibilityLevel.TRANSFORM
        )
        return MultiStatementConversionResult(conversions, compatibility, warnings)

    @staticmethod
    def _split_statements(statements_text: str) -> list[str]:
        """Split on semicolons outside quoted strings and SQL comments."""
        statements: list[str] = []
        start = 0
        index = 0
        quote: str | None = None
        in_line_comment = False
        in_block_comment = False

        while index < len(statements_text):
            character = statements_text[index]
            next_character = statements_text[index + 1] if index + 1 < len(statements_text) else ""

            if in_line_comment:
                if character == "\n":
                    in_line_comment = False
            elif in_block_comment:
                if character == "*" and next_character == "/":
                    in_block_comment = False
                    index += 1
            elif quote:
                if character == quote:
                    if next_character == quote:
                        index += 1
                    else:
                        quote = None
            elif character in {"'", '"', "`"}:
                quote = character
            elif character == "-" and next_character == "-":
                in_line_comment = True
                index += 1
            elif character == "/" and next_character == "*":
                in_block_comment = True
                index += 1
            elif character == ";":
                statement = statements_text[start:index].strip()
                if statement:
                    statements.append(statement)
                start = index + 1
            index += 1

        trailing_statement = statements_text[start:].strip()
        if trailing_statement:
            statements.append(trailing_statement)
        return statements

    def _detect_patterns(self, stmt: Expression) -> tuple[str, ...]:
        """Detect SQL patterns in parsed statement."""
        patterns: set[str] = set()
        node_keys = {node.key for node in stmt.walk()}

        # Structural patterns
        if "select" in node_keys:
            patterns.add("select")
        if "cte" in node_keys:
            patterns.add("cte")
        if "union" in node_keys:
            patterns.add("union")
        if "intersect" in node_keys:
            patterns.add("intersect")
        if "except" in node_keys:
            patterns.add("except")

        # Join patterns
        if "join" in node_keys:
            patterns.add("joins")
            join_count = len(list(stmt.find_all(Join)))
            if join_count > 2:
                patterns.add("multi_join")

        # Grouping and windowing
        if "group" in node_keys:
            patterns.add("group_by")
        if "window" in node_keys or "over" in node_keys:
            patterns.add("window_functions")
        if "qualify" in node_keys:
            patterns.add("qualify")

        # Array and struct operations
        if "unnest" in node_keys or "lateral" in node_keys:
            patterns.add("unnest")
        if "struct" in node_keys or "struct_extract" in node_keys:
            patterns.add("struct_types")
        if "array" in node_keys or "arrayconcat" in node_keys:
            patterns.add("array_operations")

        # Functions and expressions
        if "cast" in node_keys:
            patterns.add("cast")
        if "case" in node_keys:
            patterns.add("case_expr")
        if "coalesce" in node_keys or "nullif" in node_keys:
            patterns.add("null_handling")
        if "distinct" in node_keys:
            patterns.add("distinct")
        if "limit" in node_keys:
            patterns.add("limit")
        if "order" in node_keys:
            patterns.add("order_by")

        # DML patterns
        if "insert" in node_keys or "update" in node_keys or "delete" in node_keys:
            patterns.add("dml")
        if "create" in node_keys or "alter" in node_keys:
            patterns.add("ddl")

        # Advanced patterns
        if "window" in node_keys and "partition" in node_keys:
            patterns.add("window_with_partition")
        if "recursive" in node_keys:
            patterns.add("recursive_cte")

        return tuple(sorted(patterns))

    def _analyze_compatibility(
        self,
        stmt: Expression,
        target: TargetDialect,
        patterns: tuple[str, ...],
    ) -> tuple[tuple[ConversionWarning, ...], tuple[ManualStep, ...], CompatibilityLevel]:
        """Analyze compatibility and generate warnings/manual steps."""
        warnings: list[ConversionWarning] = []
        manual_steps: list[ManualStep] = []
        compat_level = CompatibilityLevel.DIRECT

        # Check for unsupported constructs
        node_keys = {node.key for node in stmt.walk()}

        # Script blocks and control flow
        if "command" in node_keys or "execute" in node_keys:
            warnings.append(
                ConversionWarning(
                    "Script command or procedural block detected; manual redesign required.",
                    category="syntax",
                    severity="error",
                )
            )
            manual_steps.append(
                ManualStep(
                    "Manually redesign procedural logic as separate imperative operations.",
                    "Script blocks and BEGIN/END constructs are not supported in SQL DDL.",
                    "high",
                    ("command", "execute"),
                )
            )
            compat_level = CompatibilityLevel.REDESIGN

        # DML in procedures/routines
        if "dml" in patterns and "declare" in node_keys:
            warnings.append(
                ConversionWarning(
                    "DML (INSERT/UPDATE/DELETE) detected in procedure body; review for parameterization.",
                    category="semantics",
                    severity="warning",
                )
            )
            manual_steps.append(
                ManualStep(
                    "Review all DML statements for parameterization and transaction scope.",
                    "DML in stored procedures may require different transaction semantics.",
                    "medium",
                    ("dml", "declare"),
                )
            )
            if compat_level == CompatibilityLevel.DIRECT:
                compat_level = CompatibilityLevel.TRANSFORM

        # QUALIFY clause (Spark SQL limitation)
        if "qualify" in patterns and target == TargetDialect.SPARK_SQL:
            warnings.append(
                ConversionWarning(
                    "QUALIFY clause detected; Spark SQL requires manual translation to WHERE filter on window result.",
                    category="syntax",
                    severity="warning",
                )
            )
            manual_steps.append(
                ManualStep(
                    "Rewrite QUALIFY as a WHERE clause filtering the windowed result, or wrap in a derived table.",
                    "Spark SQL does not support QUALIFY directly.",
                    "high",
                    ("qualify",),
                )
            )
            if compat_level == CompatibilityLevel.DIRECT:
                compat_level = CompatibilityLevel.TRANSFORM

        # UNNEST/array operations
        if "unnest" in patterns:
            if target == TargetDialect.TSQL:
                warnings.append(
                    ConversionWarning(
                        "UNNEST requires translation to CROSS APPLY in T-SQL.",
                        category="syntax",
                        severity="warning",
                    )
                )
                manual_steps.append(
                    ManualStep(
                        "Replace UNNEST with CROSS APPLY or convert nested arrays to relational form.",
                        "T-SQL does not have UNNEST; use CROSS APPLY for flattening.",
                        "high",
                        ("unnest",),
                    )
                )
                if compat_level == CompatibilityLevel.DIRECT:
                    compat_level = CompatibilityLevel.TRANSFORM
            elif target == TargetDialect.SPARK_SQL:
                warnings.append(
                    ConversionWarning(
                        "UNNEST in Spark SQL should use explode() for verification.",
                        category="semantics",
                        severity="info",
                    )
                )
                if compat_level == CompatibilityLevel.DIRECT:
                    compat_level = CompatibilityLevel.TRANSFORM

        # Struct types
        if "struct_types" in patterns and target == TargetDialect.TSQL:
            warnings.append(
                ConversionWarning(
                    "Struct types require mapping to T-SQL JSON or custom types.",
                    category="semantics",
                    severity="warning",
                )
            )
            manual_steps.append(
                ManualStep(
                    "Map BigQuery STRUCT to T-SQL JSON_VALUE/JSON_QUERY or define custom complex types.",
                    "T-SQL represents structs as JSON or CLR types.",
                    "high",
                    ("struct_types",),
                )
            )
            if compat_level == CompatibilityLevel.DIRECT:
                compat_level = CompatibilityLevel.TRANSFORM

        # Cross-region and federated queries
        if "federated" in node_keys or "external_data_source" in node_keys:
            warnings.append(
                ConversionWarning(
                    "Cross-region or federated query detected; review security and latency implications.",
                    category="security",
                    severity="warning",
                )
            )
            manual_steps.append(
                ManualStep(
                    "Review cross-region query security implications and validate data residency requirements.",
                    "Federated queries may violate data governance policies.",
                    "critical",
                    ("federated",),
                )
            )

        # Window functions
        if "window_functions" in patterns and target == TargetDialect.PYSPARK:
            warnings.append(
                ConversionWarning(
                    "Window functions require PySpark DataFrame or Spark SQL context.",
                    category="semantics",
                    severity="info",
                )
            )
            if compat_level == CompatibilityLevel.DIRECT:
                compat_level = CompatibilityLevel.TRANSFORM

        return (tuple(warnings), tuple(manual_steps), compat_level)

    def _transpile_statement(self, stmt: Expression, target: TargetDialect) -> str:
        """Transpile parsed statement to target dialect."""
        target_dialect_name = self.dialect_map[target]
        transpiled = stmt.sql(dialect=target_dialect_name)
        return transpiled or ""

    def _apply_target_specific_fixes(
        self, target_text: str, target: TargetDialect, patterns: tuple[str, ...]
    ) -> str:
        """Apply target-specific post-processing fixes."""
        # Re-parse the transpiled output for additional transformations
        try:
            sqlglot.parse_one(target_text, read=self.dialect_map[target])
        except ParseError:
            return target_text

        if target == TargetDialect.TSQL:
            # T-SQL-specific fixes
            if "unnest" in patterns:
                # Add comment noting manual CROSS APPLY required
                target_text = f"-- REVIEW: UNNEST requires CROSS APPLY or JSON handling\n{target_text}"

        elif target == TargetDialect.SPARK_SQL:
            # Spark SQL-specific fixes
            if "qualify" in patterns:
                # Add comment noting manual rewrite needed
                target_text = f"-- REVIEW: QUALIFY requires manual translation to WHERE on window result\n{target_text}"
            if "struct_types" in patterns:
                target_text = f"-- REVIEW: Verify STRUCT field references are compatible\n{target_text}"

        elif target == TargetDialect.PYSPARK and "window_functions" in patterns:
            # PySpark-specific fixes
            target_text = f"# REVIEW: Window functions require .over() with WindowSpec\n{target_text}"

        return target_text
