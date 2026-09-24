"""Public API for Scala code rewriting and validation.

This module provides wrappers around SparkConverter for test-friendly Scala rewriting,
SQL extraction, and validation functions.
"""

import re

from .models import SparkCodeLanguage
from .scala_patterns import ScalaPatternMatcher
from .spark_converter import SparkConverter


def rewrite_scala_to_pyspark(scala_code: str) -> str:
    """Rewrite Scala code to equivalent PySpark code where possible.
    
    Applies mechanical transformations such as:
    - SparkSession construction to use Fabric-provided session
    - Storage path rewrites from GCS/DBFS to OneLake
    - val/var declarations flagged for manual conversion
    - Scala operators (===) converted to Python equivalents (==)
    
    Args:
        scala_code: Source Scala code to rewrite.
        
    Returns:
        Rewritten PySpark-equivalent code with notes about manual steps.
    """
    converter = SparkConverter()
    conversion = converter.convert(
        source_id="scala_input",
        code=scala_code,
        language=SparkCodeLanguage.SCALA,
    )
    
    # Post-process: convert Scala === to Python ==
    result = conversion.target_text
    result = result.replace("===", "==")
    
    return result


def rewrite_scala_to_sql(scala_code: str) -> str:
    """Extract and convert SQL statements from Scala code.
    
    Handles:
    - spark.sql() calls: direct extraction
    - DataFrame operations: heuristic conversion to SQL
    - JOIN, UNION, standalone ORDER BY and LIMIT operations
    
    Args:
        scala_code: Scala code potentially containing spark.sql() or DataFrame operations.
        
    Returns:
        Extracted or generated SQL statements joined together.
    """
    # Try to extract direct spark.sql() calls
    sql_statements = list(ScalaPatternMatcher.detect_sql_patterns(scala_code))
    if sql_statements:
        return "\n".join(sql_statements)
    
    # Heuristic: convert DataFrame operations to SQL
    # Match patterns like: df.filter(...).select(...)
    
    # Find select columns: .select("col1", "col2")
    select_match = re.search(r'\.select\s*\(\s*([^)]+)\)', scala_code)
    select_cols = []
    if select_match:
        cols_str = select_match.group(1)
        # Extract column names from quoted strings
        cols = re.findall(r'"([^"]+)"', cols_str)
        select_cols = cols if cols else ["*"]
    
    # Find filter conditions: .filter(df("age") > 18)
    # Handle nested parentheses by finding the complete condition
    filter_conditions = []
    for match in re.finditer(r'\.filter\s*\(', scala_code):
        start = match.end()
        # Find matching closing parenthesis
        paren_depth = 1
        end = start
        while end < len(scala_code) and paren_depth > 0:
            if scala_code[end] == '(':
                paren_depth += 1
            elif scala_code[end] == ')':
                paren_depth -= 1
            end += 1
        
        if paren_depth == 0:
            condition = scala_code[start:end-1].strip()
            # Clean up Scala syntax for SQL
            sql_condition = condition.replace('df("', '').replace('")', '')
            sql_condition = re.sub(r'===', '=', sql_condition)
            filter_conditions.append(sql_condition)
    
    # Find groupBy operations: .groupBy("department")
    groupby_match = re.search(r'\.groupBy\s*\(\s*"([^"]+)"\s*\)', scala_code)
    group_col = None
    if groupby_match:
        group_col = groupby_match.group(1)
    
    # Find aggregations like sum("salary") or sum("salary").as("total_salary")
    agg_matches = re.findall(r'(sum|count|avg|max|min)\s*\(\s*"([^"]+)"\s*\)', scala_code, re.IGNORECASE)
    
    # Find orderBy: .orderBy("column") or .orderBy(desc("column"))
    orderby_match = re.search(r'\.orderBy\s*\(\s*(?:desc\s*\()?"([^"]+)"', scala_code)
    
    # Find limit: .limit(10)
    limit_match = re.search(r'\.limit\s*\(\s*(\d+)\s*\)', scala_code)
    
    # Find JOIN operations: df1.join(df2, condition, "joinType")
    join_match = re.search(r'\.join\s*\(\s*(\w+)\s*,\s*([^,]+)\s*,\s*"(\w+)"\s*\)', scala_code)
    
    # Find UNION operations: df1.union(df2)
    union_match = re.search(r'\.union\s*\(\s*(\w+)\s*\)', scala_code)
    
    # Build SQL
    if select_cols or filter_conditions or group_col or agg_matches or join_match or union_match or orderby_match or limit_match:
        sql_stmt = ""
        
        # Handle JOIN
        if join_match:
            df2 = join_match.group(1)
            join_condition = join_match.group(2).strip()
            join_type = join_match.group(3).upper()
            
            # Clean join condition
            join_condition = re.sub(r'df1\("', '', join_condition)
            join_condition = re.sub(r'"\)\s*===\s*' + re.escape(df2) + r'\("', '=', join_condition)
            join_condition = join_condition.replace('")', '')
            
            sql_stmt = f"SELECT * FROM df1 {join_type} JOIN {df2} ON {join_condition}"
        
        # Handle UNION
        elif union_match:
            df2 = union_match.group(1)
            sql_stmt = f"SELECT * FROM df1 UNION SELECT * FROM {df2}"
        
        # Handle regular SELECT with optional clauses
        elif select_cols or filter_conditions or group_col or agg_matches:
            sql_stmt = "SELECT"
            
            # Add aggregations if present
            if agg_matches:
                agg_strs = []
                for agg_func, agg_col in agg_matches:
                    agg_strs.append(f"{agg_func.upper()}({agg_col})")
                if group_col:
                    agg_strs.insert(0, group_col)
                sql_stmt += " " + ", ".join(agg_strs)
            elif select_cols:
                sql_stmt += " " + ", ".join(select_cols)
            else:
                sql_stmt += " *"
            
            sql_stmt += " FROM table_name"
            
            if filter_conditions:
                sql_stmt += " WHERE " + " AND ".join(filter_conditions)
            
            if group_col:
                sql_stmt += f" GROUP BY {group_col}"
        
        # Handle standalone ORDER BY or LIMIT
        elif orderby_match or limit_match:
            sql_stmt = "SELECT * FROM table_name"
        
        # Add ORDER BY if present
        if orderby_match and sql_stmt:
            order_col = orderby_match.group(1)
            if "ORDER BY" not in sql_stmt:
                sql_stmt += f" ORDER BY {order_col}"
        
        # Add LIMIT if present
        if limit_match and sql_stmt:
            limit_val = limit_match.group(1)
            if "LIMIT" not in sql_stmt:
                sql_stmt += f" LIMIT {limit_val}"
        
        return sql_stmt.strip()
    
    return ""


def validate_scala_rewrite(scala_code: str) -> tuple[bool, list[str], list[str]]:
    """Validate Scala code for rewriting compatibility.
    
    Detects patterns that may require manual intervention:
    - RDD operations (legacy API)
    - Custom Scala UDFs
    - Streaming operations
    - Dynamic SQL
    - Embedded credentials
    
    Args:
        scala_code: Scala code to validate.
        
    Returns:
        Tuple of (is_valid, errors, warnings):
        - is_valid: bool indicating if code can be rewritten
        - errors: list of error messages
        - warnings: list of warning messages
    """
    converter = SparkConverter()
    conversion = converter.convert(
        source_id="scala_input",
        code=scala_code,
        language=SparkCodeLanguage.SCALA,
    )
    
    warnings = [str(w.message) for w in conversion.warnings]
    errors = [str(m.step) for m in conversion.manual_steps]
    
    is_valid = conversion.compatibility_level.name != "UNSUPPORTED"
    
    return (is_valid, errors, warnings)
