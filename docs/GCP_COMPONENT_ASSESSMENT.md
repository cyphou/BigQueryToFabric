# GCP component assessment

The canonical inventory accepts BigQuery dataset objects and top-level GCP data-platform
components. Each component receives a primary target, optional supporting targets, compatibility
level, rationale, actions, dependency wave, and manual-review flag.

| GCP source | Preferred Fabric design | Key assessment points |
|---|---|---|
| BigQuery tables/views/SQL | Lakehouse + Notebook by preference; Warehouse when SQL constraints dominate | Types, nested data, partitions, clustering, GoogleSQL AST |
| Spark/Dataproc | Lakehouse + Notebook | Runtime, libraries, GCS paths, cluster APIs, performance |
| Dataflow/Apache Beam batch | Lakehouse + Notebook + Pipeline | Transforms, state, retries, delivery semantics |
| Dataflow/Apache Beam streaming | Eventstream + Eventhouse | Windows, watermarks, late data, state, retention |
| Dataform | Lakehouse/Notebook or Warehouse + Pipeline | Dependency graph, assertions, incremental models, variables |
| Composer/Airflow | Fabric Airflow Job when already established | Operators, providers, connections, secrets, sensors, SLAs, plugins |
| GCP Workflows | Data Pipeline + Notebook | Branching, callbacks, retries, identities |
| Pub/Sub | Eventstream + Eventhouse, optional Lakehouse retention | Ordering, replay, schema, throughput, dead letters |
| Cloud Storage | OneLake Shortcut when supported, otherwise Copy | Format, locality, network, refresh and ownership |
| Looker | Semantic model + Power BI report | LookML measures, explores, relationships, access filters, dashboards |
| BQML/Vertex AI | Fabric Data Science + Lakehouse + Notebook | Features, training, registry, metrics, scoring and endpoints |
| Dataplex | Purview + Fabric domains | Catalog, glossary, lineage, classifications and quality rules |
| Cloud SQL/Spanner | SQL Database for OLTP; Lakehouse/Warehouse for analytics | Transactions, constraints, indexes, concurrency and cutover |
| IAM/policy tags/row policies | Purview, Fabric permissions and RLS | Effective-access parity; always manual review |

## Preference policy

`data_target=lakehouse` and `compute_target=notebook` influence compatible analytical workloads.
They do not override multi-table transactions, operational OLTP, real-time event requirements,
BI semantic modeling, machine-learning lifecycle requirements, or security blockers.

`preserve_airflow=true` makes an existing Composer DAG a Fabric Airflow Job candidate. Migration
still requires provider/operator compatibility and a redesign of GCP connections and secrets.