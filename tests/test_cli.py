import json
from pathlib import Path

from test_discovery import FakeBigQueryClient

from bqtofabric import cli
from bqtofabric.cli import ExitCode, main
from bqtofabric.discovery import DiscoveryError

FIXTURE = Path(__file__).parent / "fixtures" / "mixed_project.json"


def test_inventory_command_reports_counts(capsys) -> None:
    result = main(["inventory", str(FIXTURE)])
    output = json.loads(capsys.readouterr().out)

    assert result == ExitCode.SUCCESS
    assert output == {
        "components_by_kind": {"stream": 1, "table": 2, "view": 1},
        "datasets": 1,
        "objects": 4,
        "project_id": "retail-analytics",
    }


def test_generate_writes_reviewable_dry_run_artifacts(tmp_path: Path) -> None:
    result = main(["generate", str(FIXTURE), "--output", str(tmp_path)])

    assert result == ExitCode.SUCCESS
    assert (tmp_path / "assessment.json").is_file()
    assert (tmp_path / "migration-plan.md").is_file()
    assert "Evidence coverage:" in (tmp_path / "migration-plan.md").read_text()
    assert "Parity evidence" in (tmp_path / "migration-plan.md").read_text()
    notebook = json.loads((tmp_path / "fabric" / "lakehouse_transform.ipynb").read_text())
    markdown_cell = notebook["cells"][0]
    code_cell = notebook["cells"][1]
    assert markdown_cell["metadata"]["language"] == "markdown"
    assert code_cell["metadata"]["language"] == "python"
    assert code_cell["execution_count"] is None
    assert code_cell["outputs"] == []
    assert json.loads((tmp_path / "fabric" / "pipeline.json").read_text())["mode"] == "dry-run"
    validation = json.loads((tmp_path / "fabric" / "artifact-validation.json").read_text())
    assert validation["status"] == "passed"
    parity = json.loads((tmp_path / "fabric" / "parity-evidence.json").read_text())
    assert parity["mode"] == "offline-evidence"
    manifest = json.loads((tmp_path / "fabric" / "deployment-manifest.json").read_text())
    assert manifest["mode"] == "dry-run"
    assert len(manifest["sha256"]) == 64
    sql_conversions = json.loads((tmp_path / "fabric" / "sql-conversions.json").read_text())
    assert sql_conversions["mode"] == "dry-run"
    assert any(item["convertedSql"] for item in sql_conversions["conversions"])
    spark_conversions = json.loads((tmp_path / "fabric" / "spark-conversions.json").read_text())
    assert spark_conversions["mode"] == "dry-run"
    dataform_conversions = json.loads(
        (tmp_path / "fabric" / "dataform-conversions.json").read_text()
    )
    assert dataform_conversions["mode"] == "dry-run"
    airflow = json.loads((tmp_path / "fabric" / "airflow-compatibility.json").read_text())
    assert airflow["mode"] == "dry-run"
    assert (tmp_path / "fabric" / "eventhouse_eventstream_spec.json").is_file()
    manifest = json.loads((tmp_path / "fabric" / "target-manifest.json").read_text())
    assert manifest["mode"] == "dry-run"
    assert any(entry["artifactKind"] == "lakehouse_notebook" for entry in manifest["entries"])


def test_generate_preserves_airflow_candidate(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "gcp_ecosystem_project.json"

    assert main(["generate", str(fixture), "--output", str(tmp_path)]) == ExitCode.SUCCESS

    orchestration = json.loads((tmp_path / "fabric" / "orchestration.json").read_text())
    airflow = next(
        item for item in orchestration["candidates"]
        if item["sourceId"] == "gcp-data-platform.composer.platform_dag"
    )
    assert airflow["primaryTarget"] == "airflow_job"
    assert "notebook" in airflow["supportingTargets"]

    manifest = json.loads((tmp_path / "fabric" / "target-manifest.json").read_text())
    streaming = next(
        item for item in manifest["entries"]
        if item["sourceId"] == "gcp-data-platform.pubsub.events"
    )
    assert streaming["artifactKind"] == "eventhouse_kql"


def test_generate_exposes_the_end_to_end_processing_chain(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "gcp_ecosystem_project.json"

    assert main(["generate", str(fixture), "--output", str(tmp_path)]) == ExitCode.SUCCESS

    orchestration = json.loads((tmp_path / "fabric" / "orchestration.json").read_text())
    candidates = {item["sourceId"]: item for item in orchestration["candidates"]}
    ingestion = candidates["gcp-data-platform.dataflow.batch_ingestion"]
    dataform = candidates["gcp-data-platform.dataform.gold_models"]
    composer = candidates["gcp-data-platform.composer.platform_dag"]

    assert ingestion["dependencies"] == ["gcp-data-platform.gcs.raw"]
    assert dataform["dependencies"] == ["gcp-data-platform.sql.daily_metrics"]
    assert composer["dependencies"] == ["gcp-data-platform.dataform.gold_models"]
    assert ingestion["wave"] < dataform["wave"] < composer["wave"]


def test_discover_writes_a_canonical_inventory(monkeypatch, tmp_path: Path) -> None:
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "bigquery_api_responses.json").read_text()
    )
    monkeypatch.setattr(cli, "create_rest_client", lambda project: FakeBigQueryClient(payload))
    output = tmp_path / "nested" / "inventory.json"

    assert main(["discover", "demo-project", "--output", str(output)]) == ExitCode.SUCCESS

    inventory = json.loads(output.read_text(encoding="utf-8"))
    assert inventory["project_id"] == "demo-project"
    assert inventory["datasets"][0]["labels"]["api_key"] == "[redacted]"
    assert main(["assess", str(output)]) == ExitCode.SUCCESS


def test_discover_reports_a_dedicated_exit_code_when_credentials_are_unavailable(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    def refuse(project: str):
        raise DiscoveryError("Could not obtain read-only Google credentials (DefaultCredentialsError).")

    monkeypatch.setattr(cli, "create_rest_client", refuse)

    result = main(["discover", "demo-project", "--output", str(tmp_path / "inventory.json")])

    assert result == ExitCode.DISCOVERY_FAILED
    assert "read-only Google credentials" in capsys.readouterr().out
    assert not (tmp_path / "inventory.json").exists()


def test_manifest_verify_command(tmp_path: Path, capsys) -> None:
    output = tmp_path / "manifest.json"
    assert main(["generate", str(FIXTURE), "--output", str(tmp_path / "generated")]) == ExitCode.SUCCESS
    output.write_text(
        (tmp_path / "generated" / "fabric" / "deployment-manifest.json").read_text(), encoding="utf-8"
    )

    assert main(["manifest-verify", str(output)]) == ExitCode.SUCCESS
    assert "PASS" in capsys.readouterr().out


def test_deployment_check_blocks_unresolved_plan(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    assert main(["generate", str(FIXTURE), "--output", str(generated)]) == ExitCode.SUCCESS

    result = main(["deployment-check", str(generated / "fabric")])

    assert result == ExitCode.SUCCESS