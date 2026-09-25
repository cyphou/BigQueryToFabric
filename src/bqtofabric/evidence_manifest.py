"""Portable integrity manifest for offline migration evidence packages."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

EVIDENCE_MANIFEST_VERSION = "1.0"


def build_evidence_manifest(root: Path, paths: tuple[Path, ...]) -> dict[str, Any]:
    """Hash selected evidence files relative to the package root."""
    files = {
        path.relative_to(root).as_posix(): {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "sizeBytes": path.stat().st_size,
        }
        for path in sorted(paths, key=lambda value: value.relative_to(root).as_posix())
        if path.is_file()
    }
    payload = {
        "projectId": _project_id(root),
        "files": files,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "mode": "offline-evidence",
        "manifestVersion": EVIDENCE_MANIFEST_VERSION,
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "payload": payload,
    }


def verify_evidence_manifest(root: Path, manifest: dict[str, Any]) -> bool:
    """Verify manifest integrity and the recorded bytes of each evidence file."""
    payload = manifest.get("payload")
    recorded = manifest.get("sha256")
    if not isinstance(payload, dict) or not isinstance(recorded, str):
        return False
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != recorded:
        return False
    files = payload.get("files")
    if not isinstance(files, dict):
        return False
    for relative_path, metadata in files.items():
        if not isinstance(relative_path, str) or not isinstance(metadata, dict):
            return False
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            return False
        if hashlib.sha256(path.read_bytes()).hexdigest() != metadata.get("sha256"):
            return False
    return True


def _project_id(root: Path) -> str:
    """Read project identity from the generated assessment when available."""
    assessment_path = root / "assessment.json"
    if not assessment_path.is_file():
        return "unknown"
    try:
        value = json.loads(assessment_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    project_id = value.get("project_id") if isinstance(value, dict) else None
    return project_id if isinstance(project_id, str) and project_id else "unknown"
