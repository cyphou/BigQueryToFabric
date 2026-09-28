import json
from pathlib import Path
from typing import Any

from bqtofabric.artifact_validation import validate_dbt_project
from bqtofabric.assessment import run_assessment
from bqtofabric.cli import main
from bqtofabric.converter.models import TargetDialect
from bqtofabric.converter.sql_converter import SqlConverter
from bqtofabric.dbt_manifest import normalize_dbt_manifest
from bqtofabric.generator.dbt_generator import DBT_REASON_CODES, build_dbt_projects
from bqtofabric.mapping import FabricTarget, map_component
from bqtofabric.models import BigQueryInventory, BigQueryObject, ObjectKind

FIXTURE = Path(__file__).parent / "fixtures" / "gcp_ecosystem_project.json"

MANIFEST = {
    "metadata": {"project_name": "shop", "adapter_type": "bigquery", "dbt_version": "1.8.0"},
    "sources": {"source.shop.raw.orders": {"source_name": "raw", "name": "orders", "schema": "raw"}},
    "nodes": {
        "model.shop.stg_orders": {
            "resource_type": "model", "name": "stg_orders", "schema": "shop",
            "config": {"materialized": "view"},
            "raw_code": "select order_id, amount from {{ source('raw', 'orders') }}",
            "depends_on": {"nodes": ["source.shop.raw.orders"], "macros": []},
        },
        "model.shop.orders_daily": {
            "resource_type": "model", "name": "orders_daily", "schema": "shop",
            "config": {"materialized": "incremental"},
            "raw_code": (
                "select date(created_at) as d, sum(amount) as total from {{ ref('stg_orders') }}\n"
                "{% if is_incremental() %} where created_at > (select max(d) from {{ this }}) {% endif %}\n"
                "group by 1"
            ),
            "depends_on": {"nodes": ["model.shop.stg_orders"], "macros": ["macro.dbt.is_incremental", "macro.shop.cents"]},
        },
        "test.shop.not_null_stg_orders_order_id": {
            "resource_type": "test", "name": "not_null_stg_orders_order_id",
            "test_metadata": {"name": "not_null", "kwargs": {"column_name": "order_id"}},
            "depends_on": {"nodes": ["model.shop.stg_orders"]},
        },
        "test.shop.accepted_values": {
            "resource_type": "test", "name": "accepted_values_stg_orders_status",
            "test_metadata": {"name": "accepted_values", "kwargs": {"column_name": "status"}},
            "depends_on": {"nodes": ["model.shop.stg_orders"]},
        },
    },
}


def _project_inventory(*objects: dict[str, Any], preferences: dict[str, Any] | None = None) -> BigQueryInventory:
    return BigQueryInventory.from_dict({
        "project_id": "demo-project",
        "metadata": {"preferences": preferences or {}},
        "datasets": [],
        "components": list(objects),
    })


def _dbt_component() -> dict[str, Any]:
    item = normalize_dbt_manifest("demo-project", MANIFEST)
    return {
        "source_id": item.source_id, "name": item.name, "kind": item.kind.value,
        "discovered_from": item.discovered_from, "properties": item.properties,
    }


def test_manifest_normalizes_models_tests_sources_and_custom_macros() -> None:
    item = normalize_dbt_manifest("demo-project", MANIFEST)
    models = {model["name"]: model for model in item.properties["models"]}

    assert item.kind is ObjectKind.DBT_PROJECT
    assert item.source_id == "demo-project.dbt.shop"
    assert item.properties["adapter"] == "bigquery"
    assert models["orders_daily"]["refs"] == ["stg_orders"]
    assert models["orders_daily"]["macros"] == ["cents"]
    assert models["stg_orders"]["sources"] == [["raw", "orders"]]
    assert {test["name"] for test in item.properties["tests"]} == {"not_null", "accepted_values"}


def test_dbt_project_maps_to_dbt_job_and_dataform_only_on_request() -> None:
    dataform = BigQueryObject("p.dataform.wf", "wf", ObjectKind.DATAFORM_WORKFLOW)

    assert map_component(normalize_dbt_manifest("p", MANIFEST)).target is FabricTarget.DBT_JOB
    assert map_component(dataform).target is not FabricTarget.DBT_JOB
    assert map_component(dataform, {"transformation_framework": "dbt"}).target is FabricTarget.DBT_JOB


def test_dbt_job_carries_a_preview_warning() -> None:
    report = run_assessment(_project_inventory(_dbt_component()))

    assert any(finding.code == "DBT_JOB_PREVIEW" for finding in report.findings)


