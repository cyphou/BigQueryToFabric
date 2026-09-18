"""Read-only Google Cloud discovery that produces canonical inventories."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Protocol

import sqlglot
from sqlglot import expressions as exp
from sqlglot.errors import ParseError

from .models import BigQueryInventory, BigQueryObject, Column, Dataset, ObjectKind

REDACTED = "[redacted]"
READONLY_SCOPE = "https://www.googleapis.com/auth/bigquery.readonly"
_API_ROOT = "https://bigquery.googleapis.com/bigquery/v2"
_TRANSFER_API_ROOT = "https://bigquerydatatransfer.googleapis.com/v1"
_CONNECTION_API_ROOT = "https://bigqueryconnection.googleapis.com/v1"

_SECRET_KEY_MARKERS = (
    "secret",
    "token",
    "password",
    "passwd",
    "credential",
    "private_key",
    "privatekey",
    "api_key",
    "apikey",
    "access_key",
    "accesskey",
    "authorization",
    "signature",
)
_SECRET_VALUE_MARKERS = ("-----begin", "bearer ")

# The REST API still reports legacy type names that the type mapper does not know.
_LEGACY_TYPES = {
    "INTEGER": "INT64",
    "FLOAT": "FLOAT64",
    "BOOLEAN": "BOOL",
    "RECORD": "STRUCT",
}

_TABLE_KINDS = {
    "TABLE": ObjectKind.TABLE,
    "VIEW": ObjectKind.VIEW,
    "MATERIALIZED_VIEW": ObjectKind.MATERIALIZED_VIEW,
    "EXTERNAL": ObjectKind.EXTERNAL_TABLE,
    "SNAPSHOT": ObjectKind.TABLE,
}


class DiscoveryError(RuntimeError):
    """Raised when discovery fails without exposing provider response payloads."""


class BigQueryMetadataClient(Protocol):
    def list_datasets(self) -> Iterable[dict[str, Any]]: ...

    def list_jobs(self) -> Iterable[dict[str, Any]]: ...

    def list_transfer_configs(self) -> Iterable[dict[str, Any]]: ...

    def list_connections(self) -> Iterable[dict[str, Any]]: ...

    def list_tables(self, dataset_id: str) -> Iterable[dict[str, Any]]: ...

    def list_routines(self, dataset_id: str) -> Iterable[dict[str, Any]]: ...

    def list_models(self, dataset_id: str) -> Iterable[dict[str, Any]]: ...


def redact(key: str, value: Any) -> Any:
    """Replace credential-like keys and values with a non-secret marker."""
    if _is_secret_key(key):
        return REDACTED
    if isinstance(value, dict):
        return {name: redact(name, item) for name, item in sorted(value.items())}
    if isinstance(value, list):
        return [redact(key, item) for item in value]
    if isinstance(value, str) and _is_secret_value(value):
        return REDACTED
    return value


def redact_mapping(value: dict[str, Any] | None) -> dict[str, Any]:
    if not value:
        return {}
    return {name: redact(name, item) for name, item in sorted(value.items())}


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SECRET_KEY_MARKERS)


def _is_secret_value(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _SECRET_VALUE_MARKERS)


class GoogleCloudInventoryProvider:
    """Build a canonical inventory from read-only BigQuery metadata."""

    def __init__(
        self,
        project_id: str,
        client: BigQueryMetadataClient,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.project_id = project_id
        self.client = client
        self.metadata = dict(metadata or {})

    def load(self) -> BigQueryInventory:
        datasets = [self._map_dataset(resource) for resource in self.client.list_datasets()]
        components = [self._map_job(resource) for resource in self.client.list_jobs()]
        components.extend(
            self._map_transfer_config(resource) for resource in self.client.list_transfer_configs()
        )
        components.extend(
            self._map_connection(resource) for resource in self.client.list_connections()
        )
        return BigQueryInventory(
            project_id=self.project_id,
            datasets=tuple(sorted(datasets, key=lambda item: item.source_id)),
            components=tuple(sorted(components, key=lambda item: item.source_id)),
            schema_version="1.1",
            metadata=dict(sorted(self.metadata.items())),
        )

    def _map_dataset(self, resource: dict[str, Any]) -> Dataset:
        reference = resource.get("datasetReference", {})
        dataset_id = str(reference.get("datasetId", ""))
        if not dataset_id:
            raise DiscoveryError("Dataset resource is missing datasetReference.datasetId")
        objects: list[BigQueryObject] = []
        objects.extend(
            self._map_table(item, dataset_id) for item in self.client.list_tables(dataset_id)
        )
        objects.extend(
            self._map_routine(item, dataset_id) for item in self.client.list_routines(dataset_id)
        )
        objects.extend(
            self._map_model(item, dataset_id) for item in self.client.list_models(dataset_id)
        )
        objects.extend(
            self._map_access_policy(item, dataset_id, index)
            for index, item in enumerate(resource.get("access", []))
        )
        return Dataset(
            source_id=f"{self.project_id}.{dataset_id}",
            name=dataset_id,
            location=str(resource.get("location", "unknown")),
            objects=tuple(sorted(objects, key=lambda item: item.source_id)),
            labels=redact_mapping(resource.get("labels")),
        )

    def _map_table(self, resource: dict[str, Any], dataset_id: str) -> BigQueryObject:
        reference = resource.get("tableReference", {})
        name = str(reference.get("tableId", ""))
        kind = _TABLE_KINDS.get(str(resource.get("type", "TABLE")).upper(), ObjectKind.TABLE)
        sql = _view_query(resource)
        dependencies, unresolved = _sql_dependencies(sql, self.project_id, dataset_id)
        properties: dict[str, Any] = {}
        if unresolved:
            properties["unresolved_references"] = list(unresolved)
        if resource.get("externalDataConfiguration"):
            properties["source_format"] = resource["externalDataConfiguration"].get("sourceFormat")
        size = resource.get("numBytes")
        return BigQueryObject(
            source_id=f"{self.project_id}.{dataset_id}.{name}",
            name=name,
            kind=kind,
            dataset=dataset_id,
            columns=_map_columns(resource.get("schema", {}).get("fields", [])),
            sql=sql,
            dependencies=dependencies,
            partition_field=_partition_field(resource),
            clustering_fields=tuple(resource.get("clustering", {}).get("fields", [])),
            size_bytes=int(size) if size is not None else None,
            labels=redact_mapping(resource.get("labels")),
            properties=redact_mapping(properties),
        )

    def _map_routine(self, resource: dict[str, Any], dataset_id: str) -> BigQueryObject:
        reference = resource.get("routineReference", {})
        name = str(reference.get("routineId", ""))
        routine_type = str(resource.get("routineType", "")).upper()
        kind = ObjectKind.PROCEDURE if routine_type == "PROCEDURE" else ObjectKind.ROUTINE
        sql = resource.get("definitionBody")
        dependencies, unresolved = _sql_dependencies(sql, self.project_id, dataset_id)
        properties: dict[str, Any] = {"language": str(resource.get("language", "SQL")).upper()}
        if unresolved:
            properties["unresolved_references"] = list(unresolved)
        return BigQueryObject(
            source_id=f"{self.project_id}.{dataset_id}.{name}",
            name=name,
            kind=kind,
            dataset=dataset_id,
            sql=sql,
            dependencies=dependencies,
            properties=redact_mapping(properties),
        )

    def _map_model(self, resource: dict[str, Any], dataset_id: str) -> BigQueryObject:
        reference = resource.get("modelReference", {})
        name = str(reference.get("modelId", ""))
        return BigQueryObject(
            source_id=f"{self.project_id}.{dataset_id}.{name}",
            name=name,
            kind=ObjectKind.BQML_MODEL,
            dataset=dataset_id,
            labels=redact_mapping(resource.get("labels")),
            properties=redact_mapping({"model_type": resource.get("modelType", "UNKNOWN")}),
        )

    def _map_job(self, resource: dict[str, Any]) -> BigQueryObject:
        reference = resource.get("jobReference", {})
        job_id = str(reference.get("jobId") or resource.get("id", ""))
        configuration = resource.get("configuration", {})
        query = configuration.get("query", {})
        sql = query.get("query")
        dependencies, unresolved = _sql_dependencies(sql, self.project_id, "")
        properties = {
            "job_type": next(
                (key for key in ("query", "load", "copy", "extract") if key in configuration),
                "unknown",
            ),
            "state": resource.get("status", {}).get("state", "UNKNOWN"),
            "location": reference.get("location"),
            "priority": query.get("priority"),
            "write_disposition": query.get("writeDisposition"),
            "create_disposition": query.get("createDisposition"),
        }
        if unresolved:
            properties["unresolved_references"] = list(unresolved)
        return BigQueryObject(
            source_id=f"{self.project_id}.jobs.{job_id}",
            name=job_id,
            kind=ObjectKind.BIGQUERY_JOB,
            sql=sql,
            dependencies=dependencies,
            properties=redact_mapping(properties),
        )

    def _map_transfer_config(self, resource: dict[str, Any]) -> BigQueryObject:
        resource_name = str(resource.get("name", ""))
        name = str(resource.get("displayName") or resource_name.rsplit("/", 1)[-1])
        params = resource.get("params", {})
        sql = params.get("query")
        dependencies, unresolved = _sql_dependencies(sql, self.project_id, "")
        properties = {
            "schedule": resource.get("schedule"),
            "state": resource.get("state", "UNKNOWN"),
            "data_source_id": resource.get("dataSourceId"),
            "owner_email": resource.get("ownerInfo", {}).get("email"),
            "transfer_config_name": resource_name,
            "params": params,
        }
        if unresolved:
            properties["unresolved_references"] = list(unresolved)
        return BigQueryObject(
            source_id=f"{self.project_id}.scheduled_queries.{name}",
            name=name,
            kind=ObjectKind.SCHEDULED_QUERY,
            sql=sql,
            dependencies=dependencies,
            properties=redact_mapping(properties),
        )

    def _map_connection(self, resource: dict[str, Any]) -> BigQueryObject:
        resource_name = str(resource.get("name", ""))
        name = resource_name.rsplit("/", 1)[-1]
        credential = resource.get("hasCredential", {})
        properties = {
            "connection_type": credential.get("connectionType", "UNKNOWN"),
            "friendly_name": resource.get("friendlyName"),
            "description": resource.get("description"),
            "location": resource_name.split("/locations/")[-1].split("/", 1)[0],
            "auth_configured": bool(credential),
        }
        return BigQueryObject(
            source_id=f"{self.project_id}.connections.{name}",
            name=name,
            kind=ObjectKind.CONNECTION,
            properties=redact_mapping(properties),
        )

    def _map_access_policy(
        self, resource: dict[str, Any], dataset_id: str, index: int
    ) -> BigQueryObject:
        policy_type = next(
            (
                key
                for key in ("role", "userByEmail", "groupByEmail", "specialGroup", "domain")
                if key in resource
            ),
            "unknown",
        )
        return BigQueryObject(
            source_id=f"{self.project_id}.{dataset_id}.access.{index:04d}",
            name=f"{dataset_id}-access-{index:04d}",
            kind=ObjectKind.SECURITY_POLICY,
            dataset=dataset_id,
            properties=redact_mapping(
                {
                    "policy_type": policy_type,
                    "evidence_scope": "dataset_access_entry",
                    **resource,
                }
            ),
        )


def _map_columns(fields: Sequence[dict[str, Any]]) -> tuple[Column, ...]:
    columns: list[Column] = []
    for field in fields:
        mode = str(field.get("mode", "NULLABLE")).upper()
        data_type = str(field.get("type", "STRING")).upper()
        columns.append(
            Column(
                name=str(field.get("name", "")),
                data_type=_LEGACY_TYPES.get(data_type, data_type),
                nullable=mode != "REQUIRED",
                mode=mode,
                description=field.get("description"),
                fields=_map_columns(field.get("fields", [])),
            )
        )
    return tuple(columns)


def _view_query(resource: dict[str, Any]) -> str | None:
    for key in ("view", "materializedView"):
        query = resource.get(key, {}).get("query")
        if query:
            return str(query)
    return None


def _partition_field(resource: dict[str, Any]) -> str | None:
    for key in ("timePartitioning", "rangePartitioning"):
        field = resource.get(key, {}).get("field")
        if field:
            return str(field)
    # Ingestion-time partitioning exposes no column, so record the pseudo column explicitly.
    if resource.get("timePartitioning"):
        return "_PARTITIONTIME"
    return None


def _sql_dependencies(
    sql: str | None, project_id: str, dataset_id: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not sql:
        return (), ()
    try:
        statements = sqlglot.parse(sql, read="bigquery")
    except ParseError:
        return (), ("SQL could not be parsed; references require manual review.",)

    references: set[str] = set()
    for statement in statements:
        if statement is None:
            continue
        for table in statement.find_all(exp.Table):
            if not table.name:
                continue
            catalog = table.catalog or project_id
            database = table.db or dataset_id
            references.add(f"{catalog}.{database}.{table.name}")
    return tuple(sorted(references)), ()


class RestBigQueryClient:
    """Read-only BigQuery REST client returning raw API resources."""

    def __init__(self, project_id: str, session: Any) -> None:
        self.project_id = project_id
        self.session = session

    def list_datasets(self) -> list[dict[str, Any]]:
        listed = self._paged(f"{_API_ROOT}/projects/{self.project_id}/datasets", "datasets")
        return [
            self._get(
                f"{_API_ROOT}/projects/{self.project_id}/datasets/"
                f"{item['datasetReference']['datasetId']}"
            )
            for item in listed
        ]

    def list_jobs(self) -> list[dict[str, Any]]:
        base = f"{_API_ROOT}/projects/{self.project_id}/jobs"
        return self._paged(base, "jobs")

    def list_transfer_configs(self) -> list[dict[str, Any]]:
        base = f"{_TRANSFER_API_ROOT}/projects/{self.project_id}/locations/-/transferConfigs"
        return self._paged(base, "transferConfigs")

    def list_connections(self) -> list[dict[str, Any]]:
        base = f"{_CONNECTION_API_ROOT}/projects/{self.project_id}/locations/-/connections"
        return self._paged(base, "connections")

    def list_tables(self, dataset_id: str) -> list[dict[str, Any]]:
        base = f"{_API_ROOT}/projects/{self.project_id}/datasets/{dataset_id}/tables"
        return [self._get(f"{base}/{item['tableReference']['tableId']}") for item in
                self._paged(base, "tables")]

    def list_routines(self, dataset_id: str) -> list[dict[str, Any]]:
        base = f"{_API_ROOT}/projects/{self.project_id}/datasets/{dataset_id}/routines"
        return self._paged(base, "routines")

    def list_models(self, dataset_id: str) -> list[dict[str, Any]]:
        base = f"{_API_ROOT}/projects/{self.project_id}/datasets/{dataset_id}/models"
        return self._paged(base, "models")

    def _paged(self, url: str, key: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params = {"pageToken": page_token} if page_token else None
            payload = self._get(url, params)
            items.extend(payload.get(key, []))
            page_token = payload.get("nextPageToken")
            if not page_token:
                return items

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.get(url, params=params, timeout=60)
        if response.status_code != 200:
            # The response body may echo request headers, so it is never surfaced.
            raise DiscoveryError(f"BigQuery metadata request failed with status {response.status_code}")
        return response.json()


def create_rest_client(project_id: str) -> RestBigQueryClient:
    """Build an authorized read-only client from Application Default Credentials."""
    try:
        import google.auth  # pyright: ignore[reportMissingImports]
        from google.auth.transport.requests import (  # pyright: ignore[reportMissingImports]
            AuthorizedSession,
        )
    except ImportError as error:
        raise DiscoveryError(
            'Live discovery requires the optional dependencies: pip install "bqtofabric[gcp]"'
        ) from error

    try:
        credentials, _ = google.auth.default(scopes=[READONLY_SCOPE])
    except Exception as error:  # noqa: BLE001 - provider errors may embed credential details
        raise DiscoveryError(
            f"Could not obtain read-only Google credentials ({type(error).__name__})."
        ) from None
    return RestBigQueryClient(project_id, AuthorizedSession(credentials))
