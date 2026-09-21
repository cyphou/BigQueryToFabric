"""Read-only Dataform repository, workflow, and compilation discovery."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from .discovery import DiscoveryError, redact_mapping
from .models import BigQueryInventory, BigQueryObject, ObjectKind

_API_ROOT = "https://dataform.googleapis.com/v1beta1"
DATAFORM_READONLY_SCOPE = "https://www.googleapis.com/auth/cloud-platform.read-only"


class DataformMetadataClient(Protocol):
    def list_repositories(self, location: str) -> Iterable[dict[str, Any]]: ...

    def list_workflows(self, repository_resource: str) -> Iterable[dict[str, Any]]: ...

    def list_compilation_results(self, repository_resource: str) -> Iterable[dict[str, Any]]: ...

    def get_compilation_result(self, compilation_result_resource: str) -> dict[str, Any]: ...


class DataformInventoryProvider:
    """Map Dataform repositories, workflows, and compiled DAGs to canonical objects."""

    def __init__(self, project_id: str, client: DataformMetadataClient, location: str = "us-central1") -> None:
        self.project_id = project_id
        self.client = client
        self.location = location

    def load(self) -> tuple[BigQueryObject, ...]:
        components: list[BigQueryObject] = []

        # Discover repositories
        for repo in self.client.list_repositories(self.location):
            components.append(self._map_repository(repo))

            repo_name = repo.get("name", "")
            if not repo_name:
                continue

            # Discover workflows and compilation results for each repository
            for workflow in self.client.list_workflows(repo_name):
                components.append(self._map_workflow(workflow))

            # Discover compiled DAGs and their targets
            for comp_result in self.client.list_compilation_results(repo_name):
                components.extend(self._map_compiled_result(comp_result))

        return tuple(sorted(components, key=lambda item: item.source_id))

    def _map_repository(self, resource: dict[str, Any]) -> BigQueryObject:
        """Map a Dataform repository to a canonical object."""
        name = str(resource.get("name", "")).rsplit("/", 1)[-1]
        if not name:
            raise DiscoveryError("Dataform repository resource is missing name")

        properties: dict[str, Any] = {
            "display_name": resource.get("displayName", name),
            "location": self.location,
        }

        return BigQueryObject(
            source_id=f"{self.project_id}.dataform.repository.{name}",
            name=name,
            kind=ObjectKind.DATAFORM_WORKFLOW,  # Repository is a container for workflows
            discovered_from="dataform_api",
            labels=redact_mapping(resource.get("labels")),
            properties=redact_mapping(properties),
        )

    def _map_workflow(self, resource: dict[str, Any]) -> BigQueryObject:
        """Map a Dataform workflow to a canonical object."""
        name = str(resource.get("displayName", resource.get("name", "").rsplit("/", 1)[-1]))
        if not name:
            raise DiscoveryError("Dataform workflow resource is missing displayName or name")

        compilation_status = resource.get("compilationStatus", {})
        state = compilation_status.get("compilationState", "UNKNOWN")

        properties: dict[str, Any] = {
            "state": resource.get("state", "UNKNOWN"),
            "compilation_state": state,
            "location": self.location,
        }

        if resource.get("releaseConfig"):
            properties["release_config"] = resource["releaseConfig"]

        return BigQueryObject(
            source_id=f"{self.project_id}.dataform.workflow.{name}",
            name=name,
            kind=ObjectKind.DATAFORM_WORKFLOW,
            discovered_from="dataform_api",
            properties=redact_mapping(properties),
        )

    def _map_compiled_result(
        self, comp_result: dict[str, Any]
    ) -> list[BigQueryObject]:
        """Map compiled Dataform targets (tables, views, assertions) to canonical objects."""
        components: list[BigQueryObject] = []

        # Get the full compilation result with targets and edges
        comp_name = comp_result.get("name", "")
        if not comp_name:
            return components

        try:
            full_result = self.client.get_compilation_result(comp_name)
        except DiscoveryError:
            # If we can't fetch the full result, skip processing targets
            return components

        data_source = full_result.get("dataSourceA", {})
        targets = data_source.get("targets", [])
        edges = data_source.get("edges", [])

        # Build mappings of target names to edges
        # target_edges: edges where the target is the targetTarget (incoming edges)
        # source_edges: edges where the target is the sourceTarget (outgoing edges)
        target_edges: dict[str, list[dict[str, Any]]] = {}
        source_edges: dict[str, list[dict[str, Any]]] = {}
        
        for edge in edges:
            target = edge.get("targetTarget", {})
            source = edge.get("sourceTarget", {})
            target_key = _make_target_key(target)
            source_key = _make_target_key(source)
            
            if target_key not in target_edges:
                target_edges[target_key] = []
            target_edges[target_key].append(edge)
            
            if source_key not in source_edges:
                source_edges[source_key] = []
            source_edges[source_key].append(edge)

        # Map each target to a canonical object
        for target in targets:
            target_type = target.get("relationType", "TABLE").upper()
            target_key = _make_target_key(target)

            # Skip non-table types for now; assertions are tracked via edges
            if target_type == "ASSERTION":
                # Create an assertion object but mark it for quality review
                components.append(self._map_assertion(target, target_edges.get(target_key, [])))
            else:
                components.append(self._map_target(target, target_edges.get(target_key, []), source_edges.get(target_key, [])))

        return components

    def _map_target(self, target: dict[str, Any], incoming_edges: list[dict[str, Any]], outgoing_edges: list[dict[str, Any]]) -> BigQueryObject:
        """Map a Dataform compiled target (table/view) to a canonical object."""
        database = target.get("database", "")
        schema = target.get("schema", "")
        name = target.get("name", "")
        source_id = f"{self.project_id}.dataform.target.{schema}.{name}"

        # Infer object kind
        is_view = target.get("isView", False)
        is_incremental = target.get("incremental", False)
        kind = ObjectKind.VIEW if is_view else ObjectKind.TABLE

        # Extract dependencies from incoming edges (where this target is the target)
        dependencies: list[str] = []
        for edge in incoming_edges:
            source_target = edge.get("sourceTarget", {})
            source_key = f"{self.project_id}.dataform.target.{source_target.get('schema', '')}.{source_target.get('name', '')}"
            if source_key not in dependencies:
                dependencies.append(source_key)

        # Check if there are assertions testing this target (outgoing edges with ASSERTION type)
        assertion_edges = [e for e in outgoing_edges if e.get("edgeType") == "ASSERTION"]

        properties: dict[str, Any] = {
            "database": database,
            "schema": schema,
            "description": target.get("description", ""),
            "disabled": target.get("disabled", False),
            "incremental": is_incremental,
            "has_assertions": len(assertion_edges) > 0,
        }

        return BigQueryObject(
            source_id=source_id,
            name=name,
            kind=kind,
            discovered_from="dataform_api",
            dependencies=tuple(sorted(set(dependencies))),
            properties=redact_mapping(properties),
        )

    def _map_assertion(self, target: dict[str, Any], edges: list[dict[str, Any]]) -> BigQueryObject:
        """Map a Dataform assertion to a canonical object."""
        database = target.get("database", "")
        schema = target.get("schema", "")
        name = target.get("name", "")
        source_id = f"{self.project_id}.dataform.assertion.{schema}.{name}"

        # Extract dependencies (which tables this assertion tests)
        dependencies: list[str] = []
        for edge in edges:
            source_target = edge.get("sourceTarget", {})
            source_key = f"{self.project_id}.dataform.target.{source_target.get('schema', '')}.{source_target.get('name', '')}"
            if source_key not in dependencies:
                dependencies.append(source_key)

        properties: dict[str, Any] = {
            "database": database,
            "schema": schema,
            "description": target.get("description", ""),
            "disabled": target.get("disabled", False),
            "assertion_type": "quality_check",
            "requires_review": True,  # Assertions should be reviewed
        }

        return BigQueryObject(
            source_id=source_id,
            name=name,
            kind=ObjectKind.DATAFORM_WORKFLOW,  # Assertions are modeled as workflow components
            discovered_from="dataform_api",
            dependencies=tuple(sorted(set(dependencies))),
            properties=redact_mapping(properties),
        )


def _make_target_key(target: dict[str, Any]) -> str:
    """Create a unique key for a target object."""
    schema = target.get("schema", "unknown")
    name = target.get("name", "unknown")
    return f"{schema}.{name}"


class RestDataformClient:
    """Read-only Dataform REST client returning raw API resources."""

    def __init__(self, project_id: str, location: str, session: Any) -> None:
        self.project_id = project_id
        self.location = location
        self.session = session

    def list_repositories(self, location: str) -> list[dict[str, Any]]:
        url = f"{_API_ROOT}/projects/{self.project_id}/locations/{location}/repositories"
        return self._paged(url)

    def list_workflows(self, repository_resource: str) -> list[dict[str, Any]]:
        url = f"{_API_ROOT}/{repository_resource}/workflows"
        return self._paged(url)

    def list_compilation_results(self, repository_resource: str) -> list[dict[str, Any]]:
        url = f"{_API_ROOT}/{repository_resource}/compilationResults"
        return self._paged(url)

    def get_compilation_result(self, compilation_result_resource: str) -> dict[str, Any]:
        url = f"{_API_ROOT}/{compilation_result_resource}"
        return self._get(url)

    def _paged(self, url: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params = {"pageToken": page_token} if page_token else None
            payload = self._get(url, params)
            items.extend(payload.get("repositories", payload.get("workflows", payload.get("compilationResults", []))))
            page_token = payload.get("nextPageToken")
            if not page_token:
                return items

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.get(url, params=params, timeout=60)
        if response.status_code != 200:
            raise DiscoveryError(
                f"Dataform metadata request failed with status {response.status_code}"
            )
        return response.json()


def create_dataform_rest_client(project_id: str, location: str = "us-central1") -> RestDataformClient:
    """Build an authorized read-only Dataform client from Application Default Credentials."""
    from .discovery import create_authorized_session

    return RestDataformClient(
        project_id,
        location,
        create_authorized_session((DATAFORM_READONLY_SCOPE,)),
    )


def merge_dataform_components(
    inventory: BigQueryInventory, components: Iterable[BigQueryObject]
) -> BigQueryInventory:
    """Return an inventory with deterministically merged Dataform components."""
    merged = tuple(sorted((*inventory.components, *components), key=lambda item: item.source_id))
    return BigQueryInventory(
        project_id=inventory.project_id,
        datasets=inventory.datasets,
        components=merged,
        schema_version=inventory.schema_version,
        metadata=inventory.metadata,
    )
