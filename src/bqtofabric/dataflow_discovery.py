"""Read-only regional Dataflow discovery."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Protocol

from .discovery import DiscoveryError, redact_mapping
from .models import BigQueryInventory, BigQueryObject, ObjectKind

_API_ROOT = "https://dataflow.googleapis.com/v1b3"
DATAFLOW_READONLY_SCOPE = "https://www.googleapis.com/auth/cloud-platform.read-only"


class DataflowMetadataClient(Protocol):
    def list_jobs(self, region: str) -> Iterable[dict[str, Any]]: ...


class DataflowInventoryProvider:
    """Map regional Dataflow job payloads to canonical inventory objects."""

    def __init__(self, project_id: str, client: DataflowMetadataClient) -> None:
        self.project_id = project_id
        self.client = client

    def load(self, regions: Sequence[str]) -> tuple[BigQueryObject, ...]:
        jobs = [
            self._map_job(region, resource)
            for region in regions
            for resource in self.client.list_jobs(region)
        ]
        return tuple(sorted(jobs, key=lambda item: item.source_id))

    def _map_job(self, region: str, resource: dict[str, Any]) -> BigQueryObject:
        job_id = str(resource.get("id", ""))
        if not job_id:
            raise DiscoveryError("Dataflow job resource is missing id")
        name = str(resource.get("name") or job_id)
        properties: dict[str, Any] = {
            "job_id": job_id,
            "region": region,
        }
        if "currentState" in resource:
            properties["state"] = resource["currentState"]
        if "type" in resource:
            properties["type"] = resource["type"]
            properties["streaming"] = resource["type"] == "JOB_TYPE_STREAMING"
        if "createTime" in resource:
            properties["create_time"] = resource["createTime"]
        if "currentStateTime" in resource:
            properties["update_time"] = resource["currentStateTime"]
        for field_name in (
            "environment",
            "pipelineDescription",
            "transformNameMapping",
            "portable",
            "connector_compatible",
        ):
            if field_name in resource:
                properties[field_name] = resource[field_name]
        return BigQueryObject(
            source_id=f"{self.project_id}.dataflow.{region}.{job_id}",
            name=name,
            kind=ObjectKind.DATAFLOW_JOB,
            discovered_from="dataflow_api",
            labels=redact_mapping(resource.get("labels")),
            properties=redact_mapping(properties),
        )


class RestDataflowClient:
    """Read-only regional Dataflow REST client returning raw API resources."""

    def __init__(self, project_id: str, session: Any) -> None:
        self.project_id = project_id
        self.session = session

    def list_jobs(self, region: str) -> list[dict[str, Any]]:
        url = f"{_API_ROOT}/projects/{self.project_id}/locations/{region}/jobs"
        return self._paged(url)

    def _paged(self, url: str) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params = {"pageToken": page_token} if page_token else None
            payload = self._get(url, params)
            jobs.extend(payload.get("jobs", []))
            page_token = payload.get("nextPageToken")
            if not page_token:
                return jobs

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.get(url, params=params, timeout=60)
        if response.status_code != 200:
            raise DiscoveryError(
                f"Dataflow metadata request failed with status {response.status_code}"
            )
        return response.json()


def create_dataflow_rest_client(project_id: str) -> RestDataflowClient:
    """Build an authorized read-only Dataflow client from Application Default Credentials."""
    from .discovery import create_authorized_session

    return RestDataflowClient(
        project_id,
        create_authorized_session((DATAFLOW_READONLY_SCOPE,)),
    )


def merge_dataflow_jobs(
    inventory: BigQueryInventory, jobs: Iterable[BigQueryObject]
) -> BigQueryInventory:
    """Return an inventory with deterministically merged Dataflow components."""
    components = tuple(sorted((*inventory.components, *jobs), key=lambda item: item.source_id))
    return BigQueryInventory(
        project_id=inventory.project_id,
        datasets=inventory.datasets,
        components=components,
        schema_version=inventory.schema_version,
        metadata=inventory.metadata,
    )