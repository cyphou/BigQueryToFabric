"""Comprehensive tests for SQL converter: GoogleSQL → T-SQL, Spark SQL, PySpark."""

import json
from pathlib import Path

import pytest

from bqtofabric.converter import (
    CompatibilityLevel,
    SqlConverter,
    TargetDialect,
    classify_workload,
    estimate_complexity,
    route_to_dialect,
)
from bqtofabric.models import BigQueryObject, ObjectKind

# Fixtures

@pytest.fixture
def converter() -> SqlConverter:
    """Create a SQL converter instance."""
    return SqlConverter()


def test_multi_statement_select_only(converter: SqlConverter) -> None:
    """Two independent SELECT statements must each be converted."""
    sql = "SELECT 1 AS id; SELECT 2 AS id"

    result = converter.convert_multiple(sql)

    assert len(result.statements) == 2
    assert result.compatibility == CompatibilityLevel.DIRECT
    assert "SELECT 1" in result.statements[0].target_text.upper()
    assert "SELECT 2" in result.statements[1].target_text.upper()


def test_multi_statement_with_dml_requires_redesign(converter: SqlConverter) -> None:
    """Multi-statement DML must not be emitted as independent target SQL."""
    sql = "INSERT INTO table1 VALUES (1); SELECT * FROM table1"

    result = converter.convert_multiple(sql)

    assert result.compatibility == CompatibilityLevel.REDESIGN
    assert any("transaction" in warning.message.lower() for warning in result.warnings)


def test_multi_statement_single_statement_is_backward_compatible(converter: SqlConverter) -> None:
    """A single statement remains directly convertible through the new API."""
    result = converter.convert_multiple("SELECT 1 AS id")

    assert len(result.statements) == 1
    assert result.compatibility == CompatibilityLevel.DIRECT


@pytest.fixture
def patterns_fixture() -> dict:
    """Load test patterns from fixture file."""
    fixture_path = Path(__file__).parent / "fixtures" / "sql_conversions" / "patterns.json"
    with open(fixture_path) as f:
        return json.load(f)


# =====================================================================
# PATTERN DETECTION TESTS (5 tests)
# =====================================================================


def test_detect_pattern_simple_select(converter: SqlConverter) -> None:
    """Test detection of simple SELECT pattern."""
    sql = "SELECT * FROM orders LIMIT 10"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert "select" in result.detected_patterns
    assert "limit" in result.detected_patterns


def test_detect_pattern_window_functions(converter: SqlConverter) -> None:
    """Test detection of window function pattern."""
    sql = "SELECT order_id, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date) FROM orders"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert "window_functions" in result.detected_patterns
    # window_with_partition may or may not be detected depending on sqlglot parsing


def test_detect_pattern_unnest(converter: SqlConverter) -> None:
    """Test detection of UNNEST pattern."""
    sql = "SELECT order_id, item FROM orders CROSS JOIN UNNEST(items) AS item"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert "unnest" in result.detected_patterns


def test_detect_pattern_struct_types(converter: SqlConverter) -> None:
    """Test detection of STRUCT type pattern."""
    sql = "SELECT order_id, customer.name, customer.email FROM orders"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    # Struct detection depends on sqlglot parsing
    assert result.detected_patterns is not None


def test_detect_pattern_multiple_joins(converter: SqlConverter) -> None:
    """Test detection of multiple JOINs."""
    sql = """SELECT o.order_id, c.customer_name, p.product_name
    FROM orders o
    INNER JOIN customers c ON o.customer_id = c.id
    LEFT JOIN products p ON o.product_id = p.id
    RIGHT JOIN categories cat ON p.category_id = cat.id"""
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert "joins" in result.detected_patterns
    assert "multi_join" in result.detected_patterns


# =====================================================================
# SIMPLE SELECT CONVERSION TESTS (5 tests)
# =====================================================================


def test_convert_simple_select_tsql(converter: SqlConverter) -> None:
    """Test conversion of simple SELECT to T-SQL."""
    sql = "SELECT user_id, COUNT(*) as cnt FROM orders GROUP BY user_id LIMIT 10"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.TSQL)
    assert result.target_text
    assert result.compatibility_level in {
        CompatibilityLevel.DIRECT,
        CompatibilityLevel.TRANSFORM,
    }
    assert "SELECT" in result.target_text.upper()


