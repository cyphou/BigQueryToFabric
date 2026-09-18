# Mapping reference

| BigQuery | Fabric | Notes |
|---|---|---|
| Project | Domain/workspace topology | Governance decision, not a strict 1:1 mapping |
| Dataset | Warehouse schema or Lakehouse | Choose from workload and isolation requirements |
| Flat table | Warehouse table | Preferred for governed relational BI |
| Nested table | Lakehouse Delta table | Preserve ARRAY/STRUCT before optional normalization |
| View | Warehouse view or Spark SQL | Translate GoogleSQL and test result parity |
| Materialized view | Orchestrated Gold table | Recreate refresh semantics explicitly |
| Scheduled Query | Data Pipeline | Carry schedule, parameters, retries, and identity |
| External table | Shortcut or Copy activity | Validate shortcut source support first |
| Stream | Eventstream/Eventhouse | Define retention, schema mapping, and KQL validation |
| SQL routine | Warehouse routine | Only when T-SQL semantics are equivalent |
| JavaScript UDF | Notebook | Requires redesign and parity tests |
| Policy tags | Purview and Fabric permissions | Manual governance review required |
| Row access policy | Workspace/item permissions and RLS | No automatic 1:1 security translation |
