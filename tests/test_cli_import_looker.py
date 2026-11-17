import copy
import importlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bqtofabric import cli
from bqtofabric.cli import ExitCode
from bqtofabric.generator import looker_powerbi


@pytest.fixture
def inputs(tmp_path: Path):
    inventory = tmp_path / "inventory.json"
    payload = tmp_path / "payload.json"
    inventory.write_text(json.dumps({
        "project_id": "project",
        "metadata": {"preserved": True},
        "datasets": [{"source_id": "dataset", "name": "dataset", "objects": [
            {"source_id": "table", "name": "table", "kind": "table"},
        ]}],
        "components": [{"source_id": "component", "name": "component", "kind": "stream"}],
    }), encoding="utf-8")
    payload.write_text(json.dumps({
        "explores": [{
            "model_name": "commerce", "name": "orders", "view_name": "orders",
            "sql_table_name": "project.dataset.orders",
            "joins": [], "always_join": [], "access_filters": [],
            "access_filter_fields": [], "always_filter": [], "conditionally_filter": [],
            "sql_always_where": "", "access_grants": [], "required_access_grants": [],
            "fields": {
                "dimensions": [{"name": "orders.region", "view": "orders", "type": "string",
                                "sql": "${TABLE}.region", "sql_case": None,
                                "dimension_group": None}],
                "measures": [], "filters": [], "parameters": [],
            },
        }],
        "dashboards": [{
            "title": "Overview", "dashboard_filters": [], "dashboard_elements": [{
                "title": "Summary", "query": {
                    "model": "commerce", "view": "orders", "fields": ["orders.region"],
                    "filters": {}, "filter_expression": None, "filter_config": None,
                    "pivots": [], "fill_fields": [], "dynamic_fields": None,
                    "has_table_calculations": False, "limit": "-1", "sorts": [],
                    "total": False, "row_total": None, "subtotals": [],
                    "query_timezone": None, "column_limit": None,
                    "vis_config": {"type": "looker_grid"},
                },
            }],
        }],
    }), encoding="utf-8")
    return inventory, payload


def import_command(inventory: Path, payload: Path, output: Path) -> list[str]:
    return ["import-looker-api", str(inventory), "--payload", str(payload), "--output", str(output)]


def generate_command(inventory: Path, output: Path) -> list[str]:
    return ["generate-looker-powerbi", str(inventory), "--asset", "project.looker.api_export",
            "--output", str(output)]


def test_import_and_generate_with_stub(inputs, tmp_path, monkeypatch):
    inventory, payload = inputs
    before_inventory = inventory.read_bytes()
    before_payload = payload.read_bytes()
    imported = tmp_path / "imported.json"
    assert cli.main(import_command(inventory, payload, imported)) == ExitCode.SUCCESS
    assert inventory.read_bytes() == before_inventory and payload.read_bytes() == before_payload
    document = json.loads(imported.read_text(encoding="utf-8"))
    assert document["metadata"] == {"preserved": True}
    assert document["datasets"][0]["objects"][0]["source_id"] == "table"
    assert document["components"][0]["source_id"] == "component"
    asset = document["components"][1]
    assert asset["source_id"] == "project.looker.api_export"
    expected = json.loads(asset["labels"]["looker_ingestion_report"])
    assert expected
    second = tmp_path / "second.json"
    assert cli.main(import_command(inventory, payload, second)) == ExitCode.SUCCESS
    assert imported.read_bytes() == second.read_bytes()

    def generate(selected, *, project_name):
        assert selected.source_id == "project.looker.api_export"
        assert selected.properties["views"][0]["name"] == "orders"
        return SimpleNamespace(files={"LookerMigration.pbip": "project"}, review={"issues": []})

    monkeypatch.setattr(cli, "generate_looker_powerbi_project", generate)
    output = tmp_path / "project"
    assert cli.main(generate_command(imported, output)) == ExitCode.SUCCESS
    review = json.loads((output / "looker-powerbi-review.json").read_text(encoding="utf-8"))
    assert review["ingestion_diagnostics"] == expected


