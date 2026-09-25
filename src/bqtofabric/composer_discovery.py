"""Read-only Cloud Composer environment and DAG discovery."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Protocol

from .discovery import DiscoveryError, redact_mapping
from .models import BigQueryInventory, BigQueryObject, ObjectKind

_API_ROOT = "https://composer.googleapis.com/v1"
COMPOSER_READONLY_SCOPE = "https://www.googleapis.com/auth/cloud-platform.read-only"


class ComposerMetadataClient(Protocol):
    def list_environments(self, location: str) -> Iterable[dict[str, Any]]: ...

    def list_dags(self, environment_resource: str) -> Iterable[dict[str, Any]]: ...


class ComposerInventoryProvider:
    """Map Cloud Composer environments and DAGs to canonical inventory objects."""

    def __init__(self, project_id: str, client: ComposerMetadataClient) -> None:
        self.project_id = project_id
        self.client = client

    def load(self, locations: Sequence[str]) -> tuple[BigQueryObject, ...]:
        components: list[BigQueryObject] = []
        for location in locations:
            for env in self.client.list_environments(location):
                env_resource = env.get("name", "")
                components.append(self._map_environment(location, env))

                if env_resource:
                    for dag in self.client.list_dags(env_resource):
                        components.append(self._map_dag(location, env, dag))

        return tuple(sorted(components, key=lambda item: item.source_id))

    def _map_environment(self, location: str, resource: dict[str, Any]) -> BigQueryObject:
        """Map a Cloud Composer environment to a canonical object."""
        name = str(resource.get("displayName", resource.get("name", "").rsplit("/", 1)[-1]))
        if not name:
            raise DiscoveryError("Composer environment resource is missing displayName or name")

        config = resource.get("config", {})
        node_config = config.get("nodeConfig", {})

        properties: dict[str, Any] = {
            "display_name": name,
            "location": location,
            "state": resource.get("state", "UNKNOWN"),
        }

        if node_config:
            properties["machine_type"] = node_config.get("machineType", "")
            properties["node_location"] = node_config.get("location", "")

        if "dagGcsPrefix" in config:
            properties["dag_gcs_prefix"] = config["dagGcsPrefix"]

        if "airflowConfigOverrides" in config:
            # Don't expose the full overrides, just note that they exist
            properties["has_airflow_config_overrides"] = True

        if "createTime" in resource:
            properties["create_time"] = resource["createTime"]

        return BigQueryObject(
            source_id=f"{self.project_id}.composer.env.{location}.{name}",
            name=name,
            kind=ObjectKind.COMPOSER_DAG,
            discovered_from="composer_api",
            labels=redact_mapping(resource.get("labels")),
            properties=redact_mapping(properties),
        )

    def _map_dag(
        self, location: str, environment: dict[str, Any], resource: dict[str, Any]
    ) -> BigQueryObject:
        """Map a Cloud Composer DAG to a canonical object."""
        dag_id = str(resource.get("dagId", ""))
        if not dag_id:
            raise DiscoveryError("Composer DAG resource is missing dagId")

        env_name = str(environment.get("displayName", environment.get("name", "").rsplit("/", 1)[-1]))
        environment_config = environment.get("config", {})
        runtime_version = str(
            environment_config.get("softwareConfig", {}).get("imageVersion")
            or environment.get("labels", {}).get("version", "unknown")
        )

        serialized_dag = resource.get("serializedDag", {})
        task_cycle = serialized_dag.get("_task_cycle", [])
        dependencies = serialized_dag.get("dependencies", {})

        properties: dict[str, Any] = {
            "dag_id": dag_id,
            "environment": env_name,
            "location": location,
            "runtime_version": runtime_version,
            "owner": resource.get("owner", ""),
            "description": resource.get("description", ""),
            "schedule": resource.get("schedule", ""),
            "schedule_interval": resource.get("schedule", ""),
            "is_paused": resource.get("isPaused", False),
            "task_count": resource.get("taskCount", 0),
            "last_parsed_time": resource.get("lastParsedTime", ""),
        }

        # Extract operator types and analyze task dependencies
        operator_types: set[str] = set()
        task_dependencies: dict[str, list[str]] = {}

        for task in task_cycle:
            task_type = task.get("task_type", "Unknown")
            operator_types.add(task_type)

        for task_id, deps in dependencies.items():
            if deps:
                task_dependencies[task_id] = list(deps)

        connections = _extract_connections(task_cycle)
        providers = _extract_task_values(task_cycle, "provider")
        sensors = sorted(task_type for task_type in operator_types if "Sensor" in task_type)
        pools = _extract_task_values(task_cycle, "pool")
        sla = _first_task_value(task_cycle, "sla")
        retries = _first_task_value(task_cycle, "retries")
        retry_delay = _first_task_value(task_cycle, "retry_delay")

        properties["operators"] = sorted(operator_types)
        properties["connections"] = sorted(connections)
        properties["providers"] = providers
        properties["sensors"] = sensors
        properties["pools"] = pools
        properties["sla"] = sla
        properties["retries"] = retries
        properties["retry_delay"] = retry_delay
        properties["has_bigquery_operators"] = any(
            "BigQuery" in op for op in operator_types
        )
        properties["has_dataproc_operators"] = any(
            "Dataproc" in op for op in operator_types
        )
        properties["has_sensor_operators"] = any(
            "Sensor" in op for op in operator_types
        )

        # Classify DAG by operators
        dag_type = _classify_composer_dag(operator_types, dag_id)
        properties["dag_type"] = dag_type

        # Extract BigQuery dependencies from operators
        bq_dependencies = _extract_bq_dependencies(task_cycle)
        if bq_dependencies:
            properties["bq_dependencies"] = sorted(bq_dependencies)

        return BigQueryObject(
            source_id=f"{self.project_id}.composer.dag.{location}.{dag_id}",
            name=dag_id,
            kind=ObjectKind.COMPOSER_DAG,
            discovered_from="composer_api",
            dependencies=tuple(sorted(set(bq_dependencies))),
            labels=redact_mapping(resource.get("labels")),
            properties=redact_mapping(properties),
        )


def _classify_composer_dag(operator_types: set[str], dag_id: str) -> str:
    """Classify a DAG by its operators and ID."""
    # Check for explicit patterns in DAG ID
    dag_lower = dag_id.lower()
    if "train" in dag_lower or "ml" in dag_lower:
        return "ml_training"
    if "stream" in dag_lower or "kafka" in dag_lower:
        return "streaming"

    # Check for operators
    if any("Dataproc" in op or "Spark" in op for op in operator_types):
        return "spark_orchestration"
    if any("BigQuery" in op or "SQL" in op for op in operator_types):
        return "analytics"
    if any("Sensor" in op for op in operator_types):
        return "event_driven"

    return "general_orchestration"


def _extract_bq_dependencies(task_cycle: list[dict[str, Any]]) -> set[str]:
    """Extract BigQuery table references from DAG tasks."""
    dependencies: set[str] = set()

    for task in task_cycle:
        # Extract from SQL-based operators
        if "sql" in task or "query" in task:
            # Try to extract table references from SQL
            sql = task.get("sql", task.get("query", ""))
            if sql:
                # Simple pattern matching for bigquery.table()
                import re
                pattern = r'`([^`]+\.[^`]+\.[^`]+)`|bigquery\.table\([\'"`]([^\'"` ]+)[\'"`]\)'
                matches = re.findall(pattern, sql)
                for match in matches:
                    table_ref = match[0] or match[1]
                    if table_ref:
                        dependencies.add(table_ref)

        # Extract from destination table config
        if "destination_dataset_table" in task:
            dest = task["destination_dataset_table"]
            if dest:
                dependencies.add(dest)

        # Extract from BigQuery-specific fields
        if "dataset_id" in task and "table_id" in task:
            dataset = task.get("dataset_id", "")
            table = task.get("table_id", "")
            if dataset and table:
                dependencies.add(f"{dataset}.{table}")

    return dependencies


def _extract_connections(task_cycle: list[dict[str, Any]]) -> set[str]:
    """Extract declared Airflow connection names without serializing connection settings."""
    connection_keys = ("conn_id", "connection_id", "gcp_conn_id", "google_cloud_conn_id")
    connections: set[str] = set()
    for task in task_cycle:
        for key in connection_keys:
            value = task.get(key)
            if isinstance(value, str) and value:
                connections.add(value)
    return connections


def _extract_task_values(task_cycle: list[dict[str, Any]], key: str) -> list[str]:
    """Extract non-empty string task metadata deterministically."""
    values = {
        str(task[key])
        for task in task_cycle
        if isinstance(task, dict) and task.get(key) not in (None, "")
    }
    return sorted(values)


def _first_task_value(task_cycle: list[dict[str, Any]], key: str) -> Any:
    """Return the first declared task value without fabricating missing evidence."""
    values = [task[key] for task in task_cycle if isinstance(task, dict) and task.get(key) is not None]
    return values[0] if values else None


class RestComposerClient:
    """Read-only Cloud Composer REST client returning raw API resources."""

    def __init__(self, project_id: str, session: Any) -> None:
        self.project_id = project_id
        self.session = session

    def list_environments(self, location: str) -> list[dict[str, Any]]:
        url = f"{_API_ROOT}/projects/{self.project_id}/locations/{location}/environments"
        return self._paged(url)

    def list_dags(self, environment_resource: str) -> list[dict[str, Any]]:
        url = f"{_API_ROOT}/{environment_resource}/dags"
        return self._paged(url)

    def _paged(self, url: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params = {"pageToken": page_token} if page_token else None
            payload = self._get(url, params)
            items.extend(payload.get("environments", payload.get("dags", [])))
            page_token = payload.get("nextPageToken")
            if not page_token:
                return items

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.get(url, params=params, timeout=60)
        if response.status_code != 200:
            raise DiscoveryError(
                f"Composer metadata request failed with status {response.status_code}"
            )
        return response.json()


def create_composer_rest_client(project_id: str) -> RestComposerClient:
    """Build an authorized read-only Composer client from Application Default Credentials."""
    from .discovery import create_authorized_session

    return RestComposerClient(
        project_id,
        create_authorized_session((COMPOSER_READONLY_SCOPE,)),
    )


def merge_composer_components(
    inventory: BigQueryInventory, components: Iterable[BigQueryObject]
) -> BigQueryInventory:
    """Return an inventory with deterministically merged Composer components."""
    merged = tuple(sorted((*inventory.components, *components), key=lambda item: item.source_id))
    return BigQueryInventory(
        project_id=inventory.project_id,
        datasets=inventory.datasets,
        components=merged,
        schema_version=inventory.schema_version,
        metadata=inventory.metadata,
    )
