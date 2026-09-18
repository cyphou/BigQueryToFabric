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
        if any(item.get("compatibility") == "unsupported" for item in payload.get("targetManifest", [])):
            errors.append("plan contains unsupported components")

    return {
        "mode": "offline",
        "status": "blocked" if errors else "ready_for_review",
        "errors": errors,
        "apply": "not_implemented",
    }


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
