"""Core Spark code conversion engine: PySpark and Scala analysis and transpilation."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from ..models import BigQueryObject, ObjectKind
from ..security import CredentialScanner
from .models import (
    CompatibilityLevel,
    ConversionWarning,
    ManualStep,
    SparkCodeLanguage,
    SparkConversion,
    SparkOperation,
    SparkPattern,
)
from .pyspark_patterns import PySpark_PatternMatcher, analyze_pyspark_code
from .scala_patterns import ScalaPatternMatcher, analyze_scala_code
from .sql_converter import SqlConverter
from .storage_mapping import StoragePathMapper


class SparkConverter:
    """Convert Spark code (PySpark, Scala) with pattern analysis and compatibility assessment."""

    def __init__(self) -> None:
        """Initialize Spark converter with SQL converter."""
        self.sql_converter = SqlConverter()
        self.credential_scanner = CredentialScanner()

    def _redact(self, value: str) -> str:
        """Remove credentials before they enter a conversion record."""
        return self.credential_scanner.redact(value)

    def _redact_value(self, value: Any) -> Any:
        """Redact credential-bearing strings recursively in persisted metadata."""
        if isinstance(value, str):
            return self._redact(value)
        if isinstance(value, dict):
            return {self._redact_value(key): self._redact_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._redact_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._redact_value(item) for item in value)
        return value

    def _redact_patterns(self, patterns: tuple[SparkPattern, ...]) -> tuple[SparkPattern, ...]:
        return tuple(
            replace(
                pattern,
                code_snippet=self._redact(pattern.code_snippet),
                metadata=self._redact_value(pattern.metadata),
            )
            for pattern in patterns
        )

    def convert(
        self,
        source_id: str,
        code: str,
        language: SparkCodeLanguage,
        lakehouse_name: str | None = None,
        preferences: dict[str, Any] | None = None,
    ) -> SparkConversion:
        """
        Analyze and convert Spark code.

        Args:
            source_id: Unique identifier (e.g., Dataproc job ID).
            code: Source Spark code (PySpark or Scala).
            language: Source code language.
            lakehouse_name: Optional Fabric lakehouse name for path mapping.
            preferences: Conversion preferences.

        Returns:
            SparkConversion with analysis, warnings, and recommendations.
        """
        if not code or not code.strip():
            return SparkConversion(
                source_id=source_id,
                language=language,
                source_text="",
                compatibility_level=CompatibilityLevel.DIRECT,
                rationale="No code to convert.",
            )

        # Route to language-specific analyzer
        if language == SparkCodeLanguage.PYSPARK:
            return self._convert_pyspark(source_id, code, lakehouse_name, preferences or {})
        elif language == SparkCodeLanguage.SCALA:
            return self._convert_scala(source_id, code, lakehouse_name, preferences or {})
        else:
            return SparkConversion(
                source_id=source_id,
                language=language,
                source_text=self._redact(code),
                compatibility_level=CompatibilityLevel.UNSUPPORTED,
                warnings=(
                    ConversionWarning(
                        f"Language {language} not supported.",
                        category="language",
                        severity="error",
                    ),
                ),
                rationale="Unsupported language.",
            )

    def _convert_pyspark(
        self,
        source_id: str,
        code: str,
        lakehouse_name: str | None = None,
        preferences: dict[str, Any] | None = None,
    ) -> SparkConversion:
        """Convert PySpark code."""
        warnings: list[ConversionWarning] = []
        manual_steps: list[ManualStep] = []
        compat_level = CompatibilityLevel.DIRECT

        # Extract SQL from spark.sql() calls
        extracted_sql = PySpark_PatternMatcher.extract_sql_from_code(code)

        # Detect dynamic SQL (security/maintenance issue)
        dynamic_sql_calls = PySpark_PatternMatcher.detect_dynamic_sql(code)
        if dynamic_sql_calls:
            for call in dynamic_sql_calls:
                warnings.append(
                    ConversionWarning(
                        message=f"Dynamic SQL detected at line {call['line']}: {call['warning']}",
                        location=f"line {call['line']}",
                        category="semantics",
                        severity="warning",
                    )
                )
            manual_steps.append(
                ManualStep(
                    step=(
                        "Review dynamic SQL (f-strings or .format()) for parameter "
                        "injection and SQL injection risks."
                    ),
                    rationale=(
                        "Dynamic SQL is harder to optimize and may have security "
                        "implications."
                    ),
                    priority="high",
                    affected_patterns=("dynamic_sql",),
                )
            )
            if compat_level == CompatibilityLevel.DIRECT:
                compat_level = CompatibilityLevel.TRANSFORM

        # Detect storage paths
        storage_paths = PySpark_PatternMatcher.detect_storage_paths(code)

        # Check for embedded credentials
        credentials_found = []
        for path in storage_paths:
            has_creds, _ = StoragePathMapper.check_embedded_credentials(path)
            if has_creds:
                credentials_found.append(path)
                warnings.append(
                    ConversionWarning(
                        message="Security issue: Credentials embedded in a storage path.",
                        category="security",
                        severity="error",
                    )
                )
        
        if credentials_found:
            manual_steps.append(
                ManualStep(
                    step=(
                        "Remove embedded credentials from paths; use managed identities "
                        "or Key Vault."
                    ),
                    rationale="Embedded credentials pose security risk.",
                    priority="critical",
                    affected_patterns=("storage_paths",),
                )
            )
            if compat_level == CompatibilityLevel.DIRECT:
                compat_level = CompatibilityLevel.REDESIGN

        # Map storage paths
        storage_mapping = StoragePathMapper.map_multiple_paths(storage_paths, lakehouse_name)

        target_text, rewrites = self._rewrite_pyspark(code, storage_mapping)
        for rewrite in rewrites:
            warnings.append(
                ConversionWarning(message=rewrite, category="rewrite", severity="info")
            )
        if rewrites and compat_level == CompatibilityLevel.DIRECT:
            compat_level = CompatibilityLevel.TRANSFORM

        # Detect all patterns
        patterns = analyze_pyspark_code(code)

        # Check for UDFs
        udf_patterns = [p for p in patterns if p.operation == SparkOperation.UDF]
        if udf_patterns:
            warnings.append(
                ConversionWarning(
                    message=f"Found {len(udf_patterns)} user-defined functions (UDFs).",
                    category="semantics",
                    severity="info",
                )
            )
            manual_steps.append(
                ManualStep(
                    step="Review UDFs for compatibility; Fabric Data Science or Spark SQL may offer alternatives.",
                    rationale="Some Python UDFs may not port directly; consider vectorized/Pandas UDFs.",
                    priority="medium",
                    affected_patterns=("udf",),
                )
            )
            if compat_level == CompatibilityLevel.DIRECT:
                compat_level = CompatibilityLevel.TRANSFORM

        # Detect streaming
        streaming_patterns = [p for p in patterns if p.operation == SparkOperation.STREAMING]
        if streaming_patterns:
            warnings.append(
                ConversionWarning(
                    message=f"Spark Structured Streaming detected ({len(streaming_patterns)} patterns).",
                    category="architecture",
                    severity="info",
                )
            )
            manual_steps.append(
                ManualStep(
                    step="Review Spark Structured Streaming topology; Fabric Eventstream or Eventhouse may be alternatives.",
                    rationale="Streaming patterns may require redesign for Fabric.",
                    priority="high",
                    affected_patterns=("streaming",),
                )
            )
            if compat_level == CompatibilityLevel.DIRECT:
                compat_level = CompatibilityLevel.TRANSFORM

        # Build conversion record
        return SparkConversion(
            source_id=source_id,
            language=SparkCodeLanguage.PYSPARK,
            source_text=self._redact(code),
            target_language="pyspark_notebook",
            target_text=self._redact(target_text),
            compatibility_level=compat_level,
            warnings=tuple(warnings),
            manual_steps=tuple(manual_steps),
            detected_patterns=self._redact_patterns(patterns),
            extracted_sql=tuple(self._redact(sql) for sql in extracted_sql),
            storage_paths=tuple(self._redact(path) for path in storage_paths),
            storage_mapping={
                self._redact(path): self._redact_value(storage_mapping[path])
                for path in storage_paths
            },
            rationale="PySpark code analyzed for Fabric compatibility.",
        )

    def _rewrite_pyspark(
        self, code: str, storage_mapping: dict[str, dict[str, Any]]
    ) -> tuple[str, list[str]]:
        """Rewrite the parts of a PySpark job that Fabric changes mechanically.

        Only substitutions with an unambiguous target are applied; everything else is
        left intact so a reviewer sees the original logic rather than a guess.
        """
        rewritten = code
        notes: list[str] = []

        for source_path, mapping in sorted(storage_mapping.items()):
            target_path = mapping.get("target_path")
            if not target_path or source_path not in rewritten:
                continue
            rewritten = rewritten.replace(source_path, str(target_path))
            notes.append(
                self._redact(f"Rewrote storage path {source_path} to {target_path}.")
            )

        # Fabric provides a live SparkSession; re-creating one is ignored at best.
        session_pattern = re.compile(
            r"(?m)^([ \t]*)([A-Za-z_][A-Za-z0-9_]*)\s*=\s*SparkSession\s*\.\s*builder"
            r"[\s\S]*?\.\s*getOrCreate\s*\(\s*\)"
        )
        rewritten, session_count = session_pattern.subn(
            lambda match: (
                f"{match.group(1)}# Fabric provides the SparkSession"
                if match.group(2) == "spark"
                else f"{match.group(1)}{match.group(2)} = spark  "
                "# Fabric provides the SparkSession"
            ),
            rewritten,
        )
        if session_count:
            notes.append(
                f"Replaced {session_count} SparkSession construction(s) with the "
                "Fabric-provided session."
            )

        context_pattern = re.compile(
            r"(?m)^([ \t]*)([A-Za-z_][A-Za-z0-9_]*)\s*=\s*SparkContext\s*\([^)]*\)"
        )
        rewritten, context_count = context_pattern.subn(
            lambda match: f"{match.group(1)}{match.group(2)} = spark.sparkContext",
            rewritten,
        )
        if context_count:
            notes.append(
                f"Replaced {context_count} SparkContext construction(s) with "
                "spark.sparkContext."
            )

        return rewritten, notes

    def _rewrite_scala(
        self, code: str, storage_mapping: dict[str, dict[str, Any]]
    ) -> tuple[str, list[str]]:
        """Rewrite the parts of Scala Spark code that can be mechanically transformed.

        Handles storage paths, SparkSession construction, and marks language-specific
        patterns for manual review. Scala → Python conversion is guided, not automated.
        """
        rewritten = code
        notes: list[str] = []

        # Rewrite storage paths
        for source_path, mapping in sorted(storage_mapping.items()):
            target_path = mapping.get("target_path")
            if not target_path or source_path not in rewritten:
                continue
            rewritten = rewritten.replace(source_path, str(target_path))
            notes.append(
                self._redact(f"Rewrote storage path {source_path} to {target_path}.")
            )

        # Fabric provides a live SparkSession; re-creating one is ignored at best.
        # Scala pattern: val spark = SparkSession.builder().appName(...).getOrCreate()
        scala_session_pattern = re.compile(
            r"(?m)^([ \t]*)val\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*SparkSession\s*\.\s*builder"
            r"[\s\S]*?\.\s*getOrCreate\s*\(\s*\)"
        )
        rewritten, scala_session_count = scala_session_pattern.subn(
            lambda match: (
                f"{match.group(1)}// Fabric provides the SparkSession"
                if match.group(2) == "spark"
                else f"{match.group(1)}{match.group(2)} = spark  "
                "// Fabric provides the SparkSession"
            ),
            rewritten,
        )
        if scala_session_count:
            notes.append(
                f"Replaced {scala_session_count} Scala SparkSession construction(s). "
                "Fabric provides the session; use it directly in Python."
            )

        # Convert val/var declarations to Python assignment syntax
        val_var_pattern = re.compile(r"(?m)^\s*(?:val|var)\s+")
        rewritten, val_var_count = val_var_pattern.subn("", rewritten)
        if val_var_count:
            notes.append(
                f"Removed {val_var_count} Scala val/var keyword(s); "
                "translated to Python assignment syntax."
            )

        return rewritten, notes

    def _convert_scala(
        self,
        source_id: str,
        code: str,
        lakehouse_name: str | None = None,
        preferences: dict[str, Any] | None = None,
    ) -> SparkConversion:
        """Convert Scala Spark code."""
        warnings: list[ConversionWarning] = []
        manual_steps: list[ManualStep] = []
        compat_level = CompatibilityLevel.TRANSFORM  # Scala → Python requires transformation.

        # Detect all patterns
        patterns = analyze_scala_code(code)

        # Check for RDD operations (legacy)
        rdd_patterns = [p for p in patterns if p.operation == SparkOperation.RDD]
        if rdd_patterns:
            warnings.append(
                ConversionWarning(
                    message=f"RDD operations detected ({len(rdd_patterns)} patterns); legacy Spark API.",
                    category="semantics",
                    severity="warning",
                )
            )
            manual_steps.append(
                ManualStep(
                    step="Refactor RDD operations to use Spark DataFrame API; RDD is legacy.",
                    rationale="RDD performance is poor compared to DataFrames; DataFrames are recommended.",
                    priority="high",
                    affected_patterns=("rdd",),
                )
            )
            if compat_level == CompatibilityLevel.DIRECT:
                compat_level = CompatibilityLevel.REDESIGN

        # Check for custom Scala UDFs
        udf_patterns = [p for p in patterns if p.operation == SparkOperation.UDF]
        if udf_patterns:
            warnings.append(
                ConversionWarning(
                    message=f"Custom Scala UDF detected ({len(udf_patterns)} functions); manual porting required.",
                    category="semantics",
                    severity="error",
                )
            )
            manual_steps.append(
                ManualStep(
                    step="Port Scala UDFs to Python; register as PySpark UDFs or use SQL UDFs in Spark SQL.",
                    rationale="Scala UDFs do not port directly to Python; manual translation needed.",
                    priority="critical",
                    affected_patterns=("udf",),
                )
            )
            if compat_level == CompatibilityLevel.DIRECT or compat_level == CompatibilityLevel.TRANSFORM:
                compat_level = CompatibilityLevel.REDESIGN

        # Detect storage paths
        storage_paths = ScalaPatternMatcher.detect_storage_paths(code)

        # Check for embedded credentials
        credentials_found = []
        for path in storage_paths:
            has_creds, _ = StoragePathMapper.check_embedded_credentials(path)
            if has_creds:
                credentials_found.append(path)
                warnings.append(
                    ConversionWarning(
                        message="Security issue: Credentials embedded in a storage path.",
                        category="security",
                        severity="error",
                    )
                )
        
        if credentials_found:
            manual_steps.append(
                ManualStep(
                    step="Remove embedded credentials; use managed identities or Key Vault.",
                    rationale="Embedded credentials are security risk.",
                    priority="critical",
                    affected_patterns=("storage_paths",),
                )
            )
            if compat_level != CompatibilityLevel.REDESIGN:
                compat_level = CompatibilityLevel.REDESIGN

        # Map storage paths
        storage_mapping = StoragePathMapper.map_multiple_paths(storage_paths, lakehouse_name)

        # Apply mechanical Scala rewrites (SparkSession, paths, etc.)
        target_text, rewrites = self._rewrite_scala(code, storage_mapping)
        for rewrite in rewrites:
            warnings.append(
                ConversionWarning(message=rewrite, category="rewrite", severity="info")
            )
        if rewrites and compat_level == CompatibilityLevel.TRANSFORM:
            # Keep as TRANSFORM since val/var and other syntax still need manual port
            pass

        # Extract SQL from spark.sql() calls
        extracted_sql = ScalaPatternMatcher.detect_sql_patterns(code)

        # Scala → Python conversion note
        warnings.append(
            ConversionWarning(
                message="Scala code requires manual translation to Python for Fabric notebooks.",
                category="language",
                severity="info",
            )
        )
        manual_steps.append(
            ManualStep(
                step="Port Scala code to PySpark (Python); Fabric notebooks are Python-based.",
                rationale="Fabric Data Engineering notebooks use Python/PySpark, not Scala.",
                priority="critical",
                affected_patterns=("language",),
            )
        )

        # Build conversion record
        return SparkConversion(
            source_id=source_id,
            language=SparkCodeLanguage.SCALA,
            source_text=self._redact(code),
            target_language="python",
            target_text=self._redact(target_text),  # Mechanical transformations applied
            compatibility_level=compat_level,
            warnings=tuple(warnings),
            manual_steps=tuple(manual_steps),
            detected_patterns=self._redact_patterns(patterns),
            extracted_sql=tuple(self._redact(sql) for sql in extracted_sql),
            storage_paths=tuple(self._redact(path) for path in storage_paths),
            storage_mapping={
                self._redact(path): self._redact_value(storage_mapping[path])
                for path in storage_paths
            },
            rationale="Scala code requires manual translation to Python for Fabric; mechanical rewrites applied.",
        )

    def extract_embedded_sql(
        self,
        code: str,
        language: SparkCodeLanguage,
    ) -> tuple[str, ...]:
        """
        Extract all SQL queries from spark.sql() calls.
        
        Args:
            code: Source code.
            language: Language (PySpark or Scala).
        
        Returns:
            Tuple of extracted SQL strings.
        """
        if language == SparkCodeLanguage.PYSPARK:
            return PySpark_PatternMatcher.extract_sql_from_code(code)
        elif language == SparkCodeLanguage.SCALA:
            return ScalaPatternMatcher.detect_sql_patterns(code)
        else:
            return ()

    def convert_embedded_sql(
        self,
        extracted_sql: tuple[str, ...],
        target_dialect: str = "spark_sql",
    ) -> dict[str, Any]:
        """
        Convert extracted SQL queries using the SQL converter.
        
        Args:
            extracted_sql: Tuple of SQL strings.
            target_dialect: Target SQL dialect.
        
        Returns:
            Dict mapping SQL string → conversion result.
        """
        results = {}
        for idx, sql_str in enumerate(extracted_sql):
            # Create a BigQueryObject wrapper for SQL conversion
            sql_obj = BigQueryObject(
                source_id=f"embedded_sql_{idx}",
                name=f"embedded_query_{idx}",
                kind=ObjectKind.SQL_SCRIPT,
                sql=sql_str,
            )
            
            # Convert using SQL converter
            conversion = self.sql_converter.convert(sql_obj)
            results[sql_str] = conversion
        
        return results
