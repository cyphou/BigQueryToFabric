from pathlib import Path
from typing import Any

import pytest

from scripts.review_ledger import check_verdict, main, read_ledger, record, recurring

GATES_PASSED = {"pytest": "passed", "ruff": "passed", "pyright": "passed", "validate_agents": "passed"}


def _verdict(**overrides: Any) -> dict[str, Any]:
    verdict: dict[str, Any] = {
        "schema_version": "1.0",
        "slice": "p4-wave-scoped-generation",
        "reviewer": "Reviewer",
        "owner": "FabricGenerator",
        "round": 1,
        "verdict": "changes_requested",
        "findings": [_finding()],
        "gates": dict(GATES_PASSED),
    }
    verdict.update(overrides)
    return verdict


def _finding(code: str = "PIPELINE_TRIGGER_MISPLACED", *, blocking: bool = True) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "FAIL" if blocking else "WARN",
        "blocking": blocking,
        "file": "src/bqtofabric/fabric_artifacts.py",
        "summary": "Triggers emitted under properties.",
    }


def test_documented_example_verdict_conforms() -> None:
    assert check_verdict(_verdict()) == []


def test_accepted_requires_every_gate_passed() -> None:
    gates = dict(GATES_PASSED, pyright="not_run")

    errors = check_verdict(_verdict(verdict="accepted", findings=[], gates=gates))

    assert errors == ["$.gates.pyright: must be 'passed'"]


def test_accepted_rejects_a_blocking_finding() -> None:
    assert check_verdict(_verdict(verdict="accepted")) == [
        "$.findings[0].blocking: must be False"
    ]


def test_changes_requested_needs_a_blocking_finding() -> None:
    errors = check_verdict(_verdict(findings=[_finding(blocking=False)]))

    assert errors == ["$.findings: no item matches the required condition"]


def test_round_three_cannot_request_changes() -> None:
    errors = check_verdict(_verdict(round=3))

    assert errors == ["$.verdict: must be one of ['accepted', 'escalate']"]


def test_escalate_requires_a_target_and_unknown_fields_are_rejected() -> None:
    errors = check_verdict(_verdict(verdict="escalate", note="x"))

    assert "$: missing escalate_to" in errors
    assert "$: unexpected note" in errors


def test_boolean_is_not_an_integer_round() -> None:
    assert check_verdict(_verdict(round=True)) == ["$.round: expected integer"]


def test_ledger_enforces_round_sequence_and_closes_threads(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"

    assert record(ledger, _verdict(round=2)) == ["first verdict for this slice must be round 1"]
    assert record(ledger, _verdict()) == []
    assert record(ledger, _verdict(round=3, verdict="escalate", escalate_to="TechLead")) == [
        "expected round 2, got 3"
    ]
    assert record(ledger, _verdict(round=2, owner="Architect")) == [
        "owner changed from FabricGenerator to Architect without escalation"
    ]
    assert record(ledger, _verdict(round=2, verdict="accepted", findings=[])) == []
    assert record(ledger, _verdict(round=3, verdict="accepted", findings=[])) == [
        "thread already closed with accepted; open a new slice"
    ]
    assert [entry["round"] for entry in read_ledger(ledger)] == [1, 2]


def test_rounds_are_counted_per_reviewer(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"

    assert record(ledger, _verdict(verdict="accepted", findings=[])) == []
    assert record(ledger, _verdict(reviewer="Tester")) == []


def test_invalid_verdict_is_not_written(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"

    assert record(ledger, _verdict(verdict="approved")) != []
    assert not ledger.exists()


def test_recurring_counts_distinct_slices_of_blocking_findings(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    repeated = dict(_finding(), failure_mode="Tests that assert the bug")
    record(ledger, _verdict(slice="a", findings=[repeated, _finding("ONLY_WARN", blocking=False)]))
    record(ledger, _verdict(slice="a", reviewer="Tester", findings=[repeated]))
    record(ledger, _verdict(slice="b", findings=[repeated, _finding("ONLY_WARN", blocking=False)]))

    assert recurring(read_ledger(ledger)) == {
        "PIPELINE_TRIGGER_MISPLACED": ["a", "b"],
        "failure_mode:Tests that assert the bug": ["a", "b"],
    }


def test_cli_check_reports_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import json

    verdict = tmp_path / "verdict.json"
    verdict.write_text(json.dumps(_verdict(round=4)), encoding="utf-8")

    assert main(["check", str(verdict)]) == 1
    assert "$.round: above 3" in capsys.readouterr().err
