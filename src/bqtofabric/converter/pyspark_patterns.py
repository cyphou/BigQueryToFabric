"""PySpark pattern detection and extraction from Python code."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .models import SparkOperation, SparkPattern


@dataclass(frozen=True)
class PySpark_PatternMatcher:
    """Detect PySpark DataFrame API patterns and SQL within Python code."""

    # Regex patterns for common PySpark operations
    READ_PATTERNS = (
        r'spark\.read\.format\(["\']([^"\']+)["\']\)',  # format() call
        r'spark\.read\.(\w+)\(',  # spark.read.parquet(), spark.read.csv(), etc.
    )

    WRITE_PATTERNS = (
        r'\.write\.format\(["\']([^"\']+)["\']\)',  # format() call
        r'\.write\.(\w+)\(',  # .write.parquet(), .write.csv(), etc.
    )

    # Map pattern to operation and operation name
    DATAFRAME_OPS = (
        (r'\.select\(', SparkOperation.TRANSFORMATION, 'select'),
        (r'\.filter\(', SparkOperation.TRANSFORMATION, 'filter'),
        (r'\.where\(', SparkOperation.TRANSFORMATION, 'where'),
        (r'\.withColumn\(', SparkOperation.TRANSFORMATION, 'withcolumn'),
        (r'\.drop\(', SparkOperation.TRANSFORMATION, 'drop'),
        (r'\.rename\(', SparkOperation.TRANSFORMATION, 'rename'),
        (r'\.distinct\(', SparkOperation.TRANSFORMATION, 'distinct'),
        (r'\.limit\(', SparkOperation.TRANSFORMATION, 'limit'),
        (r'\.orderBy\(', SparkOperation.TRANSFORMATION, 'orderby'),
        (r'\.sort\(', SparkOperation.TRANSFORMATION, 'sort'),
        (r'\.groupBy\(', SparkOperation.AGGREGATION, 'groupby'),
        (r'\.agg\(', SparkOperation.AGGREGATION, 'agg'),
        (r'\.window\(', SparkOperation.AGGREGATION, 'window'),
        (r'\.over\(', SparkOperation.AGGREGATION, 'over'),
        (r'\.join\(', SparkOperation.JOIN, 'join'),
        (r'\.union\(', SparkOperation.JOIN, 'union'),
        (r'\.intersect\(', SparkOperation.JOIN, 'intersect'),
        (r'\.write\.', SparkOperation.SINK, 'write'),
        (r'\.saveAsTable\(', SparkOperation.SINK, 'saveastable'),
        (r'spark\.read\.', SparkOperation.INGESTION, 'read'),
    )

    SQL_PATTERNS = (
        r'spark\.sql\(["\']([^"\']*?)["\']\)',  # Simple string
        r'spark\.sql\(["\']([^"\']*?)["\']\s*\)',  # With spaces
        r'spark\.sql\(\s*"""(.*?)"""\s*\)',  # Triple-quoted
        r'spark\.sql\(\s*\'\'\'(.*?)\'\'\'\s*\)',  # Triple-quoted single
    )

    STREAMING_PATTERNS = (
        r'readStream\(',
        r'writeStream\(',
        r'trigger\(',
        r'checkpointLocation',
    )

    CONFIG_PATTERNS = (
        r'spark\.conf\.set\(',
        r'spark\.conf\.get\(',
        r'spark\.config\(',
    )

    UDF_PATTERNS = (
        r'@udf\(',
        r'@pandas_udf\(',
        r'udf\(',
        r'register\(.*?udf',
    )

    @staticmethod
    def extract_sql_from_code(code: str) -> tuple[str, ...]:
        """Extract SQL strings from spark.sql() calls."""
        extracted = set()  # Use set to avoid duplicates
        
        # First try triple-quoted patterns
        for pattern in [
            r'spark\.sql\(\s*"""(.*?)"""\s*\)',  # Triple-quoted double
            r"spark\.sql\(\s*'''(.*?)'''\s*\)",  # Triple-quoted single
        ]:
            matches = re.finditer(pattern, code, re.DOTALL | re.MULTILINE)
            for match in matches:
                sql_str = match.group(1)
                if sql_str.strip():
                    extracted.add(sql_str.strip())
        
        # Then try single-line patterns (but avoid if already matched as triple-quoted)
        single_line_pattern = r'spark\.sql\(["\']([^"\']*?)["\'](?:\s*[,)])'
        matches = re.finditer(single_line_pattern, code)
        for match in matches:
            sql_str = match.group(1)
            if sql_str.strip() and '"""' not in sql_str and "'''" not in sql_str:
                extracted.add(sql_str.strip())
        
        return tuple(sorted(extracted))

    @staticmethod
    def detect_read_patterns(code: str) -> list[dict[str, Any]]:
        """Detect spark.read.* patterns (handles multiline)."""
        patterns = []
        # Normalize: remove line continuations and reduce whitespace
        normalized = re.sub(r'\\\s*\n\s*', ' ', code)  # Handle \ continuations
        normalized = re.sub(r'\s+', ' ', normalized)  # Normalize whitespace
        
        # Check for format() method
        if 'spark.read' in normalized and 'format' in normalized:
            format_match = re.search(r'format\(\s*["\']([^"\']+)["\']\s*\)', normalized)
            if format_match:
                format_name = format_match.group(1)
                patterns.append({
                    'line': 1,
                    'type': 'read',
                    'format': format_name,
                    'snippet': normalized[:100],
                })
                return patterns
        
        # Check for direct method calls like spark.read.parquet()
        for pattern_str in PySpark_PatternMatcher.READ_PATTERNS:
            if re.search(pattern_str, normalized):
                method_match = re.search(r'read\.(\w+)\(', normalized)
                if method_match:
                    method_name = method_match.group(1)
                    patterns.append({
                        'line': 1,
                        'type': 'read',
                        'format': method_name,
                        'snippet': normalized[:100],
                    })
                    break
        
        return patterns

    @staticmethod
    def detect_write_patterns(code: str) -> list[dict[str, Any]]:
        """Detect .write.* patterns (handles multiline)."""
        patterns = []
        # For simplicity, check if code contains .write at all
        if '.write' not in code:
            return patterns
        
        # Remove all newlines and continuations
        normalized = code.replace('\n', ' ').replace('\\', '')
        normalized = re.sub(r'\s+', ' ', normalized)  # Normalize whitespace
        
        # Look for format() in the write chain
        if '.write' in normalized and 'format' in normalized:
            format_match = re.search(r'format\(\s*["\']([^"\']+)["\']\s*\)', normalized)
            if format_match:
                format_name = format_match.group(1)
                patterns.append({
                    'line': 1,
                    'type': 'write',
                    'format': format_name,
                    'snippet': normalized[:100],
                })
                return patterns
        
        # Look for direct write methods: .parquet(), .csv(), .delta(), .json(), etc.
        method_match = re.search(r'\.write\s*\.\s*(\w+)\s*\(', normalized)
        if method_match:
            method_name = method_match.group(1)
            patterns.append({
                'line': 1,
                'type': 'write',
                'format': method_name,
                'snippet': normalized[:100],
            })
        
        return patterns

    @staticmethod
    def detect_dataframe_operations(code: str) -> tuple[SparkPattern, ...]:
        """Detect DataFrame API operations (select, filter, groupBy, etc.)."""
        patterns = []
        lines = code.split('\n')
        
        for line_no, line in enumerate(lines, start=1):
            for pattern_str, operation, op_name in PySpark_PatternMatcher.DATAFRAME_OPS:
                if re.search(pattern_str, line):
                    patterns.append(
                        SparkPattern(
                            name=f"dataframe_{op_name}",
                            operation=operation,
                            line_range=(line_no, line_no),
                            code_snippet=line.strip(),
                        )
                    )
                    # Don't break - allow multiple operations on same line
        return tuple(patterns)

    @staticmethod
    def detect_streaming_patterns(code: str) -> tuple[SparkPattern, ...]:
        """Detect Spark Structured Streaming patterns."""
        patterns = []
        # Check if code contains streaming keywords
        if 'readStream' not in code and 'writeStream' not in code and \
           'trigger' not in code and 'checkpointLocation' not in code:
            return ()
        
        # Split on lines and check each for streaming patterns
        for line_no, line in enumerate(code.split('\n'), start=1):
            for pattern_str in PySpark_PatternMatcher.STREAMING_PATTERNS:
                # For readStream and writeStream, also match without parenthesis
                if pattern_str.endswith('('):
                    base_pattern = pattern_str[:-2]  # Remove \(
                    if re.search(base_pattern, line):
                        pattern_name = base_pattern.replace('\\', '')
                        patterns.append(
                            SparkPattern(
                                name=f"streaming_{pattern_name}",
                                operation=SparkOperation.STREAMING,
                                line_range=(line_no, line_no),
                                code_snippet=line.strip(),
                            )
                        )
                elif re.search(pattern_str, line):
                    pattern_name = pattern_str.replace('\\', '').rstrip('(')
                    patterns.append(
                        SparkPattern(
                            name=f"streaming_{pattern_name}",
                            operation=SparkOperation.STREAMING,
                            line_range=(line_no, line_no),
                            code_snippet=line.strip(),
                        )
                    )
        return tuple(patterns)

    @staticmethod
    def detect_config_patterns(code: str) -> tuple[SparkPattern, ...]:
        """Detect spark.conf.set/get patterns."""
        patterns = []
        lines = code.split('\n')
        
        for line_no, line in enumerate(lines, start=1):
            for pattern_str in PySpark_PatternMatcher.CONFIG_PATTERNS:
                if re.search(pattern_str, line):
                    pattern_name = pattern_str.rstrip('(').replace(r'\(', '')
                    patterns.append(
                        SparkPattern(
                            name=f"config_{pattern_name}",
                            operation=SparkOperation.CONFIGURATION,
                            line_range=(line_no, line_no),
                            code_snippet=line.strip(),
                        )
                    )
        return tuple(patterns)

    @staticmethod
    def detect_udf_patterns(code: str) -> tuple[SparkPattern, ...]:
        """Detect UDF definitions."""
        patterns = []
        lines = code.split('\n')
        
        for line_no, line in enumerate(lines, start=1):
            for pattern_str in PySpark_PatternMatcher.UDF_PATTERNS:
                if re.search(pattern_str, line):
                    pattern_name = 'udf_definition' if '@' in line else 'udf_register'
                    patterns.append(
                        SparkPattern(
                            name=pattern_name,
                            operation=SparkOperation.UDF,
                            line_range=(line_no, line_no),
                            code_snippet=line.strip(),
                        )
                    )
        return tuple(patterns)

    @staticmethod
    def detect_storage_paths(code: str) -> tuple[str, ...]:
        """Detect GCS, HDFS, WASB, ABFS paths."""
        path_patterns = (
            r'gs://[^\s"\']*',  # GCS
            r'hdfs://[^\s"\']*',  # HDFS
            r'wasb://[^\s"\']*',  # WASB
            r'abfs://[^\s"\']*',  # ABFS
            r's3://[^\s"\']*',  # S3
            r's3a://[^\s"\']*',  # S3A
        )
        paths = set()
        for pattern in path_patterns:
            matches = re.finditer(pattern, code)
            for match in matches:
                path = match.group(0).rstrip(',)')
                paths.add(path)
        return tuple(sorted(paths))

    @staticmethod
    def detect_credentials_in_paths(code: str) -> tuple[str, ...]:
        """Detect embedded credentials in paths (security issue)."""
        credential_patterns = (
            r'[?&](key|password|secret|token|api_key)=[^&\s"\']+',
            r'://\w+:\w+@',  # Basic auth in URL
        )
        credentials = []
        for pattern in credential_patterns:
            matches = re.finditer(pattern, code)
            for match in matches:
                credentials.append(match.group(0))
        return tuple(credentials)

    @staticmethod
    def detect_dynamic_sql(code: str) -> list[dict[str, Any]]:
        """Detect dynamic SQL (string interpolation in spark.sql calls)."""
        dynamic_patterns = []
        # Look for spark.sql( with f-strings or format()
        sql_calls = re.finditer(r'spark\.sql\(\s*([^)]+)\)', code, re.DOTALL)
        
        for match in sql_calls:
            sql_arg = match.group(1)
            line_no = code[:match.start()].count('\n') + 1
            
            # Check for f-string or format() usage
            if 'f"' in sql_arg or "f'" in sql_arg or '.format(' in sql_arg:
                dynamic_patterns.append({
                    'line': line_no,
                    'type': 'dynamic_sql',
                    'snippet': sql_arg.strip(),
                    'warning': 'Dynamic SQL (f-string or format) detected; manual review required.',
                })
        
        return dynamic_patterns


def analyze_pyspark_code(code: str) -> tuple[SparkPattern, ...]:
    """
    Comprehensive analysis of PySpark code: detect all patterns.
    
    Args:
        code: Python code containing PySpark operations.
    
    Returns:
        Tuple of detected SparkPattern objects.
    """
    patterns = []
    
    # Detect all pattern types
    patterns.extend(PySpark_PatternMatcher.detect_dataframe_operations(code))
    patterns.extend(PySpark_PatternMatcher.detect_streaming_patterns(code))
    patterns.extend(PySpark_PatternMatcher.detect_config_patterns(code))
    patterns.extend(PySpark_PatternMatcher.detect_udf_patterns(code))
    
    return tuple(patterns)
