# Fabric target decision guide

Choose **Warehouse** when data is structured, developers use SQL, consumers need relational
BI, or workloads require DML and multi-table transactions.

Choose **Lakehouse** when workloads use Spark, Delta, medallion layers, unstructured or nested
data, data science, or flexible schema evolution. Its SQL analytics endpoint is read-only for
table data and is not a replacement for full Warehouse DML.

Choose **Eventhouse** for streaming events, operational telemetry, high-cardinality time-series,
geospatial event analytics, and low-latency interactive exploration.

Choose **SQL database in Fabric** only for genuine operational OLTP behavior, concurrency, and
relational integrity. BigQuery analytics workloads do not normally map there.

Use a **hybrid** architecture when Lakehouse Bronze/Silver processing feeds a governed Warehouse
Gold model, or when streaming data lands in Eventhouse and is exposed to downstream analytics.
