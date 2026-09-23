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

## How the strategy is selected

Strategy selection is weighted by mapping compatibility rather than by target identity. Each
component contributes its compatibility weight to the candidate target it was mapped to:

| Compatibility | Weight |
|---|---|
| `direct` | 3 |
| `transform` | 2 |
| `redesign` | 1 |
| `unsupported` | 0 |

A portfolio of `direct` Warehouse mappings therefore outweighs an equally sized portfolio of
`redesign` Lakehouse mappings, instead of both counting as one vote each.

Additional rules:

- The `data_target` preference signal is symmetric: stating `warehouse` and stating `lakehouse`
  apply the same magnitude of advisory weight in opposite directions. Preferences never override
  stronger technical evidence.
- Multi-table transactions **pin** Warehouse as a hard constraint, not as a weighted signal. No
  accumulation of other evidence can displace it.
- When two candidates tie, the tie-break is recorded as an explicit signal in the strategy output
  rather than resolved silently.
- `scores` reports only the three candidate primary targets, so a reader is not asked to interpret
  scores for roles that were never in contention.

The selected strategy is a review recommendation derived from inventory evidence. It does not
establish that the target will perform, secure, or behave equivalently at runtime.
