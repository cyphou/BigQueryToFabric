---
name: parity-evidence
description: >-
  Supply BQToFabric parity evidence so a component moves from not_run to passed.
  Use when parity is not_run or not_applicable, when PARITY_NOT_RUN or PARITY_FAILED
  appears, or when deciding what to measure in BigQuery and Fabric to prove a
  migration preserved the data. Triggers: "parity evidence", "PARITY_NOT_RUN",
  "PARITY_FAILED", "how do I prove parity", "row count comparison", "prouver la
  parité", "parity payload format".
---

# Parity evidence

Parity is **recomputed from evidence**. A declared `"status": "passed"` is never
trusted: each check is derived from its own `source`/`target` payload, and a claim
without a payload resolves to `not_run`. When a declared status contradicts the
evidence, the result records `declaredStatus` alongside the computed one.

BQToFabric does not query either platform. You measure in BigQuery and in Fabric,
then record both results in the inventory.

## Where it goes

```json
{
  "source_id": "acme.sales.orders",
  "name": "orders",
  "kind": "table",
  "properties": {
    "parity": {
      "row_count": { "source": 1048576, "target": 1048576 }
    }
  }
}
```

Parity applies to data-bearing kinds only: `table`, `external_table`, `view`,
`materialized_view`. Everything else is `not_applicable`.

## The seven checks

Any check you omit is `not_run`, and any `not_run` makes the object `not_run` overall.
All seven must have matching evidence for an object to report `passed`.

### `row_count`

```json
"row_count": { "source": 1048576, "target": 1048576 }
```

Non-negative integers. Booleans and negatives resolve to `not_run`.

### `schema`

```json
"schema": {
  "source": [{ "name": "id", "data_type": "INT64", "nullable": false, "mode": "REQUIRED" }],
  "target": [{ "name": "id", "data_type": "INT64", "nullable": false, "mode": "REQUIRED" }]
}
```

Compared by name, recursing into `fields`. Duplicate or unnamed columns resolve to
`not_run`. Differences are reported per column and field.

### `checksum`

```json
"checksum": {
  "source": { "algorithm": "sha256", "ordering": "id ASC", "value": "9f2c..." },
  "target": { "algorithm": "sha256", "ordering": "id ASC", "value": "9f2c..." }
}
```

All three fields are required on both sides. A digest computed under a different
ordering is not comparable, so `ordering` must match.

### `aggregate`

```json
"aggregate": {
  "source": { "sum_total": 81234.5, "distinct_customers": 4211 },
  "target": { "sum_total": 81234.5, "distinct_customers": 4211 }
}
```

Metrics present on one side only are reported as differences.

### `null_distribution`

```json
"null_distribution": {
  "source": { "email": { "null_count": 12, "row_count": 1000 } },
  "target": { "email": { "null_count": 12, "row_count": 1000 } }
}
```

Counts must be non-negative integers with `null_count <= row_count`, otherwise
`not_run`.

### `sample`

```json
"sample": {
  "source": { "method": "top", "ordering": "id ASC", "rows": [[1, "a"]] },
  "target": { "method": "top", "ordering": "id ASC", "rows": [[1, "a"]] }
}
```

`method` and `ordering` must match, otherwise the rows are not comparable.

### `sql_result`

```json
"sql_result": {
  "source": { "query_id": "revenue_by_region_v1", "ordering": "region ASC", "rows": [["EU", 42]] },
  "target": { "query_id": "revenue_by_region_v1", "ordering": "region ASC", "rows": [["EU", 42]] }
}
```

`query_id` identifies one approved parity query run against both platforms.

## Deliberately absent

There is no `type` check. It had no comparator, so it could only ever be
self-declared. Column data types are compared by the `schema` check.

## Practical sequencing

1. Start with `row_count` and `schema` — cheapest, and they catch most load defects.
2. Add `null_distribution` and `aggregate` to catch silent value corruption, notably
   `DATETIME` time-shifts and `SAFE_CAST` differences.
3. Add `checksum` or `sql_result` for contractual sign-off.
4. `sample` is for human review, not proof.

## Interpreting the result

- `not_run` is **not** success. It raises `PARITY_NOT_RUN` and leaves migration
  correctness unverified.
- `failed` raises `PARITY_FAILED`, sets `parity_failed` manual review, clamps the
  component score to zero, and blocks `deployment-check`.
- `declaredStatus` in the output means your asserted status disagreed with your
  evidence. Trust the evidence.

## References

- [Mapping reference](../../../docs/MAPPING_REFERENCE.md)
- [Migration runbook](../../../docs/MIGRATION_RUNBOOK.md)
