from bqtofabric.fabric_artifacts import build_specialized_artifacts
from bqtofabric.mapping import map_component
from bqtofabric.models import BigQueryInventory


def test_specialized_fabric_artifacts_use_review_placeholders() -> None:
    inventory = BigQueryInventory.from_dict({
        "project_id": "demo",
        "components": [
            {"source_id": "demo.events", "name": "events", "kind": "stream"},
            {"source_id": "demo.catalog", "name": "catalog", "kind": "dataplex_asset"},
        ],
    })
    decisions = tuple(map_component(item) for item in inventory.objects())

    artifacts = build_specialized_artifacts(inventory, decisions)

    assert artifacts["eventhouse_eventstream_spec"]["mode"] == "dry-run"
    event = artifacts["eventhouse_eventstream_spec"]["items"][0]
    assert event["fields"]["retention"] == "review_required"
    assert artifacts["purview_governance_spec"]["items"][0]["status"] == "review_required"