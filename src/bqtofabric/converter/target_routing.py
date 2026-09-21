"""Target dialect routing: evidence-based selection of T-SQL, Spark SQL, or PySpark."""

from __future__ import annotations

from typing import Any

import sqlglot
import sqlglot.expressions
from sqlglot.errors import ParseError
from sqlglot.expressions import Select

from ..models import BigQueryObject, ObjectKind
from .models import RoutingDecision, TargetDialect


def classify_workload(sql_text: str, obj_kind: ObjectKind) -> str:
    """Classify workload type from SQL and object metadata."""
    if obj_kind in {ObjectKind.MATERIALIZED_VIEW, ObjectKind.VIEW}:
        return "analytical"
    if obj_kind is ObjectKind.SCHEDULED_QUERY:
        return "etl"
    if obj_kind is ObjectKind.STREAM:
        return "streaming"
    if obj_kind in {ObjectKind.SPARK_JOB, ObjectKind.DATAPROC_JOB}:
        return "distributed_compute"

    # Parse and inspect SQL patterns.
    try:
        statements = sqlglot.parse(sql_text, read="bigquery")
        if not statements:
            return "unknown"
        stmt = statements[0]
        if stmt is None:
            return "unknown"
        if isinstance(stmt, Select):
            # Look for window functions, aggregations, JOINs.
            has_window = any(
                node.key == "window"
                for node in stmt.walk()
            )
            has_complex_join = any(
                node.key == "join" and len(list(node.find_all(sqlglot.expressions.Join))) > 1
                for node in stmt.walk()
            )
            if has_window or has_complex_join:
                return "analytical"
            return "etl"
    except ParseError:
        pass

    return "unknown"


def estimate_complexity(sql_text: str) -> int:
    """Estimate SQL complexity on 1-100 scale."""
    try:
        statements = sqlglot.parse(sql_text, read="bigquery")
        if not statements:
            return 10
        stmt = statements[0]
        if stmt is None:
            return 10
        node_count = len(list(stmt.walk()))
        distinct_types = len({node.key for node in stmt.walk()})
        # Simple heuristic: 1 point per node, max 100.
        return min(node_count + distinct_types, 100)
    except ParseError:
        return 50


def detect_problematic_patterns(sql_text: str) -> tuple[str, ...]:
    """Detect patterns that may require special handling."""
    patterns: list[str] = []
    try:
        statements = sqlglot.parse(sql_text, read="bigquery")
        if not statements:
            return tuple(patterns)
        stmt = statements[0]
        if stmt is None:
            return tuple(patterns)
        node_keys = {node.key for node in stmt.walk()}

        # Spark SQL issues
        if "cte" in node_keys:
            patterns.append("cte")
        if "unnest" in node_keys:
            patterns.append("unnest")
        if "pivot" in node_keys:
            patterns.append("pivot")
        if "unpivot" in node_keys:
            patterns.append("unpivot")
        if "qualify" in node_keys:
            patterns.append("qualify")
        if "window" in node_keys:
            patterns.append("window_functions")
        if "struct" in node_keys or "struct_extract" in node_keys:
            patterns.append("struct_types")
        if "array" in node_keys or "arrayconcat" in node_keys:
            patterns.append("array_operations")
        if "cast" in node_keys:
            patterns.append("cast")
        if "case" in node_keys:
            patterns.append("case_expr")
        if "coalesce" in node_keys or "nullif" in node_keys:
            patterns.append("null_handling")
    except ParseError:
        pass

    return tuple(patterns)


def route_to_dialect(obj: BigQueryObject, preferences: dict[str, Any] | None = None) -> RoutingDecision:
    """
    Route SQL object to recommended target dialect.

    Decision tree:
    1. If object is a table, route to WAREHOUSE (DDL/DML in T-SQL).
    2. If scheduled query or streaming, route to PYSPARK (notebook/job context).
    3. If view/materialized_view with complex transformations, route to SPARK_SQL (Lakehouse SQL endpoint).
    4. Default: WAREHOUSE for DDL, PYSPARK for ETL/analysis.
    """
    preferences = preferences or {}
    workload = classify_workload(obj.sql or "", obj.kind)
    complexity = estimate_complexity(obj.sql or "")
    patterns = detect_problematic_patterns(obj.sql or "")

    # Routing logic
    target = TargetDialect.TSQL
    alternatives: list[TargetDialect] = []
    rationale = ""

    if obj.kind in {
        ObjectKind.TABLE,
        ObjectKind.EXTERNAL_TABLE,
        ObjectKind.MATERIALIZED_VIEW,
    }:
        # Tables and materialized views fit Warehouse (persistent storage).
        target = TargetDialect.TSQL
        alternatives = [TargetDialect.SPARK_SQL]
        rationale = f"Object kind {obj.kind} is best served by Warehouse for ACID guarantees and SQL indexing."

    elif obj.kind is ObjectKind.VIEW:
        if complexity > 70 or workload in {"analytical", "etl"}:
            target = TargetDialect.SPARK_SQL
            alternatives = [TargetDialect.PYSPARK, TargetDialect.TSQL]
            rationale = (
                "Complex views are better served by Spark SQL on Lakehouse, "
                "which supports unstructured data and dynamic schema."
            )
        else:
            target = TargetDialect.TSQL
            alternatives = [TargetDialect.SPARK_SQL]
            rationale = "Simple views map well to Warehouse views."

    elif obj.kind is ObjectKind.ROUTINE:
        if "javascript" in (obj.properties.get("language") or "").lower():
            target = TargetDialect.PYSPARK
            alternatives = []
            rationale = "JavaScript UDFs require PySpark for manual implementation."
        else:
            target = TargetDialect.SPARK_SQL
            alternatives = [TargetDialect.PYSPARK, TargetDialect.TSQL]
            rationale = "Routines map to Spark SQL UDFs or PySpark functions in notebooks."

    elif obj.kind is ObjectKind.SCHEDULED_QUERY:
        target = TargetDialect.PYSPARK
        alternatives = [TargetDialect.SPARK_SQL, TargetDialect.TSQL]
        rationale = "Scheduled queries fit Fabric Pipelines with PySpark notebooks for orchestration."

    elif obj.kind in {ObjectKind.SPARK_JOB, ObjectKind.DATAPROC_JOB}:
        target = TargetDialect.PYSPARK
        alternatives = [TargetDialect.SPARK_SQL]
        rationale = "Spark jobs map directly to PySpark in Fabric Notebooks or Spark Job Definitions."

    elif obj.kind in {ObjectKind.STREAM, ObjectKind.PUBSUB_TOPIC}:
        target = TargetDialect.PYSPARK
        alternatives = [TargetDialect.SPARK_SQL]
        rationale = "Streaming workloads fit Fabric Eventstream and PySpark consumer logic."

    # Override based on preferences
    if preferences.get("force_warehouse"):
        target = TargetDialect.TSQL
        rationale += " (Warehouse forced by preference)"
    elif preferences.get("force_lakehouse"):
        if target != TargetDialect.PYSPARK:
            target = TargetDialect.SPARK_SQL
        rationale += " (Lakehouse forced by preference)"

    return RoutingDecision(
        source_id=obj.source_id,
        source_text=obj.sql or "",
        recommended_target=target,
        alternative_targets=tuple(alternatives),
        rationale=rationale,
        workload_classification=workload,
        complexity_score=complexity,
        metadata={
            "detected_patterns": list(patterns),
            "object_kind": str(obj.kind),
        },
    )
