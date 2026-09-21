# SQL Converter Module (v0.3)

The SQL Converter module provides comprehensive GoogleSQL → T-SQL, Spark SQL, and PySpark transpilation with intelligent target routing and detailed compatibility tracking.

## Features

### 1. **Intelligent Target Routing**
Automatically selects the best Fabric target based on:
- Object kind (table, view, routine, etc.)
- SQL complexity and pattern analysis
- Workload classification (analytical, ETL, streaming, etc.)
- User preferences

**Routing Logic:**
- **Tables/Materialized Views** → Warehouse (T-SQL) for ACID guarantees and indexing
- **Complex Views** → Spark SQL for unstructured data and dynamic schema
- **Routines** → Spark SQL UDFs or PySpark functions
- **Scheduled Queries** → PySpark in Fabric Pipelines
- **Spark/Dataproc Jobs** → PySpark in Notebooks
- **Streaming** → PySpark with Eventstream

### 2. **Comprehensive SQL Pattern Detection**
Detects and tracks 30+ SQL patterns:
- Structural: SELECT, CTEs, UNION, INTERSECT, EXCEPT
- Joins: INNER/LEFT/RIGHT/FULL OUTER, multi-join
- Aggregation: GROUP BY, window functions, QUALIFY
- Array/Struct: UNNEST, array operations, struct extraction
- Functions: CASE, COALESCE, NULLIF, CAST, DISTINCT
- DML/DDL: INSERT, UPDATE, DELETE, CREATE, ALTER

### 3. **Compatibility Tracking**
Four-level compatibility assessment:
- **DIRECT**: No changes needed; production-ready
- **TRANSFORM**: One-to-one rewrite; production-ready after testing
- **REDESIGN**: Requires manual refactoring; AST may be incomplete
- **UNSUPPORTED**: Manual implementation required; no AST translation

### 4. **Actionable Warnings and Manual Steps**
Every conversion includes:
- **Warnings**: Specific issues with line/column or AST node location
- **Manual Steps**: Actionable, prioritized remediation steps
- **Rationale**: Evidence-based explanation for target selection
- **Performance Notes**: Potential implications for the target platform

### 5. **Negative Controls for Unsupported Constructs**
- Script blocks (DECLARE, BEGIN/END) → REDESIGN/UNSUPPORTED
- JavaScript/Python UDFs → UNSUPPORTED
- DML in routine bodies → TRANSFORM (with warnings)
- Federated/cross-region queries → Security review required
- Dynamic SQL (EXECUTE) → REDESIGN

## Usage

### Basic Conversion

```python
from bqtofabric.converter import SqlConverter, TargetDialect
from bqtofabric.models import BigQueryObject, ObjectKind

converter = SqlConverter()

obj = BigQueryObject(
    source_id="project.dataset.view_name",
    name="view_name",
    kind=ObjectKind.VIEW,
    sql="SELECT * FROM orders WHERE status = 'completed'"
)

result = converter.convert(obj, TargetDialect.SPARK_SQL)

print(f"Target SQL:\n{result.target_text}")
print(f"Compatibility: {result.compatibility_level}")
print(f"Warnings: {result.warnings}")
print(f"Manual Steps: {result.manual_steps}")
```

### Automatic Target Routing

```python
from bqtofabric.converter import route_to_dialect

# Automatically selects the best target
routing = route_to_dialect(obj)
print(f"Recommended Target: {routing.recommended_target}")
print(f"Alternatives: {routing.alternative_targets}")
print(f"Rationale: {routing.rationale}")

# Convert with automatic routing
result = converter.convert(obj)  # No target_dialect parameter
```

### Workload Classification

```python
from bqtofabric.converter import classify_workload, estimate_complexity

workload = classify_workload(sql_text, ObjectKind.VIEW)
complexity = estimate_complexity(sql_text)

print(f"Workload: {workload}")  # analytical, etl, streaming, etc.
print(f"Complexity: {complexity}/100")
```

## Supported Patterns

### Golden Test Coverage (50+ Tests)

