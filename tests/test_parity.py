from bqtofabric.parity import assess_parity, compare_row_count, compare_schema


def test_compare_row_count_is_explicit_about_missing_runtime_evidence() -> None:
    assert compare_row_count(None, 10)["status"] == "not_run"
    assert compare_row_count(10, 10)["status"] == "passed"
    assert compare_row_count(10, 9)["status"] == "failed"


def test_compare_schema_reports_type_and_missing_column_differences() -> None:
    source = [
        {"name": "id", "data_type": "INT64", "nullable": False, "mode": "REQUIRED"},
        {"name": "amount", "data_type": "NUMERIC", "nullable": True, "mode": "NULLABLE"},
    ]
    target = [{"name": "id", "data_type": "STRING", "nullable": False, "mode": "REQUIRED"}]

    result = compare_schema(source, target)

    assert result["status"] == "failed"
    assert [item["column"] for item in result["differences"]] == ["amount", "id"]


def test_compare_schema_walks_nested_fields() -> None:
    source = [{
        "name": "payload",
        "data_type": "STRUCT",
        "fields": [{"name": "sku", "data_type": "STRING"}],
    }]
    target = [{
        "name": "payload",
        "data_type": "STRUCT",
        "fields": [{"name": "sku", "data_type": "INT64"}],
    }]

    result = compare_schema(source, target)

    assert result["differences"] == [{
        "column": "payload.sku",
        "field": "data_type",
        "source": "STRING",
        "target": "INT64",
    }]


def test_parity_requires_runtime_evidence_for_passed_status() -> None:
    result = assess_parity({"parity": {"schema": {"status": "passed"}}})

    assert result["status"] == "not_run"
    assert result["checks"]["row_count"]["status"] == "not_run"


def test_parity_failed_check_wins_over_not_run_checks() -> None:
    result = assess_parity({"parity": {
        "schema": {"status": "passed"},
        "row_count": {"status": "failed", "source": 10, "target": 9},
        "checksum": {"status": "not_run", "algorithm": "sha256"},
    }})

    assert result["status"] == "failed"
    assert result["checks"]["row_count"]["target"] == 9


def test_parity_can_be_not_applicable() -> None:
    assert assess_parity({}, applicable=False)["status"] == "not_applicable"