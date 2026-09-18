import json
from pathlib import Path

from bqtofabric.deployment_readiness import check_deployment_readiness


def test_readiness_blocks_tampered_manifest(tmp_path: Path) -> None:
    (tmp_path / "deployment-manifest.json").write_text(json.dumps({"sha256": "bad", "payload": {}}))
    (tmp_path / "artifact-validation.json").write_text(json.dumps({"status": "passed"}))

    result = check_deployment_readiness(tmp_path)

    assert result["status"] == "blocked"
    assert result["apply"] == "not_implemented"