def test_real_api_import_through_real_backend(inputs, tmp_path, monkeypatch):
    sibling = Path(__file__).resolve().parents[2] / "TableauToPowerBI"
    if (sibling / "powerbi_import" / "pbip_generator.py").is_file():
        monkeypatch.syspath_prepend(str(sibling))
    if (importlib.util.find_spec("powerbi_import") is None
            or importlib.util.find_spec("tableau_export") is None):
        pytest.skip("optional TableauToPowerBI packages are unavailable")
    inventory, payload = inputs

    def no_network(*args, **kwargs):
        raise AssertionError("offline only")

    monkeypatch.setattr("socket.socket.connect", no_network)
    imported, output = tmp_path / "imported.json", tmp_path / "project"
    assert cli.main(import_command(inventory, payload, imported)) == ExitCode.SUCCESS
    assert cli.main(generate_command(imported, output)) == ExitCode.SUCCESS
    pbip = json.loads((output / "LookerMigration.pbip").read_text(encoding="utf-8"))
    assert pbip["artifacts"][0]["report"]["path"] == "LookerMigration.Report"
    assert list((output / "LookerMigration.Report/definition/pages").glob("*/visuals/*/visual.json"))
    review = json.loads((output / "looker-powerbi-review.json").read_text(encoding="utf-8"))
    assert review["status"] == "review_required"
    assert any(item["code"] == "explore_and_security_not_fully_represented"
               for item in review["ingestion_diagnostics"])
    assert not any(item["code"].endswith("_missing_or_invalid")
                   for item in review["ingestion_diagnostics"])


def test_common_visuals_migrate_end_to_end_offline(inputs, tmp_path, monkeypatch):
    sibling = Path(__file__).resolve().parents[2] / "TableauToPowerBI"
    if (sibling / "powerbi_import" / "pbip_generator.py").is_file():
        monkeypatch.syspath_prepend(str(sibling))
    if (importlib.util.find_spec("powerbi_import") is None
            or importlib.util.find_spec("tableau_export") is None):
        pytest.skip("optional TableauToPowerBI packages are unavailable")
    inventory, payload = inputs
    source = json.loads(payload.read_text(encoding="utf-8"))
    fields = source["explores"][0]["fields"]
    fields["dimensions"].append({
        "name": "orders.amount", "view": "orders", "type": "number",
        "sql": "${TABLE}.amount", "sql_case": None, "dimension_group": None,
    })
    fields["measures"].append({
        "name": "orders.sales", "view": "orders", "type": "sum",
        "sql": "${TABLE}.amount", "sql_case": None, "dimension_group": None, "filters": [],
    })
    template = source["dashboards"][0]["dashboard_elements"][0]
    elements = []
    for title, visual_type, query_fields in (
        ("Trend", "looker_line", ["orders.region", "orders.sales"]),
        ("Columns", "looker_column", ["orders.region", "orders.sales"]),
        ("KPI", "single_value", ["orders.sales"]),
    ):
        element = copy.deepcopy(template)
        element["title"] = title
        element["query"]["fields"] = query_fields
        element["query"]["vis_config"] = {"type": visual_type}
        elements.append(element)
    source["dashboards"][0]["dashboard_elements"] = elements
    payload.write_text(json.dumps(source), encoding="utf-8")

    def no_network(*args, **kwargs):
        raise AssertionError("offline only")

    monkeypatch.setattr("socket.socket.connect", no_network)
    imported, output, again = tmp_path / "imported.json", tmp_path / "project", tmp_path / "again"
    assert cli.main(import_command(inventory, payload, imported)) == ExitCode.SUCCESS
    assert cli.main(generate_command(imported, output)) == ExitCode.SUCCESS
    assert cli.main(generate_command(imported, again)) == ExitCode.SUCCESS
    assert {p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()} == {
        p.relative_to(again): p.read_bytes() for p in again.rglob("*") if p.is_file()
    }

    report = output / "LookerMigration.Report" / "definition"
    visuals = [
        json.loads(p.read_text(encoding="utf-8"))["visual"]
        for p in report.glob("pages/*/visuals/*/visual.json")
    ]
    assert len(visuals) == 3
    assert {visual["visualType"] for visual in visuals} == {
        "lineChart", "clusteredColumnChart", "cardVisual",
    }
    for visual in visuals:
        query = visual["query"]["queryState"]
        if visual["visualType"] == "cardVisual":
            expected_roles = {"Data": ("Measure", "sales")}
        else:
            expected_roles = {"Category": ("Column", "region"), "Y": ("Measure", "sales")}
        assert set(query) == set(expected_roles)
        for role, (field_type, field_name) in expected_roles.items():
            projections = query[role]["projections"]
            assert len(projections) == 1
            projection = projections[0]
            assert projection["field"][field_type] == {
                "Expression": {"SourceRef": {"Entity": "orders"}}, "Property": field_name,
            }
            assert projection["queryRef"] == f"orders.{field_name}"
            assert projection["nativeQueryRef"] == field_name
    schema_validator = importlib.import_module("powerbi_import.schema_validator")
    schema_results = schema_validator.validate_report_dir(str(report))
    assert schema_results and all(result.ok for result in schema_results)
    assert sum(result.artifact_type == "visual" for result in schema_results) == 3
    openability = importlib.import_module("powerbi_import.openability")
    result = openability.check_openability(str(output))
    assert result.openable, result.blocking_issues
    assert result.to_dict()["refresh_verification"] == "not_run"
    review = json.loads((output / "looker-powerbi-review.json").read_text(encoding="utf-8"))
    assert review["runtime"] == review["parity"] == "not_run"
    assert review["security"] == "not_migrated_unverified"

    elements[0]["query"]["vis_config"]["extra"] = "private_config_value"
    elements[1]["query"]["filters"] = {"orders.region": "private_filter_value"}
    del elements[2]["query"]["limit"]
    payload.write_text(json.dumps(source), encoding="utf-8")
    blocked_inventory, blocked_output = tmp_path / "blocked.json", tmp_path / "blocked"
    assert cli.main(import_command(inventory, payload, blocked_inventory)) == ExitCode.SUCCESS
    assert cli.main(generate_command(blocked_inventory, blocked_output)) == ExitCode.SUCCESS
    assert not list((blocked_output / "LookerMigration.Report" / "definition")
                    .glob("pages/*/visuals/*/visual.json"))
    blocked_review = json.loads(
        (blocked_output / "looker-powerbi-review.json").read_text(encoding="utf-8")
    )
    assert {
        "visual_configuration_not_migrated", "query_semantics_not_migrated",
        "query_semantics_evidence_missing_or_invalid",
    } <= {item["code"] for item in blocked_review["ingestion_diagnostics"]}
    assert "private_config_value" not in blocked_inventory.read_text(encoding="utf-8")
    assert "private_filter_value" not in blocked_inventory.read_text(encoding="utf-8")
    for path in blocked_output.rglob("*"):
        if path.is_file():
            contents = path.read_text(encoding="utf-8")
            assert "private_config_value" not in contents
            assert "private_filter_value" not in contents