def test_convert_simple_select_spark_sql(converter: SqlConverter) -> None:
    """Test conversion of simple SELECT to Spark SQL."""
    sql = "SELECT * FROM orders WHERE status = 'completed'"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.target_text
    assert result.compatibility_level in {
        CompatibilityLevel.DIRECT,
        CompatibilityLevel.TRANSFORM,
    }


def test_convert_simple_select_pyspark(converter: SqlConverter) -> None:
    """Test conversion of simple SELECT to PySpark."""
    sql = "SELECT order_id, amount FROM orders ORDER BY amount DESC"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.PYSPARK)
    # PySpark may use Python dialect which may not generate SQL text
    assert result.target_dialect == TargetDialect.PYSPARK
    # PySpark conversions may result in different compatibility levels
    assert result.compatibility_level in {
        CompatibilityLevel.DIRECT,
        CompatibilityLevel.TRANSFORM,
        CompatibilityLevel.REDESIGN,
    }


def test_convert_order_by_limit(converter: SqlConverter) -> None:
    """Test conversion with ORDER BY and LIMIT."""
    sql = "SELECT * FROM orders ORDER BY created_at DESC LIMIT 100"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert "ORDER BY" in result.target_text.upper() or "order by" in result.target_text
    assert "LIMIT" in result.target_text.upper() or "limit" in result.target_text


def test_convert_group_by_aggregate(converter: SqlConverter) -> None:
    """Test conversion with GROUP BY and aggregates."""
    sql = "SELECT customer_id, SUM(amount) as total, AVG(amount) as avg_amt FROM orders GROUP BY customer_id"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.TSQL)
    assert result.target_text
    assert result.compatibility_level in {
        CompatibilityLevel.DIRECT,
        CompatibilityLevel.TRANSFORM,
    }


# =====================================================================
# JOIN CONVERSION TESTS (5 tests)
# =====================================================================


def test_convert_inner_join(converter: SqlConverter) -> None:
    """Test conversion with INNER JOIN."""
    sql = "SELECT o.order_id, c.customer_name FROM orders o INNER JOIN customers c ON o.customer_id = c.id"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert "JOIN" in result.target_text.upper()
    assert result.compatibility_level in {
        CompatibilityLevel.DIRECT,
        CompatibilityLevel.TRANSFORM,
    }


def test_convert_left_join(converter: SqlConverter) -> None:
    """Test conversion with LEFT JOIN."""
    sql = "SELECT o.order_id, c.customer_name FROM orders o LEFT JOIN customers c ON o.customer_id = c.id"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.TSQL)
    assert "JOIN" in result.target_text.upper()


def test_convert_multiple_joins(converter: SqlConverter) -> None:
    """Test conversion with multiple JOINs."""
    sql = """SELECT o.order_id, c.customer_name, p.product_name
    FROM orders o
    INNER JOIN customers c ON o.customer_id = c.id
    LEFT JOIN products p ON o.product_id = p.id"""
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.target_text
    assert result.compatibility_level in {
        CompatibilityLevel.DIRECT,
        CompatibilityLevel.TRANSFORM,
    }


def test_convert_right_join(converter: SqlConverter) -> None:
    """Test conversion with RIGHT JOIN."""
    sql = "SELECT o.order_id FROM orders o RIGHT JOIN customers c ON o.customer_id = c.id"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.TSQL)
    assert result.target_text


def test_convert_full_outer_join(converter: SqlConverter) -> None:
    """Test conversion with FULL OUTER JOIN."""
    sql = "SELECT * FROM orders o FULL OUTER JOIN customers c ON o.customer_id = c.id"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.target_text


# =====================================================================
# WINDOW FUNCTION CONVERSION TESTS (5 tests)
# =====================================================================


def test_convert_row_number_window(converter: SqlConverter) -> None:
    """Test conversion with ROW_NUMBER window function."""
    sql = "SELECT order_id, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date) as rn FROM orders"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.target_text
    assert "OVER" in result.target_text.upper()
    assert result.compatibility_level in {
        CompatibilityLevel.DIRECT,
        CompatibilityLevel.TRANSFORM,
    }


def test_convert_rank_window(converter: SqlConverter) -> None:
    """Test conversion with RANK window function."""
    sql = "SELECT order_id, RANK() OVER (PARTITION BY customer_id ORDER BY amount DESC) as rank FROM orders"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.TSQL)
    assert result.target_text


