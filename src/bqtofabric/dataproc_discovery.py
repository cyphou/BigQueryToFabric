"""Read-only regional Dataproc cluster and job discovery."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Protocol

from .discovery import DiscoveryError, redact_mapping
from .models import BigQueryInventory, BigQueryObject, ObjectKind

_API_ROOT = "https://dataproc.googleapis.com/v1"
DATAPROC_READONLY_SCOPE = "https://www.googleapis.com/auth/cloud-platform.read-only"


class DataprocMetadataClient(Protocol):
    def list_clusters(self, region: str) -> Iterable[dict[str, Any]]: ...

    def list_jobs(self, region: str) -> Iterable[dict[str, Any]]: ...


class DataprocInventoryProvider:
    """Map regional Dataproc cluster and job payloads to canonical inventory objects."""

    def __init__(self, project_id: str, client: DataprocMetadataClient) -> None:
        self.project_id = project_id
        self.client = client

    def load(self, regions: Sequence[str]) -> tuple[BigQueryObject, ...]:
        components: list[BigQueryObject] = []
        for region in regions:
            clusters = list(self.client.list_clusters(region))
            cluster_runtime_versions = {
                str(cluster.get("clusterName", "")): _cluster_runtime_version(cluster)
                for cluster in clusters
            }
            components.extend(self._map_cluster(region, resource) for resource in clusters)
            components.extend(
                self._map_job(region, resource, cluster_runtime_versions)
                for resource in self.client.list_jobs(region)
            )
        return tuple(sorted(components, key=lambda item: item.source_id))

    def _map_cluster(self, region: str, resource: dict[str, Any]) -> BigQueryObject:
        """Map a Dataproc cluster to a canonical object."""
        name = str(resource.get("clusterName", ""))
        if not name:
            raise DiscoveryError("Dataproc cluster resource is missing clusterName")

        config = resource.get("config", {})
        properties: dict[str, Any] = {
            "cluster_name": name,
            "region": region,
        }

        # Extract machine configuration
        master_config = config.get("masterConfig", {})
        if master_config:
            properties["master_machine_type"] = master_config.get("machineTypeUri", "")

        worker_config = config.get("workerConfig", {})
        if worker_config:
            properties["worker_machine_type"] = worker_config.get("machineTypeUri", "")
            properties["worker_count"] = worker_config.get("numInstances", 0)

        # Extract autoscaling configuration
        autoscaling_config = config.get("autoscalingConfig", {})
        if autoscaling_config:
            properties["autoscaling_min_instances"] = autoscaling_config.get("minInstances")
            properties["autoscaling_max_instances"] = autoscaling_config.get("maxInstances")

        # Extract staging bucket
        staging_bucket = config.get("stagingBucket", "")
        if staging_bucket:
            properties["staging_bucket"] = staging_bucket

        # Extract status
        status = resource.get("status", {})
        if status:
            properties["state"] = status.get("state", "UNKNOWN")

        # Extract timestamps
        if "createTime" in resource:
            properties["create_time"] = resource["createTime"]

        return BigQueryObject(
            source_id=f"{self.project_id}.dataproc.{region}.{name}",
            name=name,
            kind=ObjectKind.SPARK_JOB,  # Clusters are modeled as SPARK_JOB for now
            discovered_from="dataproc_api",
            labels=redact_mapping(resource.get("labels")),
            properties=redact_mapping(properties),
        )

    def _map_job(
        self,
        region: str,
        resource: dict[str, Any],
        cluster_runtime_versions: dict[str, str],
    ) -> BigQueryObject:
        """Map a Dataproc job to a canonical object."""
        reference = resource.get("reference", {})
        job_id = str(reference.get("jobId", ""))
        if not job_id:
            raise DiscoveryError("Dataproc job resource is missing jobId")

        properties: dict[str, Any] = {
            "job_id": job_id,
            "region": region,
        }

        # Determine job type and runtime
        job_type = "unknown"
        runtime = "unknown"
        if "pysparkJob" in resource:
            job_type = "pyspark"
            runtime = "pyspark"
            pysparkjob = resource["pysparkJob"]
            if "mainPythonFileUri" in pysparkjob:
                properties["main_file"] = pysparkjob["mainPythonFileUri"]
            if "args" in pysparkjob:
                properties["args_count"] = len(pysparkjob["args"])
        elif "sparkJob" in resource:
            job_type = "spark"
            runtime = "spark_java"
            sparkjob = resource["sparkJob"]
            if "mainJarFileUri" in sparkjob:
                properties["main_file"] = sparkjob["mainJarFileUri"]
            if "args" in sparkjob:
                properties["args_count"] = len(sparkjob["args"])
        elif "sparkSqlJob" in resource:
            job_type = "spark_sql"
            runtime = "spark_sql"
            sparksqljob = resource["sparkSqlJob"]
            if "queryList" in sparksqljob:
                properties["query_count"] = len(sparksqljob["queryList"].get("queries", []))
        elif "hadoopJob" in resource:
            job_type = "hadoop"
            runtime = "hadoop"
        elif "hiveJob" in resource:
            job_type = "hive"
            runtime = "hive"
        elif "pigJob" in resource:
            job_type = "pig"
            runtime = "pig"

        properties["job_type"] = job_type
        properties["runtime"] = runtime
        properties["language"] = _job_language(job_type)

        # Classify workload type based on job type and context
        workload_type = _classify_dataproc_workload(job_type, resource)
        properties["workload_type"] = workload_type

        # Extract cluster placement
        placement = resource.get("placement", {})
        if placement:
            properties["cluster_name"] = placement.get("clusterName", "")
        properties["runtime_version"] = cluster_runtime_versions.get(
            properties.get("cluster_name", ""), "unknown"
        )

        # Extract status
        status = resource.get("status", {})
        if status:
            properties["state"] = status.get("state", "UNKNOWN")
            if "stateStartTime" in status:
                properties["state_start_time"] = status["stateStartTime"]

        # Extract driver controls file URI
        if "driverControlsFilesUri" in resource:
            properties["driver_controls_files_uri"] = resource["driverControlsFilesUri"]

        return BigQueryObject(
            source_id=f"{self.project_id}.dataproc.job.{region}.{job_id}",
            name=job_id,
            kind=ObjectKind.DATAPROC_JOB,
            discovered_from="dataproc_api",
            labels=redact_mapping(resource.get("labels")),
            properties=redact_mapping(properties),
        )


def _classify_dataproc_workload(job_type: str, resource: dict[str, Any]) -> str:
    """Classify Dataproc job into workload categories: data_engineering, ml_training, streaming."""
    labels = resource.get("labels", {})

    # Check explicit labels
    if labels.get("workload_type"):
        return labels.get("workload_type", "unknown")
    if labels.get("workflow") == "streaming":
        return "streaming"

    # Infer from job type
    if job_type == "pyspark":
        # Could be training or ETL; default to data_engineering
        if "train" in resource.get("reference", {}).get("jobId", "").lower():
            return "ml_training"
        return "data_engineering"
    elif job_type in ("spark_sql", "spark") or job_type == "hadoop":
        return "data_engineering"

    return "unknown"


def _cluster_runtime_version(resource: dict[str, Any]) -> str:
    """Read Dataproc image version when the API payload includes it."""
    config = resource.get("config", {})
    return str(config.get("softwareConfig", {}).get("imageVersion", "unknown"))


def _job_language(job_type: str) -> str:
    """Map Dataproc job types to canonical source-language evidence."""
    language_by_job_type = {
        "pyspark": "python",
        "spark_sql": "sql",
        "spark": "unknown",
        "hadoop": "unknown",
        "hive": "sql",
        "pig": "pig",
    }
    return language_by_job_type.get(job_type, "unknown")


class RestDataprocClient:
    """Read-only regional Dataproc REST client returning raw API resources."""

    def __init__(self, project_id: str, session: Any) -> None:
        self.project_id = project_id
        self.session = session

    def list_clusters(self, region: str) -> list[dict[str, Any]]:
        url = f"{_API_ROOT}/projects/{self.project_id}/regions/{region}/clusters"
        return self._paged(url)

    def list_jobs(self, region: str) -> list[dict[str, Any]]:
        url = f"{_API_ROOT}/projects/{self.project_id}/regions/{region}/jobs"
        return self._paged(url)

    def _paged(self, url: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params = {"pageToken": page_token} if page_token else None
            payload = self._get(url, params)
            items.extend(payload.get("clusters", payload.get("jobs", [])))
            page_token = payload.get("nextPageToken")
            if not page_token:
                return items

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.get(url, params=params, timeout=60)
        if response.status_code != 200:
            raise DiscoveryError(
                f"Dataproc metadata request failed with status {response.status_code}"
            )
        return response.json()


def create_dataproc_rest_client(project_id: str) -> RestDataprocClient:
    """Build an authorized read-only Dataproc client from Application Default Credentials."""
    from .discovery import create_authorized_session

    return RestDataprocClient(
        project_id,
        create_authorized_session((DATAPROC_READONLY_SCOPE,)),
    )


def merge_dataproc_components(
    inventory: BigQueryInventory, components: Iterable[BigQueryObject]
) -> BigQueryInventory:
    """Return an inventory with deterministically merged Dataproc components."""
    merged = tuple(sorted((*inventory.components, *components), key=lambda item: item.source_id))
    return BigQueryInventory(
        project_id=inventory.project_id,
        datasets=inventory.datasets,
        components=merged,
        schema_version=inventory.schema_version,
        metadata=inventory.metadata,
    )
