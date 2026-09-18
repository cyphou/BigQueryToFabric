"""Canonical, cloud-independent BigQuery inventory model."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class ObjectKind(StrEnum):
    TABLE = "table"
    VIEW = "view"
    MATERIALIZED_VIEW = "materialized_view"
    EXTERNAL_TABLE = "external_table"
    ROUTINE = "routine"
    PROCEDURE = "procedure"
    SCHEDULED_QUERY = "scheduled_query"
    STREAM = "stream"
    SQL_SCRIPT = "sql_script"
    SPARK_JOB = "spark_job"
    DATAFLOW_JOB = "dataflow_job"
    DATAPROC_JOB = "dataproc_job"
    DATAFORM_WORKFLOW = "dataform_workflow"
    COMPOSER_DAG = "composer_dag"
    WORKFLOW = "workflow"
    PUBSUB_TOPIC = "pubsub_topic"
    GCS_SOURCE = "gcs_source"
    LOOKER_ASSET = "looker_asset"
    BQML_MODEL = "bqml_model"
    SECURITY_POLICY = "security_policy"
    CONNECTION = "connection"
    DATAPLEX_ASSET = "dataplex_asset"
    VERTEX_AI_PIPELINE = "vertex_ai_pipeline"
    CLOUD_SQL_DATABASE = "cloud_sql_database"
    SPANNER_DATABASE = "spanner_database"


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    data_type: str
    nullable: bool = True
    mode: str = "NULLABLE"
    description: str | None = None
    fields: tuple[Column, ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Column:
        return cls(
            name=str(value["name"]),
            data_type=str(value["data_type"]).upper(),
            nullable=bool(value.get("nullable", True)),
            mode=str(value.get("mode", "NULLABLE")).upper(),
            description=value.get("description"),
            fields=tuple(cls.from_dict(item) for item in value.get("fields", [])),
        )


@dataclass(frozen=True, slots=True)
class BigQueryObject:
    source_id: str
    name: str
    kind: ObjectKind
    dataset: str = ""
    columns: tuple[Column, ...] = ()
    sql: str | None = None
    dependencies: tuple[str, ...] = ()
    partition_field: str | None = None
    clustering_fields: tuple[str, ...] = ()
    size_bytes: int | None = None
    labels: dict[str, str] = field(default_factory=dict)
    properties: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> BigQueryObject:
        return cls(
            source_id=str(value["source_id"]),
            name=str(value["name"]),
            kind=ObjectKind(value["kind"]),
            dataset=str(value.get("dataset", "")),
            columns=tuple(Column.from_dict(item) for item in value.get("columns", [])),
            sql=value.get("sql"),
            dependencies=tuple(value.get("dependencies", [])),
            partition_field=value.get("partition_field"),
            clustering_fields=tuple(value.get("clustering_fields", [])),
            size_bytes=value.get("size_bytes"),
            labels=dict(value.get("labels", {})),
            properties=dict(value.get("properties", {})),
        )


@dataclass(frozen=True, slots=True)
class Dataset:
    source_id: str
    name: str
    location: str
    objects: tuple[BigQueryObject, ...] = ()
    labels: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Dataset:
        return cls(
            source_id=str(value["source_id"]),
            name=str(value["name"]),
            location=str(value.get("location", "unknown")),
            objects=tuple(BigQueryObject.from_dict(item) for item in value.get("objects", [])),
            labels=dict(value.get("labels", {})),
        )


@dataclass(frozen=True, slots=True)
class BigQueryInventory:
    project_id: str
    datasets: tuple[Dataset, ...]
    components: tuple[BigQueryObject, ...] = ()
    schema_version: str = "1.0"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> BigQueryInventory:
        return cls(
            project_id=str(value["project_id"]),
            datasets=tuple(Dataset.from_dict(item) for item in value.get("datasets", [])),
            components=tuple(BigQueryObject.from_dict(item) for item in value.get("components", [])),
            schema_version=str(value.get("schema_version", "1.0")),
            metadata=dict(value.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def objects(self) -> tuple[BigQueryObject, ...]:
        dataset_objects = tuple(item for dataset in self.datasets for item in dataset.objects)
        return dataset_objects + self.components