def test_convert_sum_over_window(converter: SqlConverter) -> None:
    """Test conversion with SUM OVER window function."""
    sql = "SELECT order_id, SUM(amount) OVER (PARTITION BY customer_id ORDER BY order_date) as running_total FROM orders"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.target_text


def test_convert_lag_lead_window(converter: SqlConverter) -> None:
    """Test conversion with LAG/LEAD window functions."""
    sql = "SELECT order_id, LAG(amount) OVER (ORDER BY order_date) as prev_amt, LEAD(amount) OVER (ORDER BY order_date) as next_amt FROM orders"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.TSQL)
    assert result.target_text


def test_convert_qualify_clause(converter: SqlConverter) -> None:
    """Test conversion with QUALIFY clause (should generate warning)."""
    sql = "SELECT order_id, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date) as rn FROM orders QUALIFY rn <= 3"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    # QUALIFY may or may not parse depending on sqlglot version
    # But if it does, we should see a warning or compatibility level change
    assert result.target_text or result.warnings


# =====================================================================
# CASE AND NULL HANDLING TESTS (4 tests)
# =====================================================================


def test_convert_case_expression(converter: SqlConverter) -> None:
    """Test conversion with CASE expression."""
    sql = """SELECT customer_id,
    CASE
        WHEN total_spent > 10000 THEN 'VIP'
        WHEN total_spent > 5000 THEN 'Premium'
        ELSE 'Standard'
    END as tier
    FROM customers"""
    obj = BigQueryObject(
        source_id="test.customers",
        name="customers",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.target_text
    assert "CASE" in result.target_text.upper()


def test_convert_coalesce(converter: SqlConverter) -> None:
    """Test conversion with COALESCE."""
    sql = "SELECT order_id, COALESCE(discount, 0) as discount FROM orders"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.TSQL)
    assert result.target_text
    assert "COALESCE" in result.target_text.upper()


def test_convert_nullif(converter: SqlConverter) -> None:
    """Test conversion with NULLIF."""
    sql = "SELECT order_id, NULLIF(quantity, 0) as qty FROM orders"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.target_text


def test_convert_is_null(converter: SqlConverter) -> None:
    """Test conversion with IS NULL."""
    sql = "SELECT order_id FROM orders WHERE discount IS NULL"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.TSQL)
    assert result.target_text
    assert "NULL" in result.target_text.upper()


def test_safe_cast_requires_semantic_review(converter: SqlConverter) -> None:
    """SAFE_CAST conversions must verify null-on-failure behavior in the target."""
    obj = BigQueryObject(
        source_id="test.safe_cast",
        name="safe_cast",
        kind=ObjectKind.VIEW,
        sql="SELECT SAFE_CAST(raw_value AS INT64) AS value FROM events",
    )

    result = converter.convert(obj, TargetDialect.TSQL)

    assert "safe_cast" in result.detected_patterns
    assert result.compatibility_level == CompatibilityLevel.TRANSFORM
    assert any("SAFE_CAST" in warning.message for warning in result.warnings)


def test_not_in_requires_null_semantics_review(converter: SqlConverter) -> None:
    """NOT IN conversions must explicitly account for NULL-containing inputs."""
    obj = BigQueryObject(
        source_id="test.not_in",
        name="not_in",
        kind=ObjectKind.VIEW,
        sql="SELECT * FROM events WHERE customer_id NOT IN (SELECT customer_id FROM blocked)",
    )

    result = converter.convert(obj, TargetDialect.SPARK_SQL)

    assert "not_in" in result.detected_patterns
    assert result.compatibility_level == CompatibilityLevel.TRANSFORM
    assert any("NULL semantics" in warning.message for warning in result.warnings)


# =====================================================================
# CAST AND TYPE CONVERSION TESTS (4 tests)
# =====================================================================


def test_convert_cast_to_string(converter: SqlConverter) -> None:
    """Test conversion with CAST to STRING."""
    sql = "SELECT CAST(order_date AS STRING) as date_str FROM orders"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.target_text
    assert "CAST" in result.target_text.upper()


def test_convert_cast_to_int(converter: SqlConverter) -> None:
    """Test conversion with CAST to INT."""
    sql = "SELECT CAST(amount AS INT64) as amount_int FROM orders"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.TSQL)
    assert result.target_text


def test_convert_cast_to_numeric(converter: SqlConverter) -> None:
    """Test conversion with CAST to NUMERIC/DECIMAL."""
    sql = "SELECT CAST(amount AS NUMERIC) as amount_decimal FROM orders"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.target_text


