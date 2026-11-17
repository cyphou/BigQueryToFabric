"""Regression tests for the downloaded, manually assisted LookML example."""

import importlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from bqtofabric import cli
from bqtofabric.assessment import run_assessment
from bqtofabric.cli import ExitCode
from bqtofabric.generator import looker_powerbi
from bqtofabric.inventory import JsonInventoryProvider
from bqtofabric.planner import build_plan

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "examples" / "looker" / "looker-skills"
INVENTORY = SAMPLE / "inventory.assisted.json"
ASSET = "enterprise_analytics.looker.orders"


def _no_network(*args: object, **kwargs: object) -> None:
    raise AssertionError("public example migration must remain offline")


def _generate_args(output: Path) -> list[str]:
    return [
        "generate-looker-powerbi", str(INVENTORY), "--asset", ASSET, "--output", str(output),
    ]


def test_assisted_public_sample_is_assessed_and_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("socket.socket.connect", _no_network)
    original = INVENTORY.read_bytes()
    document = json.loads(original)
    component = document["components"][0]
    assert component["discovered_from"] == "assisted"
    assert len(component["properties"]["joins"]) == 5
    assert len(component["properties"]["dashboards"][0]["elements"]) == 7

    raw_view = (SAMPLE / "views" / "raw" / "orders.view.lkml").read_text(encoding="utf-8")
    assert "dimension: user_id {" in raw_view and "sql: ${TABLE}.user_id ;;" in raw_view
    assert cli.main(["validate", str(INVENTORY)]) == ExitCode.SUCCESS
    capsys.readouterr()
    assert cli.main(["assess", str(INVENTORY)]) == ExitCode.SUCCESS
    assessment = json.loads(capsys.readouterr().out)
    assert assessment["discovery_coverage"] == {"assisted": 1}
    assert any(finding["code"] == "ASSISTED_EVIDENCE_UNVERIFIED"
               for finding in assessment["findings"])
    inventory = JsonInventoryProvider(INVENTORY).load()
    plan = build_plan(inventory, run_assessment(inventory))
    assert plan.items[0].manual_review
    assert "assisted_evidence" in plan.items[0].manual_review_reasons

    monkeypatch.setattr(looker_powerbi, "_load_backend", lambda: (None, None, None))

    def capture(
        pbip: Any, tmdl: Any, visual: Any, name: str,
        tables: list[dict[str, Any]], pages: list[Any],
    ) -> dict[str, str]:
        return {"capture.json": json.dumps({"tables": tables, "pages": pages})}

    monkeypatch.setattr(looker_powerbi, "_render", capture)
    output = tmp_path / "review"
    assert cli.main(_generate_args(output)) == ExitCode.SUCCESS
    captured = json.loads((output / "capture.json").read_text(encoding="utf-8"))
    assert [column["name"] for column in captured["tables"][0]["columns"]] == ["user_id"]
    assert captured["tables"][0]["measures"] == []
    assert captured["tables"][0]["partitions"][0]["source"]["expression"].startswith("error ")
    assert captured["pages"][0][1:] == ["Review", []]
    review = json.loads((output / "looker-powerbi-review.json").read_text(encoding="utf-8"))
    assert review["status"] == "review_required"
    assert review["runtime"] == review["parity"] == "not_run"
    assert review["security"] == "not_migrated_unverified"
    assert review["source_binding"] == "disabled"
    assert {"security_not_migrated", "joins_not_migrated", "explores_not_migrated",
            "dashboard_filters_not_migrated", "review_page_scaffold"} <= {
        issue["code"] for issue in review["issues"]
    }
    assert not any(item["kind"] == "visual" for item in review["converted"])
    assert INVENTORY.read_bytes() == original


def test_assisted_public_sample_with_optional_real_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sibling = ROOT.parent / "TableauToPowerBI"
    if (sibling / "powerbi_import" / "pbip_generator.py").is_file():
        monkeypatch.syspath_prepend(str(sibling))
    if (importlib.util.find_spec("powerbi_import") is None
            or importlib.util.find_spec("tableau_export") is None):
        pytest.skip("optional TableauToPowerBI packages are unavailable")
    monkeypatch.setattr("socket.socket.connect", _no_network)
    output = tmp_path / "review"
    assert cli.main(_generate_args(output)) == ExitCode.SUCCESS
    second = tmp_path / "review-again"
    assert cli.main(_generate_args(second)) == ExitCode.SUCCESS
    assert {
        path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()
    } == {
        path.relative_to(second): path.read_bytes() for path in second.rglob("*") if path.is_file()
    }
    assert (output / "LookerMigration.pbip").is_file()
    report = output / "LookerMigration.Report" / "definition"
    assert not list(report.glob("pages/*/visuals/*/visual.json"))
    model = (output / "LookerMigration.SemanticModel" / "definition" / "tables"
             / "orders.tmdl").read_text(encoding="utf-8")
    assert "column user_id" in model and 'error "Review-only:' in model

    schema_validator = importlib.import_module("powerbi_import.schema_validator")
    schema_results = schema_validator.validate_report_dir(str(report))
    assert schema_results and all(result.ok for result in schema_results)
    openability = importlib.import_module("powerbi_import.openability")
    result = openability.check_openability(str(output))
    assert result.openable, result.blocking_issues
    assert result.to_dict()["refresh_verification"] == "not_run"
