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
    notebook = json.loads((tmp_path / "fabric" / "lakehouse_transform.ipynb").read_text())
    markdown_cell = notebook["cells"][0]
    code_cell = notebook["cells"][1]
    assert markdown_cell["metadata"]["language"] == "markdown"
    assert code_cell["metadata"]["language"] == "python"
    assert code_cell["execution_count"] is None
    assert code_cell["outputs"] == []
    assert json.loads((tmp_path / "fabric" / "pipeline.json").read_text())["mode"] == "dry-run"
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