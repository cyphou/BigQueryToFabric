# Type mapping

`map_type` normalizes legacy REST names (`INTEGER`, `FLOAT`, `BOOLEAN`, `RECORD`,
`DECIMAL`, `BIGDECIMAL`) and strips `<...>` and `(...)` suffixes, so `NUMERIC(10,2)`
resolves rather than falling through to unsupported.

## Direct

BOOL, INT64, FLOAT64, NUMERIC, BYTES, DATE.

## Transform — a deliberate decision is required

| Type | Why it is not direct |
|---|---|
| STRING | Maps to `varchar(max)`; profile actual lengths before accepting it in Warehouse. |
| DATETIME | Civil time with no zone. Spark `timestamp` is instant-based and session-timezone dependent, so an unconsidered mapping silently shifts values. Choose `timestamp_ntz` or an explicit civil representation. |
| TIMESTAMP | Normalize BigQuery UTC semantics explicitly. |
| TIME | Mapped to string in Lakehouse. |
| BIGNUMERIC | BigQuery precision can exceed Fabric decimal precision. |
| JSON | Preserve raw JSON in Bronze and project typed fields in Silver. |

## Redesign

GEOGRAPHY, ARRAY, STRUCT, INTERVAL, RANGE. Preserve raw nested data in a Bronze
Lakehouse when lossless relational normalization is not proven.

## Unsupported

Any unrecognized type name. The note distinguishes a discovery gap from a genuinely
unsupported type — confirm which before acting.

Type risk folds into the owning component's readiness score and is reported as one
finding per distinct type per object, listing the affected column paths.