#### Basic SQL (5 tests)
- Simple SELECT with WHERE, GROUP BY, ORDER BY, LIMIT
- JOINs (INNER, LEFT, RIGHT, FULL OUTER, multiple)
- ORDER BY with LIMIT

#### Window Functions (5 tests)
- ROW_NUMBER, RANK, DENSE_RANK
- SUM/AVG OVER (PARTITION BY ... ORDER BY ...)
- LAG/LEAD window functions
- QUALIFY clause handling

#### Case & Null Handling (4 tests)
- CASE expressions with multiple conditions
- COALESCE for null defaults
- NULLIF for conditional null
- IS NULL filtering

#### Type Casting (4 tests)
- CAST to STRING, INT64, NUMERIC, TIMESTAMP
- Type compatibility across dialects

#### CTEs & Set Operations (4 tests)
- Common Table Expressions (single and multiple)
- UNION and UNION ALL
- Set operations with filtering

#### Array & Struct Operations (5 tests)
- UNNEST with CROSS JOIN
- ARRAY_CONCAT, ARRAY_AGG, ARRAY_LENGTH
- Struct field extraction
- Array deduplication

#### Distinct & Advanced Patterns (2 tests)
- DISTINCT keyword
- DISTINCT with ORDER BY

#### DML Statements (3 tests)
- INSERT INTO ... VALUES
- UPDATE with WHERE
- DELETE with date filtering

#### Edge Cases (5 tests)
- Parse failure handling
- Very long queries
- Special characters in identifiers
- Unicode content
- Mixed-case SQL keywords

#### Unsupported Constructs (3 tests)
- Script blocks with BEGIN/END
- Dynamic SQL with EXECUTE
- Empty SQL

### Conversion Examples

#### Example 1: Simple SELECT (DIRECT)
```sql
-- Input (BigQuery)
SELECT customer_id, COUNT(*) as order_count
FROM orders
WHERE created_at > '2024-01-01'
GROUP BY customer_id
ORDER BY order_count DESC
LIMIT 10

-- Output (Spark SQL) - DIRECT compatibility
SELECT customer_id, COUNT(*) as order_count
FROM orders
WHERE created_at > '2024-01-01'
GROUP BY customer_id
ORDER BY order_count DESC
LIMIT 10
```

#### Example 2: UNNEST Operations (TRANSFORM)
```sql
-- Input (BigQuery)
SELECT order_id, item
FROM orders
CROSS JOIN UNNEST(items) AS item

-- Output (Spark SQL) - TRANSFORM compatibility
SELECT order_id, item
FROM orders
LATERAL VIEW explode(items) AS item

-- Output (T-SQL) - TRANSFORM compatibility with warnings
SELECT order_id, item
FROM orders
CROSS APPLY (
    SELECT value as item
    FROM STRING_SPLIT(items, ',')
) AS item
```

#### Example 3: Window Functions (DIRECT)
```sql
-- Input (BigQuery)
SELECT order_id, amount,
  SUM(amount) OVER (PARTITION BY customer_id ORDER BY order_date) as running_total
FROM orders

-- Output (T-SQL) - DIRECT compatibility
SELECT order_id, amount,
  SUM(amount) OVER (PARTITION BY customer_id ORDER BY order_date) as running_total
FROM orders
```

#### Example 4: QUALIFY Clause (TRANSFORM)
```sql
-- Input (BigQuery)
SELECT order_id, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date) as rn
FROM orders
QUALIFY rn <= 3

-- Output (Spark SQL) - TRANSFORM compatibility
-- MANUAL STEP: Rewrite QUALIFY as WHERE filter on derived table
WITH ranked_orders AS (
  SELECT order_id, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date) as rn
  FROM orders
)
SELECT order_id FROM ranked_orders WHERE rn <= 3
```

#### Example 5: Script Block (REDESIGN)
```sql
-- Input (BigQuery - Procedure)
DECLARE @var INT;
BEGIN
  SET @var = 10;
  SELECT @var;
END

-- Output: REDESIGN required
-- MANUAL STEP: Convert procedural logic to separate imperative operations
-- OR create a PySpark notebook for procedural logic
```

## API Reference

### SqlConverter Class

