# GoogleSQL compatibility

Classify SQL before translation:

- Relational views and DML: prefer T-SQL for Warehouse.
- Nested data operations and UNNEST: prefer Spark SQL/PySpark in Lakehouse.
- Dynamic SQL and BigQuery scripting: redesign and validate transaction semantics.
- JavaScript UDFs: rewrite in a notebook and add parity tests.
- BQML: select an explicit Fabric Data Science replacement; never silently drop it.
- BigQuery-specific functions: maintain a reviewed compatibility recipe per function.

DAX is not an ETL target. Generate DAX only after Gold data contracts are established.