def test_empty_api_export_retains_ingestion_review(inputs, tmp_path, monkeypatch, capsys):
    inventory, payload = inputs
    payload.write_text('{"explores": [], "dashboards": []}', encoding="utf-8")
    imported, output = tmp_path / "imported.json", tmp_path / "project"
    assert cli.main(import_command(inventory, payload, imported)) == ExitCode.SUCCESS
    monkeypatch.setattr("bqtofabric.generator.looker_powerbi._load_backend",
                        lambda: (None, None, None))
    assert cli.main(generate_command(imported, output)) == ExitCode.VALIDATION_FAILED
    assert "no project generated" in capsys.readouterr().out.lower()
    review = json.loads((output / "looker-powerbi-review.json").read_text(encoding="utf-8"))
    assert {item["code"] for item in review["ingestion_diagnostics"]} == {
        "no_explore_responses", "no_dashboard_responses",
    }


def test_real_faa_linked_looks_are_reported_without_project(inputs, tmp_path, monkeypatch, capsys):
    inventory, payload = inputs
    fixture = (Path(__file__).resolve().parents[1] / "examples" / "looker" / "looker-cli"
               / "Dashboard_17_FAA_KPIs.json")
    dashboard = json.loads(fixture.read_text(encoding="utf-8"))
    payload.write_text(json.dumps({"explores": [], "dashboards": [dashboard]}), encoding="utf-8")
    imported, output = tmp_path / "imported.json", tmp_path / "project"
    assert cli.main(import_command(inventory, payload, imported)) == ExitCode.SUCCESS
    monkeypatch.setattr(looker_powerbi, "_load_backend", lambda: (None, None, None))
    assert cli.main(generate_command(imported, output)) == ExitCode.VALIDATION_FAILED
    assert "no project generated" in capsys.readouterr().out.lower()
    assert {path.name for path in output.iterdir()} == {"looker-powerbi-review.json"}
    review = json.loads((output / "looker-powerbi-review.json").read_text(encoding="utf-8"))
    assert review["status"] == "review_required"
    assert review["runtime"] == review["parity"] == "not_run"
    assert review["converted"] == []
    assert any(issue["code"] == "no_convertible_model" for issue in review["issues"])
    diagnostics = review["ingestion_diagnostics"]
    linked = [item for item in diagnostics if item["code"] == "linked_look_not_migrated"]
    assert len(linked) == 2
    assert len({item["path"] for item in linked}) == 2
    assert not any(item["code"] == "invalid_element"
                   and item["path"] in {entry["path"] for entry in linked}
                   for item in diagnostics)
    assert all(set(item) == {"path", "code"} for item in diagnostics)


