from bqtofabric.parity import (
    assess_parity,
    compare_aggregates,
    compare_checksums,
    compare_null_distributions,
    compare_row_count,
    compare_samples,
    compare_schema,
    compare_sql_results,
)


def test_compare_row_count_is_explicit_about_missing_runtime_evidence() -> None:
    assert compare_row_count(None, 10)["status"] == "not_run"
    assert compare_row_count(10, 10)["status"] == "passed"
    assert compare_row_count(10, 9)["status"] == "failed"


def test_compare_aggregates_reports_missing_and_different_metrics() -> None:
    result = compare_aggregates(
        {"sum_amount": 100, "distinct_customer_count": 3},
        {"sum_amount": 99, "max_amount": 50},
    )

    assert result["status"] == "failed"
    assert result["differences"] == [
        {"metric": "distinct_customer_count", "source": 3, "target": None},
        {"metric": "max_amount", "source": None, "target": 50},
        {"metric": "sum_amount", "source": 100, "target": 99},
    ]


def test_compare_aggregates_requires_both_evidence_sets() -> None:
    assert compare_aggregates(None, {"sum_amount": 100})["status"] == "not_run"
    assert compare_aggregates({"sum_amount": 100}, {"sum_amount": 100})["status"] == "passed"


def test_compare_checksums_requires_matching_algorithm_and_ordering() -> None:
    source = {"algorithm": "sha256", "ordering": "id ASC", "value": "abc123"}

    assert compare_checksums(source, source)["status"] == "passed"
    result = compare_checksums(
        source,
        {"algorithm": "sha256", "ordering": "id DESC", "value": "abc123"},
    )

    assert result["status"] == "failed"
    assert result["differences"] == [
        {"field": "ordering", "source": "id ASC", "target": "id DESC"}
    ]


def test_compare_checksums_requires_complete_runtime_evidence() -> None:
    assert compare_checksums(None, {"value": "abc123"})["status"] == "not_run"
    assert compare_checksums(
        {"algorithm": "sha256", "value": "abc123"},
        {"algorithm": "sha256", "ordering": "id ASC", "value": "abc123"},
    )["status"] == "not_run"


def test_compare_null_distributions_reports_missing_and_changed_evidence() -> None:
    result = compare_null_distributions(
        {
            "customer_id": {"null_count": 0, "row_count": 100},
            "note": {"null_count": 20, "row_count": 100},
        },
        {
            "customer_id": {"null_count": 1, "row_count": 100},
            "status": {"null_count": 0, "row_count": 100},
        },
    )

    assert result["status"] == "failed"
    assert result["differences"] == [
        {"column": "customer_id", "field": "null_count", "source": 0, "target": 1},
        {"column": "note", "reason": "missing_column"},
        {"column": "status", "reason": "missing_column"},
    ]


def test_compare_null_distributions_requires_complete_consistent_evidence() -> None:
    assert compare_null_distributions(None, {})["status"] == "not_run"
    assert compare_null_distributions(
        {"note": {"null_count": 101, "row_count": 100}},
        {"note": {"null_count": 100, "row_count": 100}},
    )["status"] == "not_run"
    assert compare_null_distributions(
        {"note": {"null_count": 20, "row_count": 100}},
        {"note": {"null_count": 20, "row_count": 100}},
    )["status"] == "passed"


def test_compare_samples_requires_matching_selection_contract_and_rows() -> None:
    source = {
        "method": "deterministic_key_range",
        "ordering": "customer_id ASC",
        "rows": [{"customer_id": "C001", "status": "active"}],
    }

    assert compare_samples(source, source)["status"] == "passed"
    result = compare_samples(
        source,
        {
            "method": "deterministic_key_range",
            "ordering": "customer_id DESC",
            "rows": [{"customer_id": "C001", "status": "inactive"}],
        },
    )

    assert result["status"] == "failed"
    assert [difference["field"] for difference in result["differences"]] == ["ordering", "rows"]


def test_compare_samples_requires_complete_runtime_evidence() -> None:
    assert compare_samples(None, {"rows": []})["status"] == "not_run"
    assert compare_samples(
        {"method": "deterministic_key_range", "rows": []},
        {"method": "deterministic_key_range", "ordering": "id ASC", "rows": []},
    )["status"] == "not_run"


def test_compare_sql_results_requires_same_approved_query_and_rows() -> None:
    source = {
        "query_id": "daily_event_counts",
        "ordering": "event_date ASC",
        "rows": [{"event_date": "2026-01-01", "event_count": 12}],
    }

    assert compare_sql_results(source, source)["status"] == "passed"
    result = compare_sql_results(
        source,
        {
            "query_id": "monthly_event_counts",
            "ordering": "event_date ASC",
            "rows": [{"event_date": "2026-01-01", "event_count": 11}],
        },
    )

    assert result["status"] == "failed"
    assert [difference["field"] for difference in result["differences"]] == ["query_id", "rows"]


def test_compare_sql_results_requires_complete_runtime_evidence() -> None:
    assert compare_sql_results(None, {"rows": []})["status"] == "not_run"
    assert compare_sql_results(
        {"query_id": "daily_event_counts", "rows": []},
        {"query_id": "daily_event_counts", "ordering": "event_date ASC", "rows": []},
    )["status"] == "not_run"


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