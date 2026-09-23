"""Offline deployment readiness gates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .deployment_manifest import verify_manifest


def check_deployment_readiness(root: Path) -> dict[str, Any]:
    """Check generated artifacts before a future authenticated apply phase."""
    errors: list[str] = []
    manifest_path = root / "deployment-manifest.json"
    validation_path = root / "artifact-validation.json"
    manifest = _read_json(manifest_path, errors)
    validation = _read_json(validation_path, errors)

    if manifest is not None and not verify_manifest(manifest):
        errors.append("deployment manifest integrity verification failed")
    if validation is not None and validation.get("status") != "passed":
        errors.append("generated artifact validation did not pass")
    if manifest is not None:
        payload = manifest.get("payload", {})
        if payload.get("unresolvedDependencies"):
            errors.append("plan contains unresolved dependencies")
        target_manifest = payload.get("targetManifest", [])
        if any(item.get("compatibility") == "unsupported" for item in target_manifest):
            errors.append("plan contains unsupported components")
        errors.extend(_assessment_gate_errors(payload, target_manifest))

    return {
        "mode": "offline",
        "status": "blocked" if errors else "ready_for_review",
        "errors": errors,
        "apply": "not_implemented",
    }


def _assessment_gate_errors(
    payload: dict[str, Any], target_manifest: list[Any]
) -> list[str]:
    """Block on assessment evidence that contradicts a ready-for-review verdict."""
    errors: list[str] = []
    blockers = payload.get("blockers")
    if isinstance(blockers, list) and blockers:
        errors.append(f"assessment reports {len(blockers)} blocking finding(s)")

    finding_counts = payload.get("findingCounts")
    if isinstance(finding_counts, dict) and finding_counts.get("FAIL"):
        errors.append(f"assessment reports {finding_counts['FAIL']} FAIL finding(s)")

    parity = payload.get("paritySummary")
    if isinstance(parity, dict) and parity.get("failed"):
        errors.append(f"{parity['failed']} parity check(s) failed")

    redesign = sum(
        1
        for item in target_manifest
        if isinstance(item, dict) and item.get("compatibility") == "redesign"
    )
    if redesign:
        errors.append(f"plan contains {redesign} component(s) requiring redesign")

    manual = sum(
        1
        for item in target_manifest
        if isinstance(item, dict) and item.get("manualReview") is True
    )
    if manual:
        errors.append(f"plan contains {manual} component(s) awaiting manual review")
    return errors


def _read_json(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        errors.append(f"{path.name}: {error}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{path.name}: root must be an object")
        return None
    return value