def test_sensitive_payload_values_do_not_appear_in_review(inputs, tmp_path, monkeypatch):
    inventory, payload = inputs
    document = json.loads(payload.read_text(encoding="utf-8"))
    document["explores"][0]["access_filters"] = [{"value": "source_secret_value"}]
    payload.write_text(json.dumps(document), encoding="utf-8")
    imported, output = tmp_path / "imported.json", tmp_path / "project"
    assert cli.main(import_command(inventory, payload, imported)) == ExitCode.SUCCESS
    monkeypatch.setattr(cli, "generate_looker_powerbi_project", lambda *args, **kwargs:
                        SimpleNamespace(files={"project.pbip": "project"}, review={"issues": []}))
    assert cli.main(generate_command(imported, output)) == ExitCode.SUCCESS
    review = (output / "looker-powerbi-review.json").read_text(encoding="utf-8")
    assert "source_secret_value" not in review
    assert "access_filters_not_migrated" in review


@pytest.mark.parametrize("missing", [
    "sql_always_where", "access_grants", "required_access_grants",
])
def test_missing_security_evidence_blocks_visuals_end_to_end(
    inputs, tmp_path, monkeypatch, missing
):
    inventory, payload = inputs
    document = json.loads(payload.read_text(encoding="utf-8"))
    del document["explores"][0][missing]
    document["dashboards"][0]["dashboard_elements"][0]["query"]["share_url"] = (
        "source_secret_value"
    )
    payload.write_text(json.dumps(document), encoding="utf-8")
    imported, output = tmp_path / "imported.json", tmp_path / "project"
    assert cli.main(import_command(inventory, payload, imported)) == ExitCode.SUCCESS
    stored = json.loads(imported.read_text(encoding="utf-8"))
    asset = stored["components"][-1]
    assert asset["properties"]["security"]
    pages_seen = []

    def render(pbip, tmdl, visual_backend, name, tables, pages):
        pages_seen.extend(pages)
        return {"LookerMigration.pbip": "review scaffold"}

    monkeypatch.setattr(looker_powerbi, "_load_backend", lambda: (None, None, None))
    monkeypatch.setattr(looker_powerbi, "_render", render)
    assert cli.main(generate_command(imported, output)) == ExitCode.SUCCESS
    assert pages_seen and all(not page[2] for page in pages_seen)
    review_text = (output / "looker-powerbi-review.json").read_text(encoding="utf-8")
    review = json.loads(review_text)
    assert any(item["code"].startswith(missing + "_")
               for item in review["ingestion_diagnostics"])
    assert any(item["code"] == "security_not_migrated" for item in review["issues"])
    assert "source_secret_value" not in imported.read_text(encoding="utf-8")
    assert "source_secret_value" not in review_text