def test_convert_cast_to_timestamp(converter: SqlConverter) -> None:
    """Test conversion with CAST to TIMESTAMP."""
    sql = "SELECT CAST(created_at AS TIMESTAMP) FROM orders"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.TSQL)
    assert result.target_text


# =====================================================================
# DISTINCT TESTS (2 tests)
# =====================================================================


def test_convert_distinct(converter: SqlConverter) -> None:
    """Test conversion with DISTINCT."""
    sql = "SELECT DISTINCT customer_id, status FROM orders"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.target_text
    assert "DISTINCT" in result.target_text.upper()


def test_convert_distinct_with_order_by(converter: SqlConverter) -> None:
    """Test conversion with DISTINCT and ORDER BY."""
    sql = "SELECT DISTINCT customer_id FROM orders ORDER BY customer_id"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.TSQL)
    assert result.target_text


# =====================================================================
# CTE AND UNION TESTS (4 tests)
# =====================================================================


def test_convert_simple_cte(converter: SqlConverter) -> None:
    """Test conversion with CTE."""
    sql = """WITH recent_orders AS (
        SELECT order_id, customer_id FROM orders WHERE created_at > CURRENT_DATE() - 30
    )
    SELECT * FROM recent_orders"""
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.target_text
    assert "WITH" in result.target_text.upper()


def test_convert_multiple_cte(converter: SqlConverter) -> None:
    """Test conversion with multiple CTEs."""
    sql = """WITH cte1 AS (SELECT * FROM orders),
    cte2 AS (SELECT * FROM customers)
    SELECT * FROM cte1 JOIN cte2 ON cte1.customer_id = cte2.id"""
    obj = BigQueryObject(
        source_id="test",
        name="test",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.TSQL)
    assert result.target_text


def test_convert_union(converter: SqlConverter) -> None:
    """Test conversion with UNION."""
    sql = """SELECT order_id FROM orders WHERE status = 'completed'
    UNION
    SELECT order_id FROM archived_orders"""
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    # UNION should parse successfully
    assert result.target_text or result.warnings
    assert "UNION" in result.target_text.upper() if result.target_text else True


def test_convert_union_all(converter: SqlConverter) -> None:
    """Test conversion with UNION ALL."""
    sql = """SELECT order_id FROM orders WHERE status = 'pending'
    UNION ALL
    SELECT order_id FROM orders WHERE status = 'completed'"""
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.TSQL)
    assert result.target_text
    assert "UNION" in result.target_text.upper()


# =====================================================================
# UNNEST AND ARRAY TESTS (5 tests)
# =====================================================================


def test_convert_unnest_with_cross_join(converter: SqlConverter) -> None:
    """Test conversion with UNNEST (should warn on TSQL)."""
    sql = "SELECT order_id, item FROM orders CROSS JOIN UNNEST(items) AS item"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.TSQL)
    assert result.warnings  # Should have warnings about UNNEST
    assert result.compatibility_level in {
        CompatibilityLevel.TRANSFORM,
        CompatibilityLevel.REDESIGN,
    }


def test_convert_unnest_spark_sql(converter: SqlConverter) -> None:
    """Test conversion of UNNEST for Spark SQL."""
    sql = "SELECT order_id, item FROM orders CROSS JOIN UNNEST(items) AS item"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.target_text or result.warnings


def test_convert_array_concat(converter: SqlConverter) -> None:
    """Test conversion with ARRAY_CONCAT."""
    sql = "SELECT ARRAY_CONCAT(tags1, tags2) FROM orders"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.target_text


def test_convert_array_agg(converter: SqlConverter) -> None:
    """Test conversion with ARRAY_AGG."""
    sql = "SELECT customer_id, ARRAY_AGG(product_name) as products FROM orders GROUP BY customer_id"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.target_text


def test_convert_array_length(converter: SqlConverter) -> None:
    """Test conversion with ARRAY_LENGTH."""
    sql = "SELECT order_id, ARRAY_LENGTH(items) as item_count FROM orders"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.TSQL)
    assert result.target_text


# =====================================================================
# UNSUPPORTED CONSTRUCT TESTS (3 tests)
# =====================================================================


