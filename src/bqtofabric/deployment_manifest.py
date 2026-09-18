"""Immutable, deterministic deployment manifest generation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from .assessment import AssessmentReport
from .models import BigQueryInventory
from .planner import MigrationPlan


def build_manifest(
    inventory: BigQueryInventory, assessment: AssessmentReport, plan: MigrationPlan
) -> dict[str, Any]:
    """Build an offline manifest suitable for a future plan/apply boundary."""
    payload = {
        "projectId": inventory.project_id,
        "architecture": plan.architecture,
        "items": [asdict(item) for item in plan.items],
        "unresolvedDependencies": list(plan.unresolved_dependencies),
        "targetManifest": [
            {
                "sourceId": decision.source_id,
                "target": decision.target.value,
                "compatibility": decision.compatibility.value,
                "actions": list(decision.actions),
            }
            for decision in sorted(assessment.decisions, key=lambda item: item.source_id)
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "mode": "dry-run",
        "manifestVersion": "1.0",
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "payload": payload,
    }