def test_unknown_explore_context_blocks_visuals_without_copying_values(inputs, tmp_path, monkeypatch):
    inventory, payload = inputs
    document = json.loads(payload.read_text(encoding="utf-8"))
    document["explores"][0]["unrecognized_context"] = "source_secret_value"
    payload.write_text(json.dumps(document), encoding="utf-8")
    imported, output = tmp_path / "imported.json", tmp_path / "project"
    assert cli.main(import_command(inventory, payload, imported)) == ExitCode.SUCCESS
    asset = json.loads(imported.read_text(encoding="utf-8"))["components"][-1]
    assert asset["properties"]["explores"]
    pages_seen = []

    def render(pbip, tmdl, visual_backend, name, tables, pages):
        pages_seen.extend(pages)
        return {"LookerMigration.pbip": "review scaffold"}

    monkeypatch.setattr(looker_powerbi, "_load_backend", lambda: (None, None, None))
    monkeypatch.setattr(looker_powerbi, "_render", render)
    assert cli.main(generate_command(imported, output)) == ExitCode.SUCCESS
    assert pages_seen and all(not page[2] for page in pages_seen)
    review_text = (output / "looker-powerbi-review.json").read_text(encoding="utf-8")
    review = json.loads(review_text)
    assert any(item["code"] == "unknown_explore_property"
               for item in review["ingestion_diagnostics"])
    assert any(item["code"] == "unresolved_model_context" for item in review["issues"])
    assert "source_secret_value" not in imported.read_text(encoding="utf-8")
    assert "source_secret_value" not in review_text


@pytest.mark.parametrize("case", ["missing_security", "unknown_context"])
def test_real_backend_blocks_incomplete_context(inputs, tmp_path, monkeypatch, case):
    sibling = Path(__file__).resolve().parents[2] / "TableauToPowerBI"
    if (sibling / "powerbi_import" / "pbip_generator.py").is_file():
        monkeypatch.syspath_prepend(str(sibling))
    if (importlib.util.find_spec("powerbi_import") is None
            or importlib.util.find_spec("tableau_export") is None):
        pytest.skip("optional TableauToPowerBI packages are unavailable")
    inventory, payload = inputs
    document = json.loads(payload.read_text(encoding="utf-8"))
    if case == "missing_security":
        del document["explores"][0]["sql_always_where"]
        document["dashboards"][0]["dashboard_elements"][0]["query"]["share_url"] = (
            "source_secret_value"
        )
        code = "sql_always_where_missing_or_invalid"
    else:
        document["explores"][0]["unrecognized_context"] = "source_secret_value"
        code = "unknown_explore_property"
    payload.write_text(json.dumps(document), encoding="utf-8")
    imported, output = tmp_path / "imported.json", tmp_path / "project"
    assert cli.main(import_command(inventory, payload, imported)) == ExitCode.SUCCESS
    assert cli.main(generate_command(imported, output)) == ExitCode.SUCCESS
    assert (output / "LookerMigration.pbip").is_file()
    assert not list((output / "LookerMigration.Report/definition/pages").glob(
        "*/visuals/*/visual.json"
    ))
    review = json.loads((output / "looker-powerbi-review.json").read_text(encoding="utf-8"))
    assert any(item["code"] == code for item in review["ingestion_diagnostics"])
    assert "source_secret_value" not in imported.read_text(encoding="utf-8")
    for path in output.rglob("*"):
        if path.is_file():
            assert "source_secret_value" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("target", ["inventory", "payload", "existing"])
def test_import_never_overwrites_files(inputs, tmp_path, target):
    inventory, payload = inputs
    existing = tmp_path / "existing"
    existing.write_text("keep", encoding="utf-8")
    output = {"inventory": inventory, "payload": payload, "existing": existing}[target]
    before = output.read_bytes()
    assert cli.main(import_command(inventory, payload, output)) == ExitCode.VALIDATION_FAILED
    assert output.read_bytes() == before


def test_import_rejects_output_symlink(inputs, tmp_path):
    inventory, payload = inputs
    output = tmp_path / "symlink"
    try:
        output.symlink_to(payload)
    except OSError:
        pytest.skip("symlinks unavailable")
    before = payload.read_bytes()
    assert cli.main(import_command(inventory, payload, output)) == ExitCode.VALIDATION_FAILED
    assert payload.read_bytes() == before


@pytest.mark.parametrize("location", ["components", "dataset"])
def test_duplicate_source_id_rejected(inputs, tmp_path, location):
    inventory, payload = inputs
    document = json.loads(inventory.read_text(encoding="utf-8"))
    duplicate = {"source_id": "project.looker.api_export", "name": "existing", "kind": "table"}
    if location == "components":
        document["components"].append(duplicate)
    else:
        document["datasets"][0]["objects"].append(duplicate)
    inventory.write_text(json.dumps(document), encoding="utf-8")
    output = tmp_path / "result"
    assert cli.main(import_command(inventory, payload, output)) == ExitCode.VALIDATION_FAILED
    assert not output.exists()


