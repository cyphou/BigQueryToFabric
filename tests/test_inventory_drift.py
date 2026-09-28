import json
from pathlib import Path

from bqtofabric.inventory_drift import inventory_drift
from bqtofabric.models import BigQueryInventory

FIXTURE = Path(__file__).parent / "fixtures" / "gcp_ecosystem_project.json"


def _load() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_identical_inventories_report_no_drift() -> None:
    inventory = BigQueryInventory.from_dict(_load())

    assert inventory_drift(inventory, inventory)["status"] == "no_drift"


def test_added_removed_and_changed_components_are_reported() -> None:
    baseline = _load()
    current = _load()
    first = current["datasets"][0]["objects"][0]
    first["size_bytes"] = (first.get("size_bytes") or 0) + 1
    first.setdefault("properties", {})["runtime_note"] = "live"
    removed = current["datasets"][0]["objects"].pop()
    current.setdefault("components", []).append(
        {"source_id": "gcp-data-platform.pubsub.new_topic", "name": "new_topic", "kind": "pubsub_topic"}
    )

    drift = inventory_drift(BigQueryInventory.from_dict(baseline), BigQueryInventory.from_dict(current))

    assert drift["status"] == "drift_detected"
    assert drift["added"] == ["gcp-data-platform.pubsub.new_topic"]
    assert drift["removed"] == [removed["source_id"]]
    assert drift["changed"] == [
        {"sourceId": first["source_id"], "fields": ["size_bytes", "properties.runtime_note"]}
    ]
