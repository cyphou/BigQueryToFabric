"""Immutable, deterministic deployment manifest generation."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict
from typing import Any

from .assessment import AssessmentReport
from .models import BigQueryInventory
from .planner import MigrationPlan


def build_manifest(
    inventory: BigQueryInventory, assessment: AssessmentReport, plan: MigrationPlan
) -> dict[str, Any]:
    """Build an offline manifest suitable for a future plan/apply boundary."""
    manual_review = {item.source_id: item.manual_review for item in plan.items}
    payload = {
        "projectId": inventory.project_id,
        "architecture": plan.architecture,
        "items": [asdict(item) for item in plan.items],
        "unresolvedDependencies": list(plan.unresolved_dependencies),
        "findingCounts": dict(
            sorted(Counter(finding.severity for finding in assessment.findings).items())
        ),
        "paritySummary": dict(
            sorted(
                Counter(
                    str(parity["status"]) for parity in assessment.parity_summary.values()
                ).items()
            )
        ),
        "blockers": [
            {
                "code": finding.code,
                "category": finding.category,
                "sourceId": finding.source_id,
                "message": finding.message,
            }
            for finding in assessment.findings
            if finding.severity == "FAIL"
        ],
        "targetManifest": [
            {
                "sourceId": decision.source_id,
                "target": decision.target.value,
                "compatibility": decision.compatibility.value,
                "actions": list(decision.actions),
                "manualReview": manual_review.get(decision.source_id, False),
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


def verify_manifest(manifest: dict[str, Any]) -> bool:
    """Verify that a manifest payload still matches its recorded SHA-256 hash."""
    recorded = manifest.get("sha256")
    payload = manifest.get("payload")
    if not isinstance(recorded, str) or not isinstance(payload, dict):
        return False
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest() == recorded
