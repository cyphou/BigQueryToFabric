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
    assert inventory.objects()[0].columns[1].fields[0].name == "sku"
    assert BigQueryInventory.from_dict(inventory.to_dict()) == inventory