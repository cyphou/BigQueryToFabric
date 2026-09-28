"""Normalize exported GCP API list responses into canonical components (offline).

Each payload is the JSON body a user saved from the service's documented list method.
Nothing is fetched. Fields the list method does not return stay absent so assessment
reports ``EVIDENCE_MISSING`` rather than inferring them.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from .discovery import redact_mapping
from .models import BigQueryObject, ObjectKind

EXPORT_PROVENANCE = "external_payload"


def _leaf(name: Any) -> str:
    return str(name or "").rstrip("/").rsplit("/", 1)[-1]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _segment(name: Any, key: str) -> str:
    parts = str(name or "").split("/")
    return parts[parts.index(key) + 1] if key in parts and parts.index(key) + 1 < len(parts) else ""


def _pubsub(resource: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {"cmek": bool(resource.get("kmsKeyName"))}
    if resource.get("messageRetentionDuration"):
        properties["message_retention"] = str(resource["messageRetentionDuration"])
    return properties


def _workflows(resource: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {"location": _segment(resource.get("name"), "locations")}
    for source, target in (("sourceContents", "source_contents"), ("state", "state")):
        if resource.get(source):
            properties[target] = str(resource[source])
    return properties


def _gcs(resource: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for source, target in (("location", "location"), ("storageClass", "storage_class")):
        if resource.get(source):
            properties[target] = str(resource[source])
    return properties


def _dataplex(resource: dict[str, Any]) -> dict[str, Any]:
    spec = _dict(resource.get("resourceSpec"))
    properties: dict[str, Any] = {}
    lake, zone = _segment(resource.get("name"), "lakes"), _segment(resource.get("name"), "zones")
    if lake and zone:
        properties["zone"] = f"{lake}/{zone}"
    if spec.get("type"):
        properties["resource_type"] = str(spec["type"])
    return properties


def _vertex(resource: dict[str, Any]) -> dict[str, Any]:
    tasks = _dict(_dict(_dict(_dict(resource.get("pipelineSpec")).get("root")).get("dag")).get("tasks"))
    return {"pipeline_steps": sorted(tasks)} if tasks else {}


def _cloud_sql(resource: dict[str, Any]) -> dict[str, Any]:
    version = str(resource.get("databaseVersion", ""))
    properties: dict[str, Any] = {"replication": bool(resource.get("replicaNames"))}
    if "_" in version:
        engine, _, number = version.partition("_")
        properties.update({"engine": engine, "version": number})
    return properties


def _spanner(resource: dict[str, Any]) -> dict[str, Any]:
    return {"dialect": str(resource["databaseDialect"])} if resource.get("databaseDialect") else {}


def _looker(resource: dict[str, Any]) -> dict[str, Any]:
    explores = resource.get("explores")
    if not isinstance(explores, list) or not explores:
        return {}
    return {"explores": sorted(str(item.get("name")) for item in explores if isinstance(item, dict))}


# service -> (list response key, or None for a bare list; kind; property extractor)
SERVICES: dict[str, tuple[str | None, ObjectKind, Callable[[dict[str, Any]], dict[str, Any]]]] = {
    "pubsub": ("topics", ObjectKind.PUBSUB_TOPIC, _pubsub),
    "workflows": ("workflows", ObjectKind.WORKFLOW, _workflows),
    "gcs": ("items", ObjectKind.GCS_SOURCE, _gcs),
    "dataplex": ("assets", ObjectKind.DATAPLEX_ASSET, _dataplex),
    "vertex": ("pipelineJobs", ObjectKind.VERTEX_AI_PIPELINE, _vertex),
    "cloudsql": ("items", ObjectKind.CLOUD_SQL_DATABASE, _cloud_sql),
    "spanner": ("databases", ObjectKind.SPANNER_DATABASE, _spanner),
    "looker": (None, ObjectKind.LOOKER_ASSET, _looker),
}


def normalize_export(project_id: str, service: str, payload: Any) -> tuple[BigQueryObject, ...]:
    """Convert one saved list response into deterministic, redacted canonical components."""
    if service not in SERVICES:
        raise ValueError(f"Unsupported export service: {service}")
    key, kind, extract = SERVICES[service]
    resources = payload if key is None else _dict(payload).get(key, [])
    if not isinstance(resources, list):
        raise TypeError(f"{service} export must contain a list under {key or 'the root'}")

    components: list[BigQueryObject] = []
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        name = _leaf(resource.get("displayName") if service == "vertex" else resource.get("name"))
        if not name:
            continue
        properties = redact_mapping(extract(resource))
        properties["export"] = {"service": service, "resource": _leaf(resource.get("name"))}
        components.append(BigQueryObject(
            source_id=f"{project_id}.{service}.{name}",
            name=name,
            kind=kind,
            discovered_from=EXPORT_PROVENANCE,
            labels=redact_mapping(resource.get("labels")),
            properties=properties,
        ))
    return tuple(sorted(components, key=lambda item: item.source_id))


def merge_export(inventory: dict[str, Any], service: str, payload: Any) -> dict[str, Any]:
    """Add or replace components by ``source_id``; existing properties are not merged."""
    merged = deepcopy(inventory)
    components = {str(item["source_id"]): item for item in merged.get("components", [])}
    for component in normalize_export(str(merged["project_id"]), service, payload):
        record = {
            "source_id": component.source_id,
            "name": component.name,
            "kind": component.kind.value,
            "discovered_from": component.discovered_from,
            "labels": component.labels,
            "properties": component.properties,
        }
        components[component.source_id] = record
    merged["components"] = [components[key] for key in sorted(components)]
    return merged
