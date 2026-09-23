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


def _write_manifest(tmp_path: Path, payload: dict) -> None:
    manifest = {"payload": payload}
    manifest["sha256"] = __import__("hashlib").sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    (tmp_path / "deployment-manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "artifact-validation.json").write_text(json.dumps({"status": "passed"}))


def test_readiness_blocks_on_assessment_fail_findings(tmp_path: Path) -> None:
    """A FAIL blocker must never coexist with a ready_for_review verdict."""
    _write_manifest(tmp_path, {
        "findingCounts": {"FAIL": 1, "WARN": 3},
        "blockers": [{"code": "MAPPING_UNSUPPORTED", "sourceId": "demo.policy"}],
        "targetManifest": [{"compatibility": "transform", "manualReview": False}],
    })

    result = check_deployment_readiness(tmp_path)

    assert result["status"] == "blocked"
    joined = " ".join(result["errors"])
    assert "1 blocking finding(s)" in joined
    assert "1 FAIL finding(s)" in joined


def test_readiness_blocks_on_failed_parity_and_manual_review(tmp_path: Path) -> None:
    """Failed parity and pending manual review are not deployment-ready states."""
    _write_manifest(tmp_path, {
        "paritySummary": {"failed": 2, "passed": 1},
        "targetManifest": [
            {"compatibility": "redesign", "manualReview": True},
            {"compatibility": "direct", "manualReview": False},
        ],
    })

    result = check_deployment_readiness(tmp_path)

    assert result["status"] == "blocked"
    joined = " ".join(result["errors"])
    assert "2 parity check(s) failed" in joined
    assert "1 component(s) requiring redesign" in joined
    assert "1 component(s) awaiting manual review" in joined


def test_readiness_allows_clean_payload(tmp_path: Path) -> None:
    """A clean assessment payload still reaches ready_for_review."""
    _write_manifest(tmp_path, {
        "findingCounts": {"WARN": 2},
        "paritySummary": {"passed": 3},
        "targetManifest": [{"compatibility": "direct", "manualReview": False}],
    })

    result = check_deployment_readiness(tmp_path)

    assert result["status"] == "ready_for_review"
    assert result["errors"] == []