import json
from pathlib import Path
from typing import Any

from bqtofabric.assessment import run_assessment
from bqtofabric.cli import main
from bqtofabric.inventory import JsonInventoryProvider
from bqtofabric.models import BigQueryInventory
from bqtofabric.parity_pack import build_parity_pack, ingest_parity_results, render_sql

FIXTURE = Path(__file__).parent / "fixtures" / "gcp_ecosystem_project.json"


def _inventory(objects: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "project_id": "demo-project",
        "datasets": [{"source_id": "demo-project.sales", "name": "sales", "location": "US", "objects": objects}],
    }


def _orders(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "source_id": "demo-project.sales.orders",
        "name": "orders",
        "kind": "table",
        "dataset": "sales",
        "columns": [
            {"name": "order_id", "data_type": "INT64", "nullable": False},
            {"name": "amount", "data_type": "NUMERIC"},
            {"name": "note", "data_type": "STRING"},
            {"name": "items", "data_type": "STRUCT", "fields": [{"name": "sku", "data_type": "STRING"}]},
        ],
    }
    value.update(overrides)
    return value


def _pack(raw: dict[str, Any]) -> dict[str, Any]:
    inventory = BigQueryInventory.from_dict(raw)
    return build_parity_pack(inventory, run_assessment(inventory))


def _statuses(raw: dict[str, Any], source_id: str) -> dict[str, str]:
    checks = run_assessment(BigQueryInventory.from_dict(raw)).parity_summary[source_id]["checks"]
    assert isinstance(checks, dict)
    return {name: value["status"] for name, value in checks.items()}


def test_every_not_run_reference_component_gets_a_row_count_query() -> None:
    inventory = JsonInventoryProvider(FIXTURE).load()
    assessment = run_assessment(inventory)
    pack = build_parity_pack(inventory, assessment)

    not_run = {source for source, value in assessment.parity_summary.items() if value["status"] == "not_run"}
    covered = {check["source_id"] for check in pack["checks"] if check["check"] == "row_count"}
    skipped = {entry["source_id"] for entry in pack["skipped"]}

    assert not_run
    assert not_run <= covered | skipped
    assert build_parity_pack(inventory, assessment) == pack


def test_pack_pairs_dialects_and_skips_nested_and_float_columns() -> None:
    checks = {check["check"]: check for check in _pack(_inventory([_orders()]))["checks"]}

    assert set(checks) == {"row_count", "null_distribution", "aggregate"}
    nulls = checks["null_distribution"]
    assert nulls["columns"] == {"n0": "order_id", "n1": "amount", "n2": "note"}
    assert "COUNTIF(`note` IS NULL) AS n2" in nulls["source_sql"]
    assert set(checks["aggregate"]["columns"].values()) == {
        "order_id.sum", "order_id.min", "order_id.max", "amount.sum", "amount.min", "amount.max",
    }
    dialect = nulls["target_dialect"]
    quoted = "[note]" if dialect == "tsql" else "`note`"
    assert f"SUM(CASE WHEN {quoted} IS NULL THEN 1 ELSE 0 END) AS n2" in nulls["target_sql"]


def test_unsafe_identifiers_are_skipped_not_interpolated() -> None:
    pack = _pack(_inventory([_orders(name="orders; DROP TABLE x", source_id="demo-project.sales.bad")]))

    assert pack["checks"] == []
    assert pack["skipped"] == [{"source_id": "demo-project.sales.bad", "reason": "unsafe_identifier"}]


def test_ingest_recomputes_status_and_never_writes_one() -> None:
    raw = _inventory([_orders()])
    pack = _pack(raw)
    results = {
        "pack_id": pack["pack_id"],
        "results": [
            {"query_id": "demo-project.sales.orders:row_count", "source": [{"row_count": "10"}],
             "target": [{"row_count": 10}], "collected_at": "2026-09-28T10:00:00Z"},
            {"query_id": "demo-project.sales.orders:null_distribution",
             "source": {"row_count": 10, "n0": 0, "n1": 2, "n2": 5},
             "target": {"row_count": 10, "n0": 0, "n1": 3, "n2": 5}},
            {"query_id": "demo-project.sales.orders:aggregate", "source": {"a0_sum": "55"}},
        ],
    }

    updated, errors = ingest_parity_results(raw, pack, results)
    parity = updated["datasets"][0]["objects"][0]["properties"]["parity"]
    statuses = _statuses(updated, "demo-project.sales.orders")

    assert errors == []
    assert "status" not in json.dumps(parity)
    assert parity["row_count"]["source"] == 10
    assert parity["row_count"]["collected_at"] == "2026-09-28T10:00:00Z"
    assert "aggregate" not in parity
    assert statuses["row_count"] == "passed"
    assert statuses["null_distribution"] == "failed"
    assert statuses["aggregate"] == "not_run"
    assert "properties" not in raw["datasets"][0]["objects"][0]


def test_ingest_rejects_tampered_pack_foreign_results_and_unknown_queries() -> None:
    raw = _inventory([_orders()])
    pack = _pack(raw)

    tampered = {**pack, "checks": [{**pack["checks"][0], "target_sql": "SELECT 1"}]}
    assert ingest_parity_results(raw, tampered, {"pack_id": pack["pack_id"]})[1] == [
        "pack was modified after generation"
    ]
    assert ingest_parity_results(raw, pack, {"pack_id": "other"})[1] == [
        f"results reference pack 'other', not {pack['pack_id']!r}"
    ]
    unknown = {"pack_id": pack["pack_id"], "results": [{"query_id": "x:row_count"}]}
    assert ingest_parity_results(raw, pack, unknown)[1] == ["x:row_count: not in pack"]


def test_aggregate_values_are_normalized_across_engines() -> None:
    raw = _inventory([_orders()])
    pack = _pack(raw)
    aliases = next(check for check in pack["checks"] if check["check"] == "aggregate")["columns"]
    source = dict.fromkeys(aliases, "100.50")
    target = dict.fromkeys(aliases, 100.5)

    updated, _ = ingest_parity_results(raw, pack, {
        "pack_id": pack["pack_id"],
        "results": [{"query_id": "demo-project.sales.orders:aggregate", "source": source, "target": target}],
    })

    assert _statuses(updated, "demo-project.sales.orders")["aggregate"] == "passed"


def test_cli_pack_then_ingest_round_trip(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(json.dumps(_inventory([_orders()])), encoding="utf-8")

    assert main(["parity-pack", str(inventory_path), "--output", str(tmp_path / "pack")]) == 0
    pack = json.loads((tmp_path / "pack" / "parity-pack.json").read_text(encoding="utf-8"))
    assert "-- query_id: demo-project.sales.orders:row_count" in (
        tmp_path / "pack" / "parity-target.sql"
    ).read_text(encoding="utf-8")
    assert render_sql(pack, "source").startswith(f"-- BQToFabric parity pack {pack['pack_id']}")

    results = tmp_path / "results.json"
    results.write_text(json.dumps({"pack_id": "wrong", "results": []}), encoding="utf-8")
    args = [
        "parity-ingest", str(inventory_path), "--pack", str(tmp_path / "pack" / "parity-pack.json"),
        "--results", str(results), "--output", str(tmp_path / "out.json"),
    ]
    assert main(args) == 5
    results.write_text(json.dumps({"pack_id": pack["pack_id"], "results": []}), encoding="utf-8")
    assert main(args) == 0
    assert (tmp_path / "out.json").exists()
