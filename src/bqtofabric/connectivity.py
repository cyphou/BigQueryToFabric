"""Offline GCP-to-Fabric connection transcode contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from .mapping import map_component
from .models import BigQueryObject
from .security import CredentialScanner
from .type_mapping import Compatibility


@dataclass(frozen=True, slots=True)
class ConnectionTranscode:
    """Reviewable connection mapping with no credential-bearing fields."""

    source_id: str
    reference_name: str
    target_type: str
    compatibility: str
    status: str
    redaction_status: str
    findings: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_TARGET_TYPES = {
    "CLOUD_SQL": {"POSTGRES": "PostgreSQL", "MYSQL": "MySQL"},
    "AWS": "Amazon S3",
    "AZURE": "Azure resource",
    "CLOUD_RESOURCE": "Google Cloud Storage",
    "SPARK": "Lakehouse",
    "CLOUD_SPANNER": "manual",
}


def _reference_name(source_id: str) -> str:
    digest = hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:12]
    return f"gcp-connection-{digest}"


def transcode_connection(item: BigQueryObject) -> ConnectionTranscode:
    """Create a deterministic safe connection candidate from canonical metadata."""
    decision = map_component(item)
    properties = json.dumps(item.properties, sort_keys=True, default=str)
    credential_findings = CredentialScanner().scan(properties)
    connection_type = str(item.properties.get("connection_type", "UNKNOWN")).upper()
    engine = str(item.properties.get("database_engine", "")).upper()
    target_type = _TARGET_TYPES.get(connection_type, {}).get(
        engine,
        _TARGET_TYPES.get(connection_type, connection_type.lower()),
    )
    findings = tuple(
        sorted({f"credential detected: {finding.finding_type}" for finding in credential_findings})
    )
    if decision.compatibility is Compatibility.REDESIGN:
        findings = tuple(sorted((*findings, decision.rationale)))
    status = (
        "manual_review"
        if findings or decision.compatibility is Compatibility.REDESIGN
        else "ready_for_review"
    )
    return ConnectionTranscode(
        source_id=item.source_id,
        reference_name=_reference_name(item.source_id),
        target_type=str(target_type),
        compatibility=decision.compatibility.value,
        status=status,
        redaction_status="blocked" if credential_findings else "clear",
        findings=findings,
        actions=decision.actions,
    )
