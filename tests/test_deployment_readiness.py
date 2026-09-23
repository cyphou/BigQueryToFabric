import json
from pathlib import Path

from bqtofabric.deployment_readiness import check_deployment_readiness


def test_readiness_blocks_tampered_manifest(tmp_path: Path) -> None:
    (tmp_path / "deployment-manifest.json").write_text(json.dumps({"sha256": "bad", "payload": {}}))
    (tmp_path / "artifact-validation.json").write_text(json.dumps({"status": "passed"}))

    result = check_deployment_readiness(tmp_path)

    assert result["status"] == "blocked"
    assert result["apply"] == "not_implemented"


def test_readiness_blocks_unresolved_and_unsupported_payload(tmp_path: Path) -> None:
    payload = {
        "unresolvedDependencies": ["missing.source"],
        "targetManifest": [{"compatibility": "unsupported"}],
    }
    manifest = {"payload": payload}
    manifest["sha256"] = __import__("hashlib").sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    (tmp_path / "deployment-manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "artifact-validation.json").write_text(json.dumps({"status": "passed"}))

    result = check_deployment_readiness(tmp_path)

    assert result["status"] == "blocked"
    assert "unresolved dependencies" in " ".join(result["errors"])
    assert "unsupported components" in " ".join(result["errors"])