def test_generated_project_converts_refs_and_flags_what_it_cannot(tmp_path: Path) -> None:
    inventory = _project_inventory(_dbt_component())
    files, report = build_dbt_projects(inventory, run_assessment(inventory))
    (project,) = report["projects"]
    models = {model["name"]: model for model in project["models"]}

    staging = files["dbt/shop/models/stg_orders.sql"]
    assert staging.startswith("{{ config(materialized='view') }}")
    assert "{{ source('raw', 'orders') }}" in staging
    assert models["stg_orders"]["reasonCodes"] == []
    assert set(models["orders_daily"]["reasonCodes"]) == {
        "jinja_macro_review", "incremental_unique_key_missing", "bigquery_macro_review",
    }
    assert project["unconvertedTests"] == ["stg_orders:accepted_values"]
    assert "- not_null" in files["dbt/shop/models/schema.yml"]
    assert set(project["reasonCodes"]) <= DBT_REASON_CODES
    assert "password" not in files["dbt/shop/profiles.yml"]

    for relative, content in files.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(content, encoding="utf-8")
    assert validate_dbt_project(tmp_path / "dbt" / "shop") == []


def test_dataform_workflow_uses_compiled_models_and_backtick_refs() -> None:
    inventory = _project_inventory(
        {"source_id": "demo-project.dataform.wf", "name": "wf", "kind": "dataform_workflow",
         "properties": {"models": ["daily"]}},
        {"source_id": "demo-project.dataform.target.gold.base", "name": "base", "kind": "table",
         "sql": "SELECT id, amount FROM `demo-project.raw.orders`", "properties": {"dataform_model": True}},
        {"source_id": "demo-project.dataform.target.gold.daily", "name": "daily", "kind": "table",
         "sql": "SELECT SUM(amount) AS total FROM `demo-project.gold.base`",
         "properties": {"dataform_model": True, "incremental": True, "has_assertions": True}},
        preferences={"transformation_framework": "dbt"},
    )

    files, report = build_dbt_projects(inventory, run_assessment(inventory))
    models = {model["name"]: model for model in report["projects"][0]["models"]}

    assert "{{ ref('base') }}" in files["dbt/wf/models/daily.sql"]
    assert "{{ source('raw', 'orders') }}" in files["dbt/wf/models/base.sql"]
    assert models["daily"]["sourceObject"] == "demo-project.dataform.target.gold.daily"
    assert set(models["daily"]["reasonCodes"]) == {
        "incremental_unique_key_missing", "incremental_filter_review", "assertion_translation_required",
    }


def test_validator_rejects_missing_refs_cycles_and_secrets(tmp_path: Path) -> None:
    root = tmp_path / "p"
    (root / "models").mkdir(parents=True)
    (root / "dbt_project.yml").write_text("name: p\n", encoding="utf-8")
    (root / "models" / "a.sql").write_text("select * from {{ ref('b') }}\n", encoding="utf-8")
    (root / "models" / "b.sql").write_text("select * from {{ ref('a') }} -- {{ ref('ghost') }}\n", encoding="utf-8")
    (root / "models" / "c.sql").write_text("select * from {{ ref('missing') }}\n", encoding="utf-8")
    (root / "profiles.yml").write_text("p:\n  outputs:\n    f:\n      password: hunter2\n", encoding="utf-8")

    errors = validate_dbt_project(root)

    assert "c: ref('missing') has no model" in errors
    assert "ref cycle: a -> b -> a" in errors
    assert "profiles.yml: secret-bearing key" in errors
    assert not any("ghost" in error for error in errors)


def test_tsql_conversion_rewrites_date_and_ordinal_group_by() -> None:
    item = BigQueryObject("p.x", "x", ObjectKind.SQL_SCRIPT, sql=(
        "SELECT DATE(ts) AS d, region, COUNT(*) AS n FROM `p.s.t` GROUP BY 1, 2"
    ))

    converted = SqlConverter().convert(item, TargetDialect.TSQL).target_text

    assert "DATE(ts)" not in converted
    assert "CAST(ts AS DATE)" in converted
    assert "GROUP BY CAST(ts AS DATE), region" in converted


def test_reference_generate_writes_a_valid_dbt_project(tmp_path: Path) -> None:
    assert main(["generate", str(FIXTURE), "--output", str(tmp_path)]) == 0

    validation = json.loads((tmp_path / "fabric" / "artifact-validation.json").read_text(encoding="utf-8"))
    dbt = [item for item in validation["artifacts"] if item["path"].startswith("dbt:")]

    assert dbt == [{"path": "dbt:analytics", "status": "passed", "errors": []}]
    assert (tmp_path / "fabric" / "dbt-conversion.json").exists()
