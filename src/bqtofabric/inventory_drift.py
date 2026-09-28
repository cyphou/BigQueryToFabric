"""Compare two canonical inventories offline and report drift as reviewable findings.

Used to diff a live discovery run against the committed offline fixture: drift is
reported, never silently absorbed into either side.
"""

from __future__ import annotations

from typing import Any

from .models import BigQueryInventory, BigQueryObject


def inventory_drift(baseline: BigQueryInventory, current: BigQueryInventory) -> dict[str, Any]:
    """Return added, removed, and changed components with the fields that differ."""
    before = {item.source_id: item for item in baseline.objects()}
    after = {item.source_id: item for item in current.objects()}
    changed = []
    for source_id in sorted(set(before) & set(after)):
        fields = _changed_fields(before[source_id], after[source_id])
        if fields:
            changed.append({"sourceId": source_id, "fields": fields})
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    return {
        "baselineProject": baseline.project_id,
        "currentProject": current.project_id,
        "added": added,
        "removed": removed,
        "changed": changed,
        "status": "no_drift" if not (added or removed or changed) else "drift_detected",
    }


def _changed_fields(before: BigQueryObject, after: BigQueryObject) -> list[str]:
    fields = [
        name
        for name in ("kind", "discovered_from", "columns", "sql", "dependencies", "partition_field",
                     "clustering_fields", "size_bytes", "labels")
        if getattr(before, name) != getattr(after, name)
    ]
    keys = set(before.properties) | set(after.properties)
    fields.extend(
        f"properties.{key}"
        for key in sorted(keys)
        if before.properties.get(key) != after.properties.get(key)
    )
    return fields
