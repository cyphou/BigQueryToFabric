import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bqtofabric import cli
from bqtofabric.cli import ExitCode
from bqtofabric.generator import looker_powerbi
from bqtofabric.models import ObjectKind


@pytest.fixture
def inventory(tmp_path: Path) -> Path:
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps({
        "project_id": "project",
        "components": [
            {"source_id": "project.looker.first", "name": "shared", "kind": "looker_asset",
             "properties": {"views": []}},
            {"source_id": "project.looker.second", "name": "shared", "kind": "looker_asset"},
            {"source_id": "project.looker.third", "name": "unique", "kind": "looker_asset"},
            {"source_id": "project.table", "name": "table", "kind": "table"},
        ],
    }), encoding="utf-8")
    return path


def command(inventory: Path, output: Path, asset: str = "project.looker.first") -> list[str]:
    return ["generate-looker-powerbi", str(inventory), "--asset", asset, "-o", str(output)]


def test_generate_looker_persists_all_files_and_review(inventory, tmp_path, monkeypatch, capsys):
    seen = []
    review = {"status": "review_required", "issues": [{"path": "views[0]", "code": "test"}]}

    def generate(asset, *, project_name):
        seen.append((asset.source_id, asset.kind, project_name, asset.properties))
        return SimpleNamespace(files={
            "MyProject.pbip": "pbip\n",
            "MyProject.Report/definition/report.json": '{"ok": true}\n',
        }, review=review)

    monkeypatch.setattr(cli, "generate_looker_powerbi_project", generate)
    output = tmp_path / "output"
    output.mkdir()
    result = cli.main(command(inventory, output, "unique") + ["--project-name", "MyProject"])
    assert result == ExitCode.SUCCESS
    assert seen == [("project.looker.third", ObjectKind.LOOKER_ASSET, "MyProject", {})]
    assert (output / "MyProject.pbip").read_text(encoding="utf-8") == "pbip\n"
    assert (output / "MyProject.Report/definition/report.json").read_text(
        encoding="utf-8"
    ) == '{"ok": true}\n'
    assert json.loads((output / "looker-powerbi-review.json").read_text(
        encoding="utf-8"
    )) == review
    assert "not verified" in capsys.readouterr().out


@pytest.mark.parametrize("selector", ["missing", "shared", "project.table"])
def test_selection_errors_do_not_call_generator(inventory, tmp_path, monkeypatch, selector, capsys):
    def unexpected(*args, **kwargs):
        pytest.fail("generator should not be called")

    monkeypatch.setattr(cli, "generate_looker_powerbi_project", unexpected)
    output = tmp_path / "output"
    assert cli.main(command(inventory, output, selector)) == ExitCode.VALIDATION_FAILED
    assert ("Ambiguous" if selector == "shared" else "not found") in capsys.readouterr().out
    assert not output.exists()


def test_source_id_takes_precedence_over_name(inventory, tmp_path, monkeypatch):
    payload = json.loads(inventory.read_text(encoding="utf-8"))
    payload["components"][1]["name"] = "project.looker.first"
    inventory.write_text(json.dumps(payload), encoding="utf-8")
    selected = []
    monkeypatch.setattr(cli, "generate_looker_powerbi_project", lambda asset, **kwargs:
                        selected.append(asset.source_id) or SimpleNamespace(
                            files={"project.pbip": "project"}, review={}
                        ))
    assert cli.main(command(inventory, tmp_path / "output")) == ExitCode.SUCCESS
    assert selected == ["project.looker.first"]


def test_missing_dependency_reports_backend_requirement(inventory, tmp_path, monkeypatch, capsys):
    def missing(name):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(looker_powerbi.importlib, "import_module", missing)
    output = tmp_path / "output"
    assert cli.main(command(inventory, output)) == ExitCode.GENERAL_ERROR
    assert "TableauToPowerBI 44.0.0" in capsys.readouterr().out
    assert not output.exists()


