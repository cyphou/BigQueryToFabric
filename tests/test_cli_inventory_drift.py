import copy
import json
from pathlib import Path

import pytest

from bqtofabric.cli import ExitCode, main
from bqtofabric.inventory_drift import inventory_drift
from bqtofabric.models import BigQueryInventory

FIXTURE = Path(__file__).parent / "fixtures" / "gcp_ecosystem_project.json"


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_inventory_drift_cli_reports_stable_json_without_writing_inputs(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    baseline = json.loads(FIXTURE.read_text(encoding="utf-8"))
    current = copy.deepcopy(baseline)
    first = current["datasets"][0]["objects"][0]
    first["size_bytes"] = (first.get("size_bytes") or 0) + 1
    first.setdefault("properties", {})["runtime_note"] = "live"
    removed = current["datasets"][0]["objects"].pop()
    current.setdefault("components", []).append({
        "source_id": "gcp-data-platform.pubsub.new_topic",
        "name": "new_topic",
        "kind": "pubsub_topic",
    })
    baseline_path, current_path = tmp_path / "baseline.json", tmp_path / "current.json"
    _write(baseline_path, baseline)
    _write(current_path, current)
    before = baseline_path.read_bytes(), current_path.read_bytes()

    def no_network(*args, **kwargs):
        raise AssertionError("inventory drift comparison must remain offline")

    monkeypatch.setattr("socket.socket.connect", no_network)
    args = ["inventory-drift", str(baseline_path), str(current_path)]
    assert main(args) == ExitCode.SUCCESS
    first_output = capsys.readouterr().out
    report = json.loads(first_output)
    assert report == inventory_drift(
        BigQueryInventory.from_dict(baseline), BigQueryInventory.from_dict(current)
    )
    assert report["status"] == "drift_detected"
    assert report["added"] == ["gcp-data-platform.pubsub.new_topic"]
    assert report["removed"] == [removed["source_id"]]
    assert report["changed"] == [{
        "sourceId": first["source_id"],
        "fields": ["size_bytes", "properties.runtime_note"],
    }]
    assert '"live"' not in first_output

    assert main(args) == ExitCode.SUCCESS
    assert capsys.readouterr().out == first_output
    assert (baseline_path.read_bytes(), current_path.read_bytes()) == before


def test_inventory_drift_cli_identical_inventory_reports_no_drift(tmp_path: Path, capsys) -> None:
    inventory = json.loads(FIXTURE.read_text(encoding="utf-8"))
    baseline_path, current_path = tmp_path / "baseline.json", tmp_path / "current.json"
    _write(baseline_path, inventory)
    _write(current_path, inventory)

    assert main(["inventory-drift", str(baseline_path), str(current_path)]) == ExitCode.SUCCESS

    assert json.loads(capsys.readouterr().out)["status"] == "no_drift"


def test_inventory_drift_cli_reports_missing_inventory(tmp_path: Path, capsys) -> None:
    baseline_path = tmp_path / "missing.json"
    current_path = tmp_path / "current.json"
    _write(current_path, json.loads(FIXTURE.read_text(encoding="utf-8")))

    assert main(["inventory-drift", str(baseline_path), str(current_path)]) == (
        ExitCode.FILE_NOT_FOUND
    )
    assert "not found" in capsys.readouterr().out.lower()


@pytest.mark.parametrize("invalid_side", ["baseline", "current"])
def test_inventory_drift_cli_rejects_noncanonical_inventory(
    tmp_path: Path, capsys, invalid_side: str,
) -> None:
    baseline_path, current_path = tmp_path / "baseline.json", tmp_path / "current.json"
    valid = json.loads(FIXTURE.read_text(encoding="utf-8"))
    _write(baseline_path, valid)
    _write(current_path, valid)
    (baseline_path if invalid_side == "baseline" else current_path).write_text(
        '{"datasets": []}', encoding="utf-8"
    )

    assert main(["inventory-drift", str(baseline_path), str(current_path)]) == (
        ExitCode.VALIDATION_FAILED
    )
    assert "invalid" in capsys.readouterr().out.lower()
