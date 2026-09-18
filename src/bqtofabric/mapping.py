"""Declarative BigQuery component to Fabric workload mapping."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import BigQueryObject, ObjectKind
from .type_mapping import Compatibility


class FabricTarget(StrEnum):
    WAREHOUSE = "warehouse"
    LAKEHOUSE = "lakehouse"
    EVENTHOUSE = "eventhouse"
    SQL_DATABASE = "sql_database"
    DATA_PIPELINE = "data_pipeline"
    NOTEBOOK = "notebook"
    EVENTSTREAM = "eventstream"
    AIRFLOW_JOB = "airflow_job"
    DATAFLOW_GEN2 = "dataflow_gen2"
    ONELAKE_SHORTCUT = "onelake_shortcut"
    SEMANTIC_MODEL = "semantic_model"
    POWER_BI_REPORT = "power_bi_report"
    DATA_SCIENCE = "data_science"
    PURVIEW = "purview"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class MappingDecision:
    source_id: str
    source_kind: ObjectKind
    target: FabricTarget
    compatibility: Compatibility
    rationale: str
    supporting_targets: tuple[FabricTarget, ...] = ()
    actions: tuple[str, ...] = ()


def map_component(
    item: BigQueryObject, preferences: dict[str, object] | None = None
) -> MappingDecision:
    preferences = preferences or {}
    prefer_lakehouse = preferences.get("data_target") == "lakehouse"
    prefer_notebook = preferences.get("compute_target") == "notebook"
    if item.kind in {ObjectKind.STREAM, ObjectKind.PUBSUB_TOPIC}:
        return MappingDecision(
            item.source_id,
            item.kind,
            FabricTarget.EVENTHOUSE,
            Compatibility.TRANSFORM,
            "High-frequency event workloads fit Eventstream and Eventhouse.",
            (FabricTarget.EVENTSTREAM, FabricTarget.LAKEHOUSE),
            ("Define event source, retention, ingestion mapping, and KQL validation.",),
        )
    if item.kind is ObjectKind.SCHEDULED_QUERY:
        return MappingDecision(
            item.source_id,
            item.kind,
            FabricTarget.DATA_PIPELINE,
            Compatibility.TRANSFORM,
            "Scheduled Queries map to a Fabric Data Pipeline schedule and SQL/notebook activity.",
            (FabricTarget.NOTEBOOK,),
            ("Translate schedule, parameters, retries, and service identity.",),
        )
    if item.kind is ObjectKind.BIGQUERY_JOB:
        return MappingDecision(
            item.source_id,
            item.kind,
            FabricTarget.DATA_PIPELINE,
            Compatibility.TRANSFORM,
            "BigQuery jobs map to Fabric Pipeline activities using the native BigQuery connector.",
            (FabricTarget.NOTEBOOK, FabricTarget.WAREHOUSE),
            ("Preserve job type, SQL or transfer configuration, disposition, location, and retry evidence.",),
        )
    if item.kind in {ObjectKind.EXTERNAL_TABLE, ObjectKind.GCS_SOURCE}:
        return MappingDecision(
            item.source_id,
            item.kind,
            FabricTarget.LAKEHOUSE,
            Compatibility.TRANSFORM,
            "External data should use a supported OneLake Shortcut or a pipeline Copy activity.",
            (FabricTarget.ONELAKE_SHORTCUT, FabricTarget.DATA_PIPELINE),
            ("Validate source format and Shortcut support before selecting zero-copy access.",),
        )
    if item.kind in {ObjectKind.SPARK_JOB, ObjectKind.DATAPROC_JOB}:
        return MappingDecision(
            item.source_id,
            item.kind,
            FabricTarget.LAKEHOUSE,
            Compatibility.TRANSFORM,
            "Spark and Dataproc workloads map naturally to Fabric Lakehouse compute.",
            (FabricTarget.NOTEBOOK,),
            ("Replace GCS paths and cluster-specific APIs; validate Spark runtime compatibility.",),
        )
    if item.kind is ObjectKind.DATAFLOW_JOB:
        streaming = bool(item.properties.get("streaming", False))
        portable = bool(item.properties.get("portable", False))
        connector_compatible = bool(item.properties.get("connector_compatible", False))
        if not streaming and portable and connector_compatible:
            return MappingDecision(
                item.source_id,
                item.kind,
                FabricTarget.DATAFLOW_GEN2,
                Compatibility.TRANSFORM,
                "Portable batch Beam with compatible connectors is a candidate for Dataflow Gen2.",
                (FabricTarget.DATA_PIPELINE, FabricTarget.LAKEHOUSE),
                ("Validate Beam transforms, schema projection, retries, and connector parity.",),
            )
        return MappingDecision(
            item.source_id,
            item.kind,
            FabricTarget.EVENTHOUSE if streaming else FabricTarget.LAKEHOUSE,
            Compatibility.REDESIGN,
            "Apache Beam pipelines require redesign as Eventstream or Fabric notebook pipelines.",
            (FabricTarget.EVENTSTREAM,) if streaming else (FabricTarget.NOTEBOOK, FabricTarget.DATA_PIPELINE),
            ("Recreate windowing, triggers, state, retries, and delivery semantics.",),
        )
    if item.kind is ObjectKind.COMPOSER_DAG:
        preserve = bool(preferences.get("preserve_airflow", True))
        unsupported_operators = item.properties.get("unsupported_operators", [])
        custom_plugins = bool(item.properties.get("custom_plugins", False))
        if unsupported_operators or custom_plugins:
            return MappingDecision(
                item.source_id,
                item.kind,
                FabricTarget.DATA_PIPELINE,
                Compatibility.REDESIGN,
                "Composer evidence includes operators or plugins that cannot be assumed reusable in Fabric Airflow.",
                (FabricTarget.NOTEBOOK, FabricTarget.LAKEHOUSE),
                ("Replace unsupported operators and custom plugins; preserve schedule, secrets, and retries.",),
            )
        return MappingDecision(
            item.source_id,
            item.kind,
            FabricTarget.AIRFLOW_JOB if preserve else FabricTarget.DATA_PIPELINE,
            Compatibility.TRANSFORM,
            "Existing Airflow DAGs remain strong candidates when operators and dependencies are reusable.",
            (FabricTarget.LAKEHOUSE, FabricTarget.NOTEBOOK),
            ("Inventory operators, connections, secrets, sensors, SLAs, and custom plugins.",),
        )
    if item.kind is ObjectKind.WORKFLOW:
        return MappingDecision(
            item.source_id,
            item.kind,
            FabricTarget.DATA_PIPELINE,
            Compatibility.TRANSFORM,
            "GCP Workflows map to parameterized Fabric Data Pipelines.",
            (FabricTarget.NOTEBOOK,),
            ("Translate branching, retries, callbacks, and identity boundaries.",),
        )
    if item.kind is ObjectKind.DATAFORM_WORKFLOW:
        target = FabricTarget.LAKEHOUSE if prefer_lakehouse else FabricTarget.WAREHOUSE
        assertions = bool(item.properties.get("assertions", False))
        incremental = bool(item.properties.get("incremental", False))
        actions = ["Preserve assertions, incremental semantics, variables, and dependency order."]
        if assertions:
            actions.append("Translate Dataform assertions into explicit Fabric data-quality checks.")
        if incremental:
            actions.append("Validate incremental watermark and merge semantics against Delta or Warehouse behavior.")
        return MappingDecision(
            item.source_id,
            item.kind,
            target,
            Compatibility.TRANSFORM,
            "Dataform dependency graphs map to SQL/notebook transformations orchestrated by pipelines.",
            (FabricTarget.NOTEBOOK, FabricTarget.DATA_PIPELINE),
            tuple(actions),
        )
    if item.kind is ObjectKind.LOOKER_ASSET:
        return MappingDecision(
            item.source_id,
            item.kind,
            FabricTarget.SEMANTIC_MODEL,
            Compatibility.REDESIGN,
            "LookML models and explores require redesign as a Power BI semantic model.",
            (FabricTarget.POWER_BI_REPORT,),
            ("Map measures, relationships, access filters, explores, and dashboard intent.",),
        )
    if item.kind is ObjectKind.BQML_MODEL:
        return MappingDecision(
            item.source_id,
            item.kind,
            FabricTarget.DATA_SCIENCE,
            Compatibility.REDESIGN,
            "BQML models require a Fabric Data Science training and scoring design.",
            (FabricTarget.LAKEHOUSE, FabricTarget.NOTEBOOK),
            ("Capture model type, features, evaluation metrics, registry, and scoring consumers.",),
        )
    if item.kind is ObjectKind.VERTEX_AI_PIPELINE:
        return MappingDecision(
            item.source_id,
            item.kind,
            FabricTarget.DATA_SCIENCE,
            Compatibility.REDESIGN,
            "Vertex AI pipelines require a Fabric Data Science experiment and orchestration redesign.",
            (FabricTarget.LAKEHOUSE, FabricTarget.NOTEBOOK, FabricTarget.DATA_PIPELINE),
            ("Map features, models, environments, registry, endpoints, metrics, and schedules.",),
        )
    if item.kind is ObjectKind.DATAPLEX_ASSET:
        return MappingDecision(
            item.source_id,
            item.kind,
            FabricTarget.PURVIEW,
            Compatibility.TRANSFORM,
            "Dataplex catalog and governance metadata map to Purview and Fabric domains.",
            (FabricTarget.LAKEHOUSE,),
            ("Map glossary, classifications, ownership, lineage, and data-quality rules.",),
        )
    if item.kind in {ObjectKind.CLOUD_SQL_DATABASE, ObjectKind.SPANNER_DATABASE}:
        return MappingDecision(
            item.source_id,
            item.kind,
            FabricTarget.SQL_DATABASE,
            Compatibility.REDESIGN if item.kind is ObjectKind.SPANNER_DATABASE else Compatibility.TRANSFORM,
            "Operational relational databases require an OLTP target, not an analytical Lakehouse default.",
            (FabricTarget.LAKEHOUSE, FabricTarget.DATA_PIPELINE),
            ("Assess transactions, constraints, indexes, concurrency, replication, and application cutover.",),
        )
    if item.kind is ObjectKind.SECURITY_POLICY:
        return MappingDecision(
            item.source_id,
            item.kind,
            FabricTarget.MANUAL,
            Compatibility.UNSUPPORTED,
            "Security policies have no safe automatic one-to-one migration.",
            (FabricTarget.PURVIEW, FabricTarget.SEMANTIC_MODEL),
            ("Recreate policy tags, permissions, authorized views, and RLS; validate effective access.",),
        )
    if item.kind is ObjectKind.CONNECTION:
        return MappingDecision(
            item.source_id,
            item.kind,
            FabricTarget.DATA_PIPELINE,
            Compatibility.TRANSFORM,
            "Recreate external connections with Fabric connection objects and managed identities.",
            (),
            ("Never copy secret values; map identity and network requirements.",),
        )
    if item.kind is ObjectKind.MATERIALIZED_VIEW:
        return MappingDecision(
            item.source_id,
            item.kind,
            FabricTarget.WAREHOUSE,
            Compatibility.REDESIGN,
            "Materialize the result as a curated Gold table orchestrated by a pipeline.",
            (FabricTarget.DATA_PIPELINE,),
            ("Define refresh cadence and parity checks.",),
        )
    if item.kind in {ObjectKind.ROUTINE, ObjectKind.PROCEDURE}:
        javascript = str(item.properties.get("language", "SQL")).upper() == "JAVASCRIPT"
        return MappingDecision(
            item.source_id,
            item.kind,
            FabricTarget.LAKEHOUSE if javascript else FabricTarget.WAREHOUSE,
            Compatibility.REDESIGN if javascript else Compatibility.TRANSFORM,
            "JavaScript routines require notebook redesign. SQL routines may translate to T-SQL.",
            (FabricTarget.NOTEBOOK,) if javascript else (),
            ("Review side effects, dynamic SQL, temporary objects, and exception handling.",),
        )
    if item.kind in {ObjectKind.VIEW, ObjectKind.SQL_SCRIPT}:
        target = FabricTarget.LAKEHOUSE if prefer_lakehouse else FabricTarget.WAREHOUSE
        return MappingDecision(
            item.source_id,
            item.kind,
            target,
            Compatibility.TRANSFORM,
            "Translate GoogleSQL to Spark SQL/Notebook or a governed T-SQL object according to the target.",
            (FabricTarget.NOTEBOOK, FabricTarget.DATA_PIPELINE) if prefer_notebook else (),
        )
    nested = any(column.mode == "REPEATED" or column.data_type in {"ARRAY", "STRUCT", "JSON"}
                 for column in item.columns)
    target = FabricTarget.LAKEHOUSE if nested or prefer_lakehouse else FabricTarget.WAREHOUSE
    actions: list[str] = []
    if item.partition_field or item.clustering_fields:
        actions.append("Reassess partitioning and clustering; Fabric physical design is not equivalent.")
    return MappingDecision(
        item.source_id,
        item.kind,
        target,
        Compatibility.TRANSFORM if nested else Compatibility.DIRECT,
        "Nested or semi-structured schemas favor Delta and Spark. Flat relational tables favor Warehouse.",
        (FabricTarget.NOTEBOOK,) if target is FabricTarget.LAKEHOUSE and prefer_notebook else (),
        tuple(actions),
    )