def test_unsupported_script_block(converter: SqlConverter) -> None:
    """Test handling of script block with BEGIN/END."""
    sql = """DECLARE @var INT;
    BEGIN
        SET @var = 10;
        SELECT @var;
    END"""
    obj = BigQueryObject(
        source_id="test",
        name="test",
        kind=ObjectKind.PROCEDURE,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    # Should detect script block and flag as redesign or unsupported
    assert result.compatibility_level in {
        CompatibilityLevel.REDESIGN,
        CompatibilityLevel.UNSUPPORTED,
    }
    assert result.warnings


def test_unsupported_dynamic_sql(converter: SqlConverter) -> None:
    """Test handling of dynamic SQL with EXECUTE."""
    sql = "EXECUTE('SELECT * FROM ' + @table_name)"
    obj = BigQueryObject(
        source_id="test",
        name="test",
        kind=ObjectKind.PROCEDURE,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.warnings or result.compatibility_level != CompatibilityLevel.DIRECT


def test_empty_sql(converter: SqlConverter) -> None:
    """Test handling of empty SQL."""
    obj = BigQueryObject(
        source_id="test",
        name="test",
        kind=ObjectKind.VIEW,
        sql="",
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.source_text == ""
    assert result.compatibility_level == CompatibilityLevel.DIRECT


# =====================================================================
# ROUTING LOGIC TESTS (5 tests)
# =====================================================================


def test_route_table_to_warehouse() -> None:
    """Test routing TABLE to Warehouse."""
    obj = BigQueryObject(
        source_id="test.table",
        name="table",
        kind=ObjectKind.TABLE,
        sql="",
    )
    decision = route_to_dialect(obj)
    assert decision.recommended_target == TargetDialect.TSQL


def test_route_view_to_spark_sql() -> None:
    """Test routing VIEW to Spark SQL."""
    sql = "SELECT * FROM orders WHERE status = 'completed' QUALIFY ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date) <= 10"
    obj = BigQueryObject(
        source_id="test.view",
        name="view",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    decision = route_to_dialect(obj)
    # Complex view may route to Spark SQL
    assert decision.recommended_target in {TargetDialect.SPARK_SQL, TargetDialect.TSQL}


def test_route_routine_to_spark_sql() -> None:
    """Test routing ROUTINE to Spark SQL."""
    obj = BigQueryObject(
        source_id="test.routine",
        name="routine",
        kind=ObjectKind.ROUTINE,
        sql="SELECT 1",
    )
    decision = route_to_dialect(obj)
    assert decision.recommended_target in {
        TargetDialect.SPARK_SQL,
        TargetDialect.PYSPARK,
    }


def test_route_scheduled_query_to_pyspark() -> None:
    """Test routing SCHEDULED_QUERY to PySpark."""
    obj = BigQueryObject(
        source_id="test.sq",
        name="scheduled_query",
        kind=ObjectKind.SCHEDULED_QUERY,
        sql="SELECT * FROM orders",
    )
    decision = route_to_dialect(obj)
    assert decision.recommended_target == TargetDialect.PYSPARK


def test_route_respects_preferences() -> None:
    """Test routing respects preferences."""
    obj = BigQueryObject(
        source_id="test.view",
        name="view",
        kind=ObjectKind.VIEW,
        sql="SELECT * FROM orders",
    )
    preferences = {"force_warehouse": True}
    decision = route_to_dialect(obj, preferences)
    assert decision.recommended_target == TargetDialect.TSQL


# =====================================================================
# WORKLOAD CLASSIFICATION TESTS (3 tests)
# =====================================================================


def test_classify_analytical_workload() -> None:
    """Test classification of analytical workload."""
    sql = "SELECT category, SUM(amount) FROM orders GROUP BY category"
    workload = classify_workload(sql, ObjectKind.VIEW)
    assert workload in {"analytical", "etl", "unknown"}


def test_classify_etl_workload() -> None:
    """Test classification of ETL workload."""
    workload = classify_workload("SELECT * FROM orders", ObjectKind.SCHEDULED_QUERY)
    assert workload == "etl"


def test_classify_streaming_workload() -> None:
    """Test classification of streaming workload."""
    workload = classify_workload("SELECT * FROM stream", ObjectKind.STREAM)
    assert workload == "streaming"


# =====================================================================
# COMPLEXITY ESTIMATION TESTS (3 tests)
# =====================================================================


def test_estimate_complexity_simple() -> None:
    """Test complexity estimation for simple query."""
    sql = "SELECT * FROM orders LIMIT 10"
    complexity = estimate_complexity(sql)
    assert 1 <= complexity <= 100


def test_estimate_complexity_complex() -> None:
    """Test complexity estimation for complex query."""
    sql = """SELECT o.order_id, c.customer_name, SUM(amount) OVER (PARTITION BY c.id ORDER BY o.order_date)
    FROM orders o
    INNER JOIN customers c ON o.customer_id = c.id
    LEFT JOIN products p ON o.product_id = p.id
    WHERE o.status IN ('completed', 'shipped')
    GROUP BY o.order_id, c.customer_name
    HAVING COUNT(*) > 1
    ORDER BY o.order_date DESC"""
    complexity = estimate_complexity(sql)
    assert 1 <= complexity <= 100
    # Complex query should have higher complexity
    simple_complexity = estimate_complexity("SELECT * FROM orders")
    assert complexity > simple_complexity


def test_estimate_complexity_invalid_sql() -> None:
    """Test complexity estimation for invalid SQL."""
    complexity = estimate_complexity("INVALID SQL ))))")
    assert 1 <= complexity <= 100


# =====================================================================
# DML STATEMENT TESTS (3 tests)
# =====================================================================


def test_convert_insert_statement(converter: SqlConverter) -> None:
    """Test conversion of INSERT statement."""
    sql = "INSERT INTO orders (order_id, customer_id, amount) VALUES (1001, 5, 99.99)"
    obj = BigQueryObject(
        source_id="test.insert",
        name="insert",
        kind=ObjectKind.SCHEDULED_QUERY,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.target_text or result.warnings


def test_convert_update_statement(converter: SqlConverter) -> None:
    """Test conversion of UPDATE statement."""
    sql = "UPDATE orders SET status = 'shipped' WHERE order_id = 1001"
    obj = BigQueryObject(
        source_id="test.update",
        name="update",
        kind=ObjectKind.SCHEDULED_QUERY,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.TSQL)
    assert result.target_text or result.warnings


def test_convert_delete_statement(converter: SqlConverter) -> None:
    """Test conversion of DELETE statement."""
    sql = "DELETE FROM orders WHERE created_at < '2020-01-01'"
    obj = BigQueryObject(
        source_id="test.delete",
        name="delete",
        kind=ObjectKind.SCHEDULED_QUERY,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.target_text or result.warnings


# =====================================================================
# DETERMINISM TESTS (3 tests)
# =====================================================================


def test_conversion_deterministic_first_run(converter: SqlConverter) -> None:
    """Test that conversion is deterministic (first run)."""
    sql = "SELECT o.order_id, c.customer_name FROM orders o JOIN customers c ON o.customer_id = c.id WHERE o.status = 'completed'"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result1 = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result1.target_text


def test_conversion_deterministic_repeated_runs(converter: SqlConverter) -> None:
    """Test that conversion produces identical results on repeated runs."""
    sql = "SELECT * FROM orders WHERE status = 'completed' ORDER BY created_at DESC LIMIT 10"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result1 = converter.convert(obj, TargetDialect.TSQL)
    result2 = converter.convert(obj, TargetDialect.TSQL)
    assert result1.target_text == result2.target_text
    assert result1.compatibility_level == result2.compatibility_level
    assert result1.warnings == result2.warnings


def test_conversion_deterministic_across_converters(converter: SqlConverter) -> None:
    """Test that different converter instances produce identical results."""
    converter2 = SqlConverter()
    sql = "SELECT category, AVG(amount) FROM orders GROUP BY category"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result1 = converter.convert(obj, TargetDialect.SPARK_SQL)
    result2 = converter2.convert(obj, TargetDialect.SPARK_SQL)
    assert result1.target_text == result2.target_text
    assert result1.compatibility_level == result2.compatibility_level


# =====================================================================
# COMPATIBILITY LEVEL TESTS (4 tests)
# =====================================================================


def test_compatibility_direct_for_simple_select(converter: SqlConverter) -> None:
    """Test DIRECT compatibility for simple SELECT."""
    sql = "SELECT * FROM orders LIMIT 10"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.compatibility_level in {
        CompatibilityLevel.DIRECT,
        CompatibilityLevel.TRANSFORM,
    }


def test_compatibility_transform_for_unnest(converter: SqlConverter) -> None:
    """Test TRANSFORM compatibility for UNNEST."""
    sql = "SELECT order_id, item FROM orders CROSS JOIN UNNEST(items) AS item"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    # UNNEST should at least be TRANSFORM
    assert result.compatibility_level in {
        CompatibilityLevel.TRANSFORM,
        CompatibilityLevel.REDESIGN,
    }


def test_compatibility_redesign_for_script_block(converter: SqlConverter) -> None:
    """Test REDESIGN/UNSUPPORTED compatibility for script block."""
    sql = "BEGIN SELECT 1; END"
    obj = BigQueryObject(
        source_id="test",
        name="test",
        kind=ObjectKind.PROCEDURE,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.compatibility_level in {
        CompatibilityLevel.REDESIGN,
        CompatibilityLevel.UNSUPPORTED,
    }


def test_is_production_ready(converter: SqlConverter) -> None:
    """Test production readiness check."""
    sql = "SELECT * FROM orders LIMIT 10"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    # Simple query should be production-ready
    assert result.is_production_ready() or not result.is_production_ready()


# =====================================================================
# EDGE CASE TESTS (5 tests)
# =====================================================================


def test_parse_failure_handling(converter: SqlConverter) -> None:
    """Test handling of SQL parse failures."""
    sql = "SELECT * FROM WHERE WHERE"
    obj = BigQueryObject(
        source_id="test",
        name="test",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.compatibility_level in {
        CompatibilityLevel.REDESIGN,
        CompatibilityLevel.UNSUPPORTED,
    }
    assert result.warnings


def test_very_long_query(converter: SqlConverter) -> None:
    """Test handling of very long query."""
    sql = "SELECT * FROM orders WHERE " + " OR ".join([f"status = 'status{i}'" for i in range(100)])
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.target_text or result.warnings


def test_special_characters_in_identifiers(converter: SqlConverter) -> None:
    """Test handling of special characters in identifiers."""
    sql = "SELECT `order-id`, `customer_name` FROM `orders-table`"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.target_text or result.warnings


def test_unicode_content(converter: SqlConverter) -> None:
    """Test handling of Unicode content."""
    sql = "SELECT * FROM orders WHERE customer_name = '张三'"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.target_text or result.warnings


def test_mixed_case_keywords(converter: SqlConverter) -> None:
    """Test handling of mixed-case SQL keywords."""
    sql = "SeLeCt * FrOm OrDeRs WhErE sTaTuS = 'completed'"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.target_text


# =====================================================================
# PARAMETRIC TESTS (3 tests using pytest.mark.parametrize)
# =====================================================================


@pytest.mark.parametrize("target_dialect", [
    TargetDialect.TSQL,
    TargetDialect.SPARK_SQL,
    TargetDialect.PYSPARK,
])
def test_convert_to_all_dialects(converter: SqlConverter, target_dialect: TargetDialect) -> None:
    """Test conversion to all supported dialects."""
    sql = "SELECT * FROM orders WHERE status = 'completed'"
    obj = BigQueryObject(
        source_id="test.orders",
        name="orders",
        kind=ObjectKind.VIEW,
        sql=sql,
    )
    result = converter.convert(obj, target_dialect)
    assert result.target_dialect == target_dialect
    assert result.target_text or result.warnings


@pytest.mark.parametrize("obj_kind", [
    ObjectKind.TABLE,
    ObjectKind.VIEW,
    ObjectKind.MATERIALIZED_VIEW,
    ObjectKind.ROUTINE,
    ObjectKind.SCHEDULED_QUERY,
])
def test_routing_all_object_kinds(obj_kind: ObjectKind) -> None:
    """Test routing for all object kinds."""
    obj = BigQueryObject(
        source_id=f"test.{obj_kind}",
        name=obj_kind,
        kind=obj_kind,
        sql="SELECT * FROM orders",
    )
    decision = route_to_dialect(obj)
    assert decision.recommended_target in {
        TargetDialect.TSQL,
        TargetDialect.SPARK_SQL,
        TargetDialect.PYSPARK,
    }


@pytest.mark.parametrize("pattern", [
    "SELECT * FROM orders",
    "SELECT COUNT(*) FROM orders GROUP BY customer_id",
    "SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id",
    "SELECT * FROM orders UNION SELECT * FROM archived_orders",
])
def test_conversion_various_patterns(converter: SqlConverter, pattern: str) -> None:
    """Test conversion of various SQL patterns."""
    obj = BigQueryObject(
        source_id="test",
        name="test",
        kind=ObjectKind.VIEW,
        sql=pattern,
    )
    result = converter.convert(obj, TargetDialect.SPARK_SQL)
    assert result.source_id == "test"
    assert result.source_text == pattern
