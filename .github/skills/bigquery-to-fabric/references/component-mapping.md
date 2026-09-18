# Component mapping

| BigQuery component | Preferred Fabric target | Migration mode |
|---|---|---|
| Flat analytical table | Warehouse | Direct or transform |
| ARRAY/STRUCT/JSON table | Lakehouse Delta | Transform or redesign |
| View | Warehouse T-SQL view or Spark SQL | Transform |
| Materialized view | Orchestrated Gold table | Redesign |
| Scheduled Query | Data Pipeline plus SQL/notebook activity | Transform |
| External GCS table | OneLake Shortcut when supported, otherwise Copy activity | Transform |
| Streaming events | Eventstream and Eventhouse | Transform |
| SQL UDF/procedure | Warehouse routine when compatible | Transform |
| JavaScript UDF | Fabric notebook | Redesign |
| BQML model | Fabric Data Science replacement | Manual redesign |
| Policy tags/row policies | Purview, Fabric permissions, semantic-model RLS | Manual review |
| Spark/Dataproc job | Lakehouse + Notebook | Transform |
| Dataflow/Beam batch | Lakehouse + Notebook + Data Pipeline | Redesign |
| Dataflow/Beam streaming | Eventstream + Eventhouse | Redesign |
| Dataform workflow | Lakehouse/Notebook or Warehouse + Data Pipeline | Transform |
| Composer DAG | Fabric Airflow Job + Lakehouse/Notebook | Transform |
| GCP Workflow | Data Pipeline + Notebook | Transform |
| Pub/Sub topic | Eventstream + Eventhouse, optionally Lakehouse | Transform |
| GCS source | OneLake Shortcut when supported, otherwise Copy | Transform |
| Looker/Looker Studio | Semantic model + Power BI report | Redesign |
| Vertex AI pipeline | Fabric Data Science + Lakehouse + Notebook | Redesign |
| Dataplex asset | Purview + Fabric domain/Lakehouse | Transform |
| Cloud SQL | SQL Database + Pipeline/Lakehouse analytics | Transform |
| Spanner | SQL Database or application redesign | Redesign |
