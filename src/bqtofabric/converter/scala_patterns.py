"""Scala Spark pattern detection and analysis."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .models import SparkOperation, SparkPattern


@dataclass(frozen=True)
class ScalaPatternMatcher:
    """Detect Scala Spark patterns and operations."""

    READ_PATTERNS = (
        r'spark\.read\.(\w+)\(',  # spark.read.parquet(), spark.read.csv(), etc.
        r'spark\.read\.format\(["\']([^"\']+)["\']\)',  # format() call
    )

    WRITE_PATTERNS = (
        r'\.write\.(\w+)\(',  # .write.parquet(), .write.csv(), etc.
        r'\.write\.format\(["\']([^"\']+)["\']\)',  # format() call
    )

    DATAFRAME_PATTERNS = {
        # Transformations
        r'\.select\(': SparkOperation.TRANSFORMATION,
        r'\.filter\(': SparkOperation.TRANSFORMATION,
        r'\.where\(': SparkOperation.TRANSFORMATION,
        r'\.withColumn\(': SparkOperation.TRANSFORMATION,
        r'\.drop\(': SparkOperation.TRANSFORMATION,
        r'\.distinct\(': SparkOperation.TRANSFORMATION,
        r'\.limit\(': SparkOperation.TRANSFORMATION,
        r'\.orderBy\(': SparkOperation.TRANSFORMATION,
        r'\.sort\(': SparkOperation.TRANSFORMATION,
        # Aggregations
        r'\.groupBy\(': SparkOperation.AGGREGATION,
        r'\.agg\(': SparkOperation.AGGREGATION,
        r'\.window\(': SparkOperation.AGGREGATION,
        r'\.over\(': SparkOperation.AGGREGATION,
        # Joins
        r'\.join\(': SparkOperation.JOIN,
        r'\.union\(': SparkOperation.JOIN,
        r'\.intersect\(': SparkOperation.JOIN,
        # Sinks
        r'\.write\.': SparkOperation.SINK,
        r'\.saveAsTable\(': SparkOperation.SINK,
        # Ingestion
        r'spark\.read\.': SparkOperation.INGESTION,
    }

    # RDD operations (legacy, should be flagged for redesign)
    RDD_PATTERNS = (
        r'\.rdd\b',  # Access to RDD
        r'sparkContext\.',  # Direct sparkContext access (RDD API)
        r'\.map\(', r'\.flatMap\(', r'\.mapPartitions\(',
        r'\.reduce\(', r'\.fold\(', r'\.aggregate\(',
        r'\.collect\(', r'\.take\(', r'\.first\(',
        r'\.saveAsTextFile\(', r'\.saveAsSequenceFile\(',
    )

    # UDF patterns
    UDF_PATTERNS = (
        r'def\s+\w+\(.*?\).*?:.*?= {',  # Custom function
        r'udf\(',
        r'register\(.*?udf',
    )

    SQL_PATTERNS = (
        r'spark\.sql\(["\']([^"\']*?)["\']\)',  # Simple string
        r'spark\.sql\(\s*"""(.*?)"""\s*\)',  # Triple-quoted
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
    )

    @staticmethod
    def detect_read_patterns(code: str) -> list[dict[str, Any]]:
        """Detect spark.read.* patterns."""
        patterns = []
        for line_no, line in enumerate(code.split('\n'), start=1):
            for pattern_str in ScalaPatternMatcher.READ_PATTERNS:
                if re.search(pattern_str, line):
                    format_match = re.search(r'read\.(\w+|\(["\']([^"\']+)["\']\))', line)
                    if format_match:
                        format_name = format_match.group(1) or format_match.group(2)
                        patterns.append({
                            'line': line_no,
                            'type': 'read',
                            'format': format_name,
                            'snippet': line.strip(),
                        })
        return patterns

    @staticmethod
    def detect_write_patterns(code: str) -> list[dict[str, Any]]:
        """Detect .write.* patterns."""
        patterns = []
        for line_no, line in enumerate(code.split('\n'), start=1):
            for pattern_str in ScalaPatternMatcher.WRITE_PATTERNS:
                if re.search(pattern_str, line):
                    format_match = re.search(r'write\.(\w+|\(["\']([^"\']+)["\']\))', line)
                    if format_match:
                        format_name = format_match.group(1) or format_match.group(2)
                        patterns.append({
                            'line': line_no,
                            'type': 'write',
                            'format': format_name,
                            'snippet': line.strip(),
                        })
        return patterns

    @staticmethod
    def detect_dataframe_operations(code: str) -> tuple[SparkPattern, ...]:
        """Detect DataFrame API operations."""
        patterns = []
        lines = code.split('\n')
        
        for line_no, line in enumerate(lines, start=1):
            for pattern_str, operation in ScalaPatternMatcher.DATAFRAME_PATTERNS.items():
                if re.search(pattern_str, line):
                    op_match = re.search(r'\.(\w+)\(', line)
                    if op_match:
                        op_name = op_match.group(1)
                        patterns.append(
                            SparkPattern(
                                name=f"dataframe_{op_name}",
                                operation=operation,
                                line_range=(line_no, line_no),
                                code_snippet=line.strip(),
                            )
                        )
        return tuple(patterns)

    @staticmethod
    def detect_rdd_operations(code: str) -> tuple[SparkPattern, ...]:
        """Detect RDD operations (legacy, flag for redesign)."""
        patterns = []
        normalized = code.replace('\\\n', ' ').replace('\n', ' ')
        
        for pattern_str in ScalaPatternMatcher.RDD_PATTERNS:
            if re.search(pattern_str, normalized):
                # Get the operation name from pattern
                # e.g., r'\.map\(' -> 'map'
                op_match = re.search(r'\.(\w+)\\?', pattern_str)
                op_name = op_match.group(1) if op_match else 'rdd_op'
                
                # Find in original code for line numbers
                line_match = re.search(pattern_str, code)
                line_no = code[:line_match.start()].count('\n') + 1 if line_match else 1
                
                patterns.append(
                    SparkPattern(
                        name=f"rdd_{op_name}",
                        operation=SparkOperation.RDD,
                        line_range=(line_no, line_no),
                        code_snippet=code[line_match.start():line_match.start()+50] if line_match else '',
                        metadata={'flag': 'redesign', 'reason': 'RDD operations are legacy; use DataFrame API'},
                    )
                )
        return tuple(patterns)

    @staticmethod
    def detect_udf_definitions(code: str) -> tuple[SparkPattern, ...]:
        """Detect custom UDF definitions."""
        patterns = []
        lines = code.split('\n')

        for line_no, line in enumerate(lines, start=1):
            # Detect function definitions
            if re.match(r'\s*def\s+\w+\(.*?\).*?:', line):
                patterns.append(
                    SparkPattern(
                        name="udf_custom_scala",
                        operation=SparkOperation.UDF,
                        line_range=(line_no, line_no),
                        code_snippet=line.strip(),
                        metadata={'flag': 'redesign', 'reason': 'Custom Scala UDFs require manual porting to Python'},
                    )
                )
            
            # Detect registered UDFs
            for pattern_str in ScalaPatternMatcher.UDF_PATTERNS:
                if re.search(pattern_str, line):
                    patterns.append(
                        SparkPattern(
                            name="udf_registered",
                            operation=SparkOperation.UDF,
                            line_range=(line_no, line_no),
                            code_snippet=line.strip(),
                            metadata={'flag': 'redesign', 'reason': 'Scala UDFs need to be converted to Python UDFs'},
                        )
                    )
        
        return tuple(patterns)

    @staticmethod
    def detect_sql_patterns(code: str) -> tuple[str, ...]:
        """Extract SQL from spark.sql() calls."""
        extracted = []
        for pattern_str in ScalaPatternMatcher.SQL_PATTERNS:
            matches = re.finditer(pattern_str, code, re.DOTALL | re.MULTILINE)
            for match in matches:
                sql_str = match.group(1)
                if sql_str.strip():
                    extracted.append(sql_str.strip())
        return tuple(extracted)

    @staticmethod
    def detect_streaming_patterns(code: str) -> tuple[SparkPattern, ...]:
        """Detect Spark Structured Streaming patterns."""
        patterns = []
        lines = code.split('\n')
        
        for line_no, line in enumerate(lines, start=1):
            for pattern_str in ScalaPatternMatcher.STREAMING_PATTERNS:
                if re.search(pattern_str, line):
                    pattern_name = pattern_str.rstrip('(').replace(r'\(', '')
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
        """Detect spark.conf patterns."""
        patterns = []
        lines = code.split('\n')
        
        for line_no, line in enumerate(lines, start=1):
            for pattern_str in ScalaPatternMatcher.CONFIG_PATTERNS:
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


def analyze_scala_code(code: str) -> tuple[SparkPattern, ...]:
    """
    Comprehensive analysis of Scala Spark code: detect all patterns.
    
    Args:
        code: Scala code containing Spark operations.
    
    Returns:
        Tuple of detected SparkPattern objects.
    """
    patterns = []
    
    # Detect all pattern types
    patterns.extend(ScalaPatternMatcher.detect_dataframe_operations(code))
    patterns.extend(ScalaPatternMatcher.detect_rdd_operations(code))
    patterns.extend(ScalaPatternMatcher.detect_udf_definitions(code))
    patterns.extend(ScalaPatternMatcher.detect_streaming_patterns(code))
    patterns.extend(ScalaPatternMatcher.detect_config_patterns(code))
    
    return tuple(patterns)
