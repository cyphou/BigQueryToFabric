from bqtofabric.inventory import JsonInventoryProvider
from bqtofabric.models import BigQueryInventory, ObjectKind


def test_inventory_round_trip_preserves_nested_schema() -> None:
    source = {
        "schema_version": "1.0",
        "project_id": "retail-analytics",
        "datasets": [
            {
                "source_id": "retail-analytics.sales",
                "name": "sales",
                "location": "EU",
                "objects": [
                    {
                        "source_id": "retail-analytics.sales.orders",
                        "name": "orders",
                        "kind": "table",
                        "dataset": "sales",
                        "columns": [
                            {"name": "order_id", "data_type": "INT64", "nullable": False},
                            {
                                "name": "items",
                                "data_type": "STRUCT",
                                "mode": "REPEATED",
                                "fields": [{"name": "sku", "data_type": "STRING"}],
                            },
                        ],
                    }
                ],
            }
        ],
    }

    inventory = BigQueryInventory.from_dict(source)

    assert inventory.objects()[0].kind is ObjectKind.TABLE
    assert inventory.objects()[0].discovered_from == "inventory"
    assert inventory.objects()[0].columns[1].fields[0].name == "sku"
    assert BigQueryInventory.from_dict(inventory.to_dict()) == inventory


def test_inventory_contract_rejects_duplicate_ids_and_invalid_columns(tmp_path) -> None:
    duplicate = {
        "project_id": "demo",
        "datasets": [{
            "source_id": "demo.data",
            "name": "data",
            "objects": [{"source_id": "demo.data.x", "name": "x", "kind": "table"}],
        }],
        "components": [{"source_id": "demo.data.x", "name": "x", "kind": "table"}],
    }
    path = tmp_path / "invalid.json"
    path.write_text(__import__("json").dumps(duplicate), encoding="utf-8")

    try:
        JsonInventoryProvider(path).load()
    except ValueError as error:
        assert "Duplicate inventory source_id" in str(error)
    else:
        raise AssertionError("Expected duplicate source IDs to be rejected")