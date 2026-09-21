"""Data models for SQL conversion, compatibility tracking, and target routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class CompatibilityLevel(StrEnum):
    """Defines the extent of manual intervention required for conversion."""

    DIRECT = "direct"  # No changes needed; output is production-ready.
    TRANSFORM = "transform"  # One-to-one rewrite; output is production-ready after testing.
    REDESIGN = "redesign"  # Requires manual refactoring; AST may be incomplete.
    UNSUPPORTED = "unsupported"  # Manual implementation required; no AST translation attempted.


class TargetDialect(StrEnum):
    """Target SQL dialect for conversion."""

    TSQL = "tsql"  # Azure SQL Warehouse T-SQL.
    SPARK_SQL = "spark_sql"  # Spark SQL for Lakehouse SQL Endpoints.
    PYSPARK = "pyspark"  # PySpark DataFrame API and SQL in notebooks.


@dataclass(frozen=True, slots=True)
class ConversionWarning:
    """Represents a single warning or issue found during conversion."""

    message: str
    location: str | None = None  # Line:Column or AST node path.
    category: str = "general"  # e.g., "syntax", "semantics", "performance", "security".
    severity: str = "info"  # "info", "warning", "error".


@dataclass(frozen=True, slots=True)
class ManualStep:
    """Represents an actionable manual step required after conversion."""

    step: str  # Actionable instruction.
    rationale: str  # Why this step is required.
    priority: str = "medium"  # "low", "medium", "high", "critical".
    affected_patterns: tuple[str, ...] = ()  # Which SQL patterns trigger this step.


@dataclass(frozen=True, slots=True)
class SqlConversion:
    """Complete record of a SQL conversion from source to target dialect."""

    source_id: str  # Unique identifier of the BigQuery object.
    target_dialect: TargetDialect
    source_text: str
    target_text: str
    compatibility_level: CompatibilityLevel
    source_dialect: str = "bigquery"
    warnings: tuple[ConversionWarning, ...] = ()
    manual_steps: tuple[ManualStep, ...] = ()
    rationale: str = ""  # Why this target was chosen.
    detected_patterns: tuple[str, ...] = ()  # SQL constructs identified in source.
    edge_cases: tuple[str, ...] = ()  # Known edge cases in conversion.
    performance_notes: tuple[str, ...] = ()  # Performance implications in target.
    metadata: dict[str, Any] = field(default_factory=dict)  # Custom metadata.

    def is_production_ready(self) -> bool:
        """Check if conversion output can be deployed without manual review."""
        return self.compatibility_level in {CompatibilityLevel.DIRECT, CompatibilityLevel.TRANSFORM}


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Decision logic for selecting target dialect and rationale."""

    source_id: str
    source_text: str
    recommended_target: TargetDialect
    alternative_targets: tuple[TargetDialect, ...] = ()
    rationale: str = ""
    workload_classification: str = ""  # e.g., "analytical", "etl", "streaming", "ml".
    complexity_score: int = 0  # 1-100 scale.
    metadata: dict[str, Any] = field(default_factory=dict)


class SparkCodeLanguage(StrEnum):
    """Supported Spark code languages."""

    PYSPARK = "pyspark"  # Python Spark code.
    SCALA = "scala"  # Scala Spark code.


class SparkOperation(StrEnum):
    """Classify Spark operations by category."""

    INGESTION = "ingestion"  # Data source read.
    TRANSFORMATION = "transformation"  # DataFrame operations.
    AGGREGATION = "aggregation"  # GroupBy, window functions.
    JOIN = "join"  # Multi-table operations.
    SINK = "sink"  # Data output/write.
    STREAMING = "streaming"  # Spark Structured Streaming.
    CONFIGURATION = "configuration"  # Spark config/runtime.
    ML_TRAINING = "ml_training"  # Machine learning.
    UDF = "udf"  # User-defined functions.
    RDD = "rdd"  # RDD operations (legacy).


@dataclass(frozen=True, slots=True)
class SparkPattern:
    """Represents a detected Spark code pattern."""

    name: str  # e.g., "read_format", "select", "join", "udf".
    operation: SparkOperation
    line_range: tuple[int, int] | None = None  # (start_line, end_line) if available.
    code_snippet: str = ""  # Extracted pattern code.
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SparkConversion:
    """Complete record of Spark code conversion and analysis."""

    source_id: str  # Unique identifier (e.g., Dataproc job ID).
    language: SparkCodeLanguage
    source_text: str
    target_language: str = "python"  # Target language for conversion (e.g., "python", "pyspark_notebook").
    target_text: str = ""  # Converted code (if applicable).
    compatibility_level: CompatibilityLevel = CompatibilityLevel.DIRECT
    source_dialect: str = "spark"
    warnings: tuple[ConversionWarning, ...] = ()
    manual_steps: tuple[ManualStep, ...] = ()
    rationale: str = ""  # Why this conversion approach was chosen.
    detected_patterns: tuple[SparkPattern, ...] = ()
    extracted_sql: tuple[str, ...] = ()  # SQL strings found in spark.sql() calls.
    storage_paths: tuple[str, ...] = ()  # GCS/HDFS/WASB paths detected.
    storage_mapping: dict[str, str] = field(default_factory=dict)  # Original path → OneLake mapping.
    edge_cases: tuple[str, ...] = ()  # Known edge cases.
    performance_notes: tuple[str, ...] = ()  # Performance considerations.
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_production_ready(self) -> bool:
        """Check if conversion output can be deployed without manual review."""
        return self.compatibility_level in {CompatibilityLevel.DIRECT, CompatibilityLevel.TRANSFORM}
