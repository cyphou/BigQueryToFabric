import json
from pathlib import Path

import pytest

from bqtofabric.assessment import run_assessment
from bqtofabric.cli import main
from bqtofabric.exported_metadata import SERVICES, merge_export, normalize_export
from bqtofabric.models import BigQueryInventory

EXPORTS = json.loads(
    (Path(__file__).parent / "fixtures" / "gcp_exports.json").read_text(encoding="utf-8")
)
EMPTY = {"project_id": "demo-project", "datasets": []}


def test_every_service_has_a_fixture_traced_to_its_api_reference() -> None:
    assert set(EXPORTS) == set(SERVICES)
    for service, entry in EXPORTS.items():
        assert entry["reference"].startswith("https://cloud.google.com/"), service


@pytest.mark.parametrize("service", sorted(SERVICES))
def test_export_normalizes_to_one_redacted_external_payload_component(service: str) -> None:
    (component,) = normalize_export("demo-project", service, EXPORTS[service]["payload"])

    assert component.discovered_from == "external_payload"
    assert component.source_id.startswith(f"demo-project.{service}.")
    assert component.properties["export"]["service"] == service
    assert "serviceAccount" not in json.dumps(component.properties)
    assert "gserviceaccount" not in json.dumps(component.properties)


def test_extracted_evidence_uses_documented_fields_only() -> None:
    by_service = {
        service: normalize_export("demo-project", service, EXPORTS[service]["payload"])[0].properties
        for service in SERVICES
    }

    assert by_service["pubsub"]["message_retention"] == "604800s"
    assert by_service["pubsub"]["cmek"] is True
    assert by_service["cloudsql"] == {
        "engine": "POSTGRES", "version": "15", "replication": True,
        "export": {"service": "cloudsql", "resource": "orders-db"},
    }
    assert by_service["vertex"]["pipeline_steps"] == ["deploy", "evaluate", "train"]
    assert by_service["dataplex"]["zone"] == "core/raw"
    assert by_service["looker"]["explores"] == ["customers", "orders"]
    assert "subscriptions" not in by_service["pubsub"]
    assert "triggers" not in by_service["workflows"]


def test_fields_a_list_method_cannot_return_surface_as_missing_evidence() -> None:
    inventory = EMPTY
    for service in sorted(SERVICES):
        inventory = merge_export(inventory, service, EXPORTS[service]["payload"])
    report = run_assessment(BigQueryInventory.from_dict(inventory))
    missing: dict[str, list[str]] = {}
    for source_id, value in report.evidence_summary.items():
        fields = value.get("missing")
        if isinstance(fields, list) and fields:
            missing[source_id] = [str(field) for field in fields]

    assert "subscriptions" in missing["demo-project.pubsub.orders"]
    assert "triggers" in missing["demo-project.workflows.notify"]
    assert "data_format" in missing["demo-project.gcs.demo-raw"]
    assert {"measures", "joins"} <= set(missing["demo-project.looker.commerce"])
    assert "demo-project.dataplex.landing" not in missing


def test_merge_replaces_by_source_id_and_is_deterministic() -> None:
    once = merge_export(EMPTY, "gcs", EXPORTS["gcs"]["payload"])
    twice = merge_export(once, "gcs", EXPORTS["gcs"]["payload"])

    assert once == twice
    assert len(twice["components"]) == 1
    assert "components" not in EMPTY


def test_unknown_service_and_malformed_payload_are_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_export("demo-project", "bigtable", {})
    with pytest.raises(TypeError):
        normalize_export("demo-project", "pubsub", {"topics": "nope"})


def test_cli_import_export(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps(EMPTY), encoding="utf-8")
    payload = tmp_path / "topics.json"
    payload.write_text(json.dumps(EXPORTS["pubsub"]["payload"]), encoding="utf-8")
    output = tmp_path / "merged.json"

    args = ["import-export", str(inventory), "--service", "pubsub", "--payload", str(payload), "--output", str(output)]
    assert main(args) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["components"][0]["kind"] == "pubsub_topic"

    payload.write_text(json.dumps({"topics": "nope"}), encoding="utf-8")
    assert main(args) == 5