```python
class SqlConverter:
    """Convert GoogleSQL to target dialects."""
    
    def convert(
        self,
        obj: BigQueryObject,
        target_dialect: TargetDialect | None = None,
        preferences: dict[str, Any] | None = None,
    ) -> SqlConversion:
        """Convert a BigQuery SQL object to target dialect."""
```

### SqlConversion Data Class

```python
@dataclass(frozen=True)
class SqlConversion:
    source_id: str
    target_dialect: TargetDialect
    source_text: str
    target_text: str
    compatibility_level: CompatibilityLevel
    source_dialect: str = "bigquery"
    warnings: tuple[ConversionWarning, ...] = ()
    manual_steps: tuple[ManualStep, ...] = ()
    rationale: str = ""
    detected_patterns: tuple[str, ...] = ()
    edge_cases: tuple[str, ...] = ()
    performance_notes: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def is_production_ready(self) -> bool:
        """Check if conversion output can be deployed without manual review."""
```

### Target Routing Functions

```python
def route_to_dialect(
    obj: BigQueryObject,
    preferences: dict[str, Any] | None = None,
) -> RoutingDecision:
    """Route SQL object to recommended target dialect."""

def classify_workload(sql_text: str, obj_kind: ObjectKind) -> str:
    """Classify workload type from SQL and object metadata."""

def estimate_complexity(sql_text: str) -> int:
    """Estimate SQL complexity on 1-100 scale."""
```

## Compatibility Matrix

| Pattern | T-SQL | Spark SQL | PySpark | Notes |
|---------|-------|-----------|---------|-------|
| SELECT | ✓ Direct | ✓ Direct | ✓ Direct | Standard SQL compatible |
| JOINs | ✓ Direct | ✓ Direct | ✓ Direct | All join types supported |
| Window Functions | ✓ Direct | ✓ Direct | ✓ Transform | PySpark requires WindowSpec |
| UNNEST | ⚠ Transform | ✓ Transform | ✓ Transform | T-SQL uses CROSS APPLY |
| Struct Types | ⚠ Transform | ✓ Transform | ✓ Direct | T-SQL uses JSON or CLR types |
| QUALIFY | ⚠ Transform | ⚠ Transform | ⚠ Transform | Requires manual rewrite |
| CTEs | ✓ Direct | ✓ Direct | ✓ Direct | Standard SQL compatible |
| CASE/Coalesce | ✓ Direct | ✓ Direct | ✓ Direct | Standard SQL compatible |
| Script Blocks | ✗ Unsupported | ✗ Unsupported | ✗ Unsupported | Manual refactoring required |
| UDFs (JavaScript) | ✗ Unsupported | ✗ Unsupported | ✗ Unsupported | Manual implementation required |

## Known Limitations

1. **Script Blocks & Procedural Logic**: DECLARE, BEGIN/END, and EXECUTE statements require manual redesign. No automatic transpilation.
2. **JavaScript/Python UDFs**: UDFs in non-SQL languages must be manually reimplemented in the target environment.
3. **Dynamic SQL**: Dynamic SQL with string concatenation cannot be safely transpiled.
4. **Federated Queries**: Cross-region and federated queries require manual security review.
5. **QUALIFY Clause**: Requires manual translation to derived tables with WHERE filters.
6. **Complex Struct Operations**: Deeply nested structs may require custom handling.

## Testing

Run tests with coverage:

```bash
pytest tests/test_sql_converter.py -v --cov=src/bqtofabric/converter --cov-report=html
```

Current coverage: **82%** (80 tests, 336 statements)

## Performance Notes

- **Complexity Estimation**: O(n) tree walk where n = AST node count
- **Pattern Detection**: O(n) single pass through AST
- **Transpilation**: O(n) sqlglot internal parsing and generation
- **Typical Conversion Time**: <100ms per 1000-line SQL file

## Future Enhancements

- [ ] Extended QUALIFY support with automatic rewrite
- [ ] Advanced type mapping for STRUCT/ARRAY
- [ ] Performance optimization recommendations
- [ ] Integration with semantic model generation
- [ ] Parameterized query detection and handling
- [ ] Transactional boundary analysis
- [ ] Cost estimation for target platforms