LOOKML_PROJECT = "analytics"
LOOKML_ASSET_ID = f"{LOOKML_PROJECT}.looker_lookml_export"
LOOKML_EXPLORE_ID = f"{LOOKML_PROJECT}.looker_lookml.explore.orders"
LOOKML_FIELD_ID = f"{LOOKML_PROJECT}.looker_lookml.field.orders.region"


def lookml_inventory_document() -> dict:
    return {
        "project_id": LOOKML_PROJECT,
        "schema_version": "1.0",
        "metadata": {"preserved": True},
        "datasets": [],
        "components": [{
            "source_id": "existing.component",
            "name": "existing",
            "kind": "stream",
        }],
    }


def lookml_payload_document() -> dict:
    return {
        "schema_version": "1.0",
        "project_id": LOOKML_PROJECT,
        "explores": [{
            "source_id": LOOKML_EXPLORE_ID,
            "name": "orders",
            "sql_table_name": "warehouse.sales.orders",
            "dimensions": [{
                "source_id": LOOKML_FIELD_ID,
                "name": "region",
                "type": "string",
                "sql": "${TABLE}.region",
            }],
            "measures": [],
        }],
        "dashboards": [],
    }


def write_lookml_inputs(tmp_path: Path) -> tuple[Path, Path]:
    inventory = tmp_path / "lookml-inventory.json"
    payload = tmp_path / "lookml-payload.json"
    inventory.write_text(json.dumps(lookml_inventory_document()), encoding="utf-8")
    payload.write_text(json.dumps(lookml_payload_document()), encoding="utf-8")
    return inventory, payload


def lookml_import_command(inventory: Path, payload: Path, output: Path) -> list[str]:
    return [
        "import-looker-lookml", str(inventory), "--payload", str(payload), "--output", str(output),
    ]


def test_lookml_import_appends_one_asset_deterministically_without_network(
    tmp_path, monkeypatch
):
    inventory, payload = write_lookml_inputs(tmp_path)
    original_inventory = inventory.read_bytes()
    original_payload = payload.read_bytes()

    def no_network(*args, **kwargs):
        raise AssertionError("LookML import must remain offline")

    monkeypatch.setattr("socket.socket.connect", no_network)
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    assert cli.main(lookml_import_command(inventory, payload, first)) == ExitCode.SUCCESS
    assert inventory.read_bytes() == original_inventory
    assert payload.read_bytes() == original_payload

    document = json.loads(first.read_text(encoding="utf-8"))
    assert document["metadata"] == {"preserved": True}
    assert len(document["components"]) == 2
    assert document["components"][0]["source_id"] == "existing.component"
    asset = document["components"][1]
    assert asset["source_id"] == LOOKML_ASSET_ID
    assert asset["kind"] == "looker_asset"
    assert asset["discovered_from"] == "external_payload"
    assert cli.main(lookml_import_command(inventory, payload, second)) == ExitCode.SUCCESS
    assert first.read_bytes() == second.read_bytes()


def test_lookml_import_rejects_mismatched_project_without_output(tmp_path, capsys):
    inventory, payload = write_lookml_inputs(tmp_path)
    document = lookml_payload_document()
    document["project_id"] = "different-project"
    payload.write_text(json.dumps(document), encoding="utf-8")
    output = tmp_path / "result.json"

    assert cli.main(lookml_import_command(inventory, payload, output)) == ExitCode.VALIDATION_FAILED
    assert "Invalid Looker LookML payload or project identifier" in capsys.readouterr().out
    assert not output.exists()


@pytest.mark.parametrize("bad_payload", ["{", "[]", '{"schema_version":"2.0"}'])
def test_lookml_import_rejects_invalid_payload(tmp_path, capsys, bad_payload):
    inventory, payload = write_lookml_inputs(tmp_path)
    payload.write_text(bad_payload, encoding="utf-8")
    output = tmp_path / "result.json"

    assert cli.main(lookml_import_command(inventory, payload, output)) == ExitCode.VALIDATION_FAILED
    assert "Invalid Looker LookML payload or project identifier" in capsys.readouterr().out
    assert not output.exists()


