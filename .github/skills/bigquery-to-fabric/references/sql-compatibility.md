# GoogleSQL compatibility

Classify SQL before translation:

- Relational views and DML: prefer T-SQL for Warehouse.
- Nested data operations and UNNEST: prefer Spark SQL/PySpark in Lakehouse.
- Dynamic SQL and BigQuery scripting: redesign and validate transaction semantics.
- JavaScript UDFs: rewrite in a notebook and add parity tests.
- BQML: select an explicit Fabric Data Science replacement; never silently drop it.
- BigQuery-specific functions: maintain a reviewed compatibility recipe per function.

DAX is not an ETL target. Generate DAX only after Gold data contracts are established.

## Compatibility is never assumed

`assess_sql` delegates to the converter and reports the **worst** of the converter
verdict, the detected semantic risks, and the mapping decision. It never defaults to
`direct`. A routine whose `language` is not SQL is `redesign` and produces no converted
SQL at all.

## Constructs that transpile without raising but change meaning

A successful transpile is not evidence of a faithful translation. These are detected
and downgrade compatibility:

| Construct | Risk |
|---|---|
| Wildcard tables, `_TABLE_SUFFIX` | No target equivalent; enumerate partitions. |
| `SELECT * EXCEPT/REPLACE` | Must be expanded to an explicit column list. |
| `EXTERNAL_QUERY` | Federation must be redesigned as a Fabric connection. |
| `NET.*`, `ST_*` | No target equivalent. |
| `SAFE.` prefix, `SAFE_CAST` | Return NULL on error; the target raises instead. |
| `UNNEST` | Changes row multiplicity; verify row counts. |
| `NOT IN` | Yields no rows when the list contains NULL. |
| `MERGE INTO` | Matched-row handling differs. |
| `TABLESAMPLE`, `INTERVAL` | Sampling and interval arithmetic differ. |

## Generated Warehouse views

View bodies are converted to T-SQL. If conversion fails, or the result uses constructs
Fabric Warehouse does not support, the view body is **omitted** and the artifact is
marked invalid — the candidate conversion is emitted as `--` comments for review rather
than as deployable SQL.