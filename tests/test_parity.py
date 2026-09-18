from bqtofabric.parity import assess_parity


def test_parity_requires_runtime_evidence_for_passed_status() -> None:
    result = assess_parity({"parity": {"schema": {"status": "passed"}}})

    assert result["status"] == "not_run"
    assert result["checks"]["row_count"]["status"] == "not_run"


def test_parity_failed_check_wins_over_not_run_checks() -> None:
    result = assess_parity({"parity": {
        "schema": {"status": "passed"},
        "row_count": {"status": "failed", "source": 10, "target": 9},
        "checksum": {"status": "not_run", "algorithm": "sha256"},
    }})

    assert result["status"] == "failed"
    assert result["checks"]["row_count"]["target"] == 9


def test_parity_can_be_not_applicable() -> None:
    assert assess_parity({}, applicable=False)["status"] == "not_applicable"