@pytest.mark.parametrize("missing", ["inventory", "payload"])
def test_lookml_import_reports_missing_input_with_file_not_found(
    tmp_path, capsys, missing
):
    inventory, payload = write_lookml_inputs(tmp_path)
    if missing == "inventory":
        inventory = tmp_path / "missing-inventory.json"
        message = "Inventory file not found"
    else:
        payload = tmp_path / "missing-payload.json"
        message = "Looker LookML payload file not found"
    output = tmp_path / "result.json"

    assert cli.main(lookml_import_command(inventory, payload, output)) == ExitCode.FILE_NOT_FOUND
    assert message in capsys.readouterr().out
    assert not output.exists()


def test_lookml_import_does_not_overwrite_existing_output(tmp_path, capsys):
    inventory, payload = write_lookml_inputs(tmp_path)
    output = tmp_path / "existing.json"
    output.write_text("keep this file", encoding="utf-8")
    before = output.read_bytes()

    assert cli.main(lookml_import_command(inventory, payload, output)) == ExitCode.VALIDATION_FAILED
    assert "Output already exists; no files were overwritten" in capsys.readouterr().out
    assert output.read_bytes() == before


def test_lookml_import_rejects_duplicate_imported_source_id(tmp_path, capsys):
    inventory, payload = write_lookml_inputs(tmp_path)
    document = lookml_inventory_document()
    document["components"].append({
        "source_id": LOOKML_ASSET_ID,
        "name": "already imported",
        "kind": "looker_asset",
    })
    inventory.write_text(json.dumps(document), encoding="utf-8")
    output = tmp_path / "result.json"

    assert cli.main(lookml_import_command(inventory, payload, output)) == ExitCode.VALIDATION_FAILED
    assert "Inventory already contains the Looker LookML asset source_id" in capsys.readouterr().out
    assert not output.exists()


@pytest.mark.parametrize("bad", ["{", "[]", '{"explores": [], "dashboards": {}}'])
def test_invalid_payload(inputs, tmp_path, bad, capsys):
    inventory, payload = inputs
    payload.write_text(bad, encoding="utf-8")
    output = tmp_path / "result"
    assert cli.main(import_command(inventory, payload, output)) == ExitCode.VALIDATION_FAILED
    assert "Invalid Looker API payload" in capsys.readouterr().out
    assert not output.exists()


def test_missing_inputs_and_invalid_inventory(inputs, tmp_path):
    inventory, payload = inputs
    output = tmp_path / "result"
    assert cli.main(import_command(tmp_path / "missing", payload, output)) == ExitCode.FILE_NOT_FOUND
    assert cli.main(import_command(inventory, tmp_path / "missing", output)) == ExitCode.FILE_NOT_FOUND
    inventory.write_text('{"project_id": "project", "components": [1]}', encoding="utf-8")
    assert cli.main(import_command(inventory, payload, output)) == ExitCode.VALIDATION_FAILED
    assert not output.exists()


@pytest.mark.parametrize("label", [
    "not-json", "{}", '[{"path":"explores[0]","code":"secret_value"}]',
    '[{"path":"secret_value","code":"expected_object"}]',
    '[{"path":"explores[0]","code":"expected_object","data":"secret_value"}]',
])
def test_untrusted_diagnostics_are_rejected(inputs, tmp_path, monkeypatch, capsys, label):
    inventory, payload = inputs
    imported = tmp_path / "imported.json"
    assert cli.main(import_command(inventory, payload, imported)) == ExitCode.SUCCESS
    document = json.loads(imported.read_text(encoding="utf-8"))
    document["components"][-1]["labels"]["looker_ingestion_report"] = label
    imported.write_text(json.dumps(document), encoding="utf-8")

    def unexpected(*args, **kwargs):
        pytest.fail("generator should not be called")

    monkeypatch.setattr(cli, "generate_looker_powerbi_project", unexpected)
    output = tmp_path / "project"
    assert cli.main(generate_command(imported, output)) == ExitCode.VALIDATION_FAILED
    assert "secret_value" not in capsys.readouterr().out
    assert not output.exists()


def test_import_help(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["import-looker-api", "--help"])
    assert exc.value.code == 0
    assert "without cloud calls" in capsys.readouterr().out
