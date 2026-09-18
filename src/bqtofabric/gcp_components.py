"""Normalize external GCP resource payloads into canonical components."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .discovery import redact_mapping
from .models import BigQueryObject, ObjectKind

_EXTERNAL_KINDS = {kind.value: kind for kind in ObjectKind}


def normalize_external_components(
    project_id: str, resources: Iterable[dict[str, Any]]
) -> tuple[BigQueryObject, ...]:
    """Convert sanitized GCP adapter payloads into deterministic canonical objects."""
    components: list[BigQueryObject] = []
    for resource in resources:
        kind_name = str(resource.get("kind", ""))
        kind = _EXTERNAL_KINDS.get(kind_name)
        if kind is None:
            continue
        name = str(resource.get("name", resource.get("id", "")))
        source_id = str(resource.get("source_id", f"{project_id}.{kind_name}.{name}"))
        components.append(BigQueryObject(
            source_id=source_id,
            name=name,
            kind=kind,
            discovered_from="external_payload",
            dependencies=tuple(sorted(str(item) for item in resource.get("dependencies", []))),
            labels=redact_mapping(resource.get("labels")),
            properties=redact_mapping(resource.get("properties", {})),
        ))
    return tuple(sorted(components, key=lambda item: item.source_id))