def test_generator_error_is_reported(inventory, tmp_path, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise RuntimeError("sensitive source value")

    monkeypatch.setattr(cli, "generate_looker_powerbi_project", fail)
    assert cli.main(command(inventory, tmp_path / "out")) == ExitCode.GENERAL_ERROR
    output = capsys.readouterr().out
    assert "backend runtime error" in output
    assert "sensitive source value" not in output


@pytest.mark.parametrize("error, code, message", [
    (ValueError("sensitive value"), ExitCode.VALIDATION_FAILED, "Invalid Looker project"),
    (TypeError("sensitive value"), ExitCode.VALIDATION_FAILED, "Invalid Looker project"),
    (OSError("sensitive value"), ExitCode.GENERAL_ERROR, "backend I/O error"),
])
def test_expected_generator_errors_are_sanitized(
    inventory, tmp_path, monkeypatch, capsys, error, code, message
):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(cli, "generate_looker_powerbi_project", fail)
    assert cli.main(command(inventory, tmp_path / "out")) == code
    output = capsys.readouterr().out
    assert message in output
    assert "sensitive value" not in output


def test_unexpected_generator_errors_propagate(inventory, tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise KeyError("unexpected backend defect")

    monkeypatch.setattr(cli, "generate_looker_powerbi_project", fail)
    with pytest.raises(KeyError, match="unexpected backend defect"):
        cli.main(command(inventory, tmp_path / "out"))


def test_no_convertible_views_fails_and_persists_review(inventory, tmp_path, monkeypatch, capsys):
    # The real adapter exits before using the backend when no views are convertible.
    monkeypatch.setattr(looker_powerbi, "_load_backend", lambda: (None, None, None))
    output = tmp_path / "output"
    assert cli.main(command(inventory, output)) == ExitCode.VALIDATION_FAILED
    assert "no project generated" in capsys.readouterr().out.lower()
    assert {path.name for path in output.iterdir()} == {"looker-powerbi-review.json"}
    review = json.loads((output / "looker-powerbi-review.json").read_text(encoding="utf-8"))
    assert any(issue["code"] == "no_convertible_model" for issue in review["issues"])


def test_real_backend_cli_generates_pbip_and_review(inventory, tmp_path, monkeypatch):
    sibling = Path(__file__).resolve().parents[2] / "TableauToPowerBI"
    if (sibling / "powerbi_import" / "pbip_generator.py").is_file():
        monkeypatch.syspath_prepend(str(sibling))
    if (importlib.util.find_spec("powerbi_import") is None
            or importlib.util.find_spec("tableau_export") is None):
        pytest.skip("optional TableauToPowerBI packages are unavailable")
    payload = json.loads(inventory.read_text(encoding="utf-8"))
    payload["components"][0]["properties"] = {
        "views": [{
            "name": "orders",
            "sql_table_name": "project.dataset.orders",
            "dimensions": [{"name": "region", "type": "string", "sql": "${TABLE}.region"}],
            "measures": [{"name": "count_orders", "type": "count"}],
        }],
        "dashboards": [{"name": "Overview", "elements": [{
            "name": "Summary", "type": "table", "view": "orders",
            "dimensions": ["region"], "measures": ["count_orders"],
        }]}],
    }
    inventory.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "real-output"
    assert cli.main(command(inventory, output)) == ExitCode.SUCCESS
    pbip = json.loads((output / "LookerMigration.pbip").read_text(encoding="utf-8"))
    assert pbip["artifacts"][0]["report"]["path"] == "LookerMigration.Report"
    report = output / "LookerMigration.Report"
    assert json.loads((report / "definition.pbir").read_text(encoding="utf-8"))[
        "datasetReference"
    ]["byPath"]["path"] == "../LookerMigration.SemanticModel"
    pages = list((report / "definition" / "pages").glob("*/page.json"))
    assert len(pages) == 1
    assert json.loads(pages[0].read_text(encoding="utf-8"))["displayName"] == "Overview"
    visuals = list((report / "definition" / "pages").glob("*/visuals/*/visual.json"))
    assert len(visuals) == 1
    assert json.loads(visuals[0].read_text(encoding="utf-8"))["visual"]["visualType"] == "tableEx"
    review = json.loads((output / "looker-powerbi-review.json").read_text(encoding="utf-8"))
    assert review["status"] == "review_required"
    assert review["runtime"] == review["parity"] == "not_run"
    assert any(issue["code"] == "source_binding_omitted" for issue in review["issues"])


def test_invalid_project_name_is_reported(inventory, tmp_path, capsys):
    assert cli.main(command(inventory, tmp_path / "out") + [
        "--project-name", "../unsafe",
    ]) == ExitCode.VALIDATION_FAILED
    assert "project_name" in capsys.readouterr().out


@pytest.mark.parametrize("payload", ["{", "[]", '{"project_id": ""}',
                                     '{"project_id": "p", "components": [1]}'])
def test_invalid_inventory(inventory, tmp_path, payload, capsys):
    inventory.write_text(payload, encoding="utf-8")
    assert cli.main(command(inventory, tmp_path / "out")) == ExitCode.VALIDATION_FAILED
    assert "Invalid inventory" in capsys.readouterr().out


def test_missing_inventory(tmp_path):
    assert cli.main(command(tmp_path / "missing", tmp_path / "out")) == ExitCode.FILE_NOT_FOUND


def test_invalid_inventory_does_not_echo_source_values(inventory, tmp_path, capsys):
    payload = json.loads(inventory.read_text(encoding="utf-8"))
    payload["components"][0]["kind"] = "sensitive_value"
    inventory.write_text(json.dumps(payload), encoding="utf-8")
    assert cli.main(command(inventory, tmp_path / "out")) == ExitCode.VALIDATION_FAILED
    assert "sensitive_value" not in capsys.readouterr().out


@pytest.mark.parametrize("files", [
    {"../escape": "x"}, {"/absolute": "x"}, {"C:/escape": "x"},
    {"nested\\escape": "x"}, {"a//b": "x"}, {"a/./b": "x"},
    {"a/../b": "x"}, {"a:stream": "x"}, {"CON.txt": "x"},
    {"looker-powerbi-review.json": "x"}, {"LOOKER-POWERBI-REVIEW.JSON": "x"},
    {"a": "x", "a/b": "y"}, {"a/x": "x", "A/X": "y"},
])
def test_unsafe_generator_paths_are_rejected(inventory, tmp_path, monkeypatch, files):
    monkeypatch.setattr(cli, "generate_looker_powerbi_project", lambda *args, **kwargs:
                        SimpleNamespace(files=files, review={}))
    output = tmp_path / "output"
    assert cli.main(command(inventory, output)) == ExitCode.VALIDATION_FAILED
    assert not output.exists()
    assert not (tmp_path / "escape").exists()


def test_unsafe_generator_path_is_not_echoed(inventory, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "generate_looker_powerbi_project", lambda *args, **kwargs:
                        SimpleNamespace(files={"../sensitive_value": "x"}, review={}))
    assert cli.main(command(inventory, tmp_path / "out")) == ExitCode.VALIDATION_FAILED
    assert "sensitive_value" not in capsys.readouterr().out


def test_nonempty_output_is_never_modified(inventory, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "generate_looker_powerbi_project", lambda *args, **kwargs:
                        SimpleNamespace(files={"existing": "new"}, review={}))
    output = tmp_path / "output"
    output.mkdir()
    (output / "existing").write_text("user", encoding="utf-8")
    assert cli.main(command(inventory, output)) == ExitCode.VALIDATION_FAILED
    assert (output / "existing").read_text(encoding="utf-8") == "user"
    assert list(output.iterdir()) == [output / "existing"]


def test_symlink_output_is_rejected(inventory, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "generate_looker_powerbi_project", lambda *args, **kwargs:
                        SimpleNamespace(files={"file": "x"}, review={}))
    outside = tmp_path / "outside"
    outside.mkdir()
    output = tmp_path / "link"
    try:
        output.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")
    assert cli.main(command(inventory, output)) == ExitCode.VALIDATION_FAILED
    assert not list(outside.iterdir())


def test_output_with_nested_symlink_is_not_touched(inventory, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "generate_looker_powerbi_project", lambda *args, **kwargs:
                        SimpleNamespace(files={"nested/file": "x"}, review={}))
    output = tmp_path / "output"
    output.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (output / "nested").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")
    assert cli.main(command(inventory, output)) == ExitCode.VALIDATION_FAILED
    assert not list(outside.iterdir())


def test_write_failure_removes_created_files(inventory, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "generate_looker_powerbi_project", lambda *args, **kwargs:
                        SimpleNamespace(files={"a/file": "x", "z/file": "y"}, review={}))
    original_open = Path.open

    def fail_second_file(path, *args, **kwargs):
        if path.name == "file" and path.parent.name == "z":
            raise OSError("sensitive source value")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_second_file)
    output = tmp_path / "output"
    assert cli.main(command(inventory, output)) == ExitCode.GENERAL_ERROR
    diagnostic = capsys.readouterr().out
    assert "I/O error" in diagnostic
    assert "sensitive source value" not in diagnostic
    assert not list(output.iterdir())


def test_invalid_review_is_rejected_before_writing(inventory, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "generate_looker_powerbi_project", lambda *args, **kwargs:
                        SimpleNamespace(files={"file": "x"}, review={"bad": object()}))
    output = tmp_path / "output"
    assert cli.main(command(inventory, output)) == ExitCode.VALIDATION_FAILED
    assert not output.exists()


def test_help_explains_offline_dependency(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["generate-looker-powerbi", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "TableauToPowerBI" in output
    assert "--asset" in output
    assert "empty output directory" in output
