"""Focused tests for the optional, offline Looker PBIP adapter."""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from bqtofabric.generator import looker_powerbi
from bqtofabric.models import BigQueryObject, ObjectKind


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> None:
    sibling = Path(__file__).resolve().parents[2] / "TableauToPowerBI"
    if not (sibling / "powerbi_import" / "pbip_generator.py").is_file():
        pytest.skip("optional TableauToPowerBI source tree not available")
    monkeypatch.syspath_prepend(str(sibling))


def asset(properties: dict) -> BigQueryObject:
    return BigQueryObject("source", "looker", ObjectKind.LOOKER_ASSET, properties=properties)


def example() -> dict:
    return {
        "views": [{
            "name": "orders",
            "sql_table_name": "`project.dataset.orders`",
            "dimensions": [
                {"name": "region", "type": "string", "sql": "${TABLE}.region"},
                {"name": "amount", "type": "number", "sql": "${TABLE}.amount"},
            ],
            "measures": [
                {"name": "sales", "type": "sum", "sql": "${TABLE}.amount"},
                {"name": "unique_regions", "type": "count_distinct", "sql": "${TABLE}.region"},
                {"name": "rows", "type": "count"},
            ],
        }],
        "dimensions": [
            {"view": "orders", "name": "active", "type": "yesno", "sql": "${TABLE}.active"},
        ],
        "dashboards": [
            {"name": "Revenue", "elements": [
                {"name": "by_region", "type": "bar", "view": "orders",
                 "dimensions": ["region"], "measures": ["sales"]},
                {"name": "detail", "type": "table", "view": "orders",
                 "dimensions": ["region", "active"], "measures": ["rows"]},
            ]},
            {"name": "Overview", "elements": [
                {"name": "regions", "type": "table", "view": "orders",
                 "dimensions": ["region"], "measures": ["unique_regions"]},
            ]},
        ],
    }


def codes(result: looker_powerbi.LookerPowerBIProject) -> list[str]:
    return [issue["code"] for issue in result.review["issues"]]


def test_real_pbip_with_source_specific_pages_and_model(
    backend: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network is prohibited")

    monkeypatch.setattr("socket.socket.connect", no_network)
    result = looker_powerbi.generate_looker_powerbi_project(asset(example()))
    assert result.review["security"] == "not_migrated_unverified"
    assert result.review["runtime"] == result.review["parity"] == "not_run"
    assert json.loads(result.files["LookerMigration.pbip"])["artifacts"][0]["report"]["path"] == (
        "LookerMigration.Report"
    )
    model = result.files["LookerMigration.SemanticModel/definition/tables/orders.tmdl"]
    assert "measure sales = SUM('orders'[amount])" in model
    assert "measure unique_regions = COALESCE(DISTINCTCOUNTNOBLANK('orders'[region]), 0)" in model
    assert "measure rows = COALESCE(COUNTROWS('orders'), 0)" in model
    assert "sourceColumn: active" in model
    assert 'error "Review-only:' in model
    assert "project.dataset.orders" not in "\n".join(result.files.values())
    pages = [json.loads(v) for k, v in result.files.items() if k.endswith("/page.json")]
    assert {page["displayName"] for page in pages} == {"Revenue", "Overview"}
    visuals = [json.loads(v) for k, v in result.files.items() if k.endswith("/visual.json")]
    assert len(visuals) == 3
    bar = next(v for v in visuals if v["visual"]["visualType"] == "clusteredBarChart")
    title = bar["visual"]["visualContainerObjects"]["title"][0]["properties"]["text"]
    assert title["expr"]["Literal"]["Value"] == "'by_region'"
    state = bar["visual"]["query"]["queryState"]
    assert state["Category"]["projections"][0]["queryRef"] == "orders.region"
    assert state["Y"]["projections"][0]["field"]["Measure"]["Property"] == "sales"

    # Sibling's offline validators are static checks, not Desktop/runtime evidence.
    for path, content in result.files.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    openability = importlib.import_module("powerbi_import.openability")
    schema_validator = importlib.import_module("powerbi_import.schema_validator")

    schema_results = schema_validator.validate_report_dir(
        str(tmp_path / "LookerMigration.Report" / "definition")
    )
    assert schema_results and all(x.ok for x in schema_results)
    report = openability.check_openability(str(tmp_path))
    assert report.openable, report.blocking_issues
    assert report.to_dict()["refresh_verification"] == "not_run"


@pytest.fixture
def capture_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace only the optional backend/renderer, not the Looker mapping logic.

    The resulting JSON is a test capture of renderer inputs, not a PBIP.
    """
    import_module = importlib.import_module

    def no_optional_import(name: str, package: str | None = None) -> ModuleType:
        if name == "powerbi_import" or name.startswith("powerbi_import."):
            raise AssertionError("mapping tests must not import the optional backend")
        return import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", no_optional_import)
    dummy = object()
    monkeypatch.setattr(looker_powerbi, "_load_backend", lambda: (dummy, dummy, dummy))

    def capture(
        pbip: Any, tmdl: Any, visual: Any, name: str,
        tables: list[dict[str, Any]], pages: list[Any],
    ) -> dict[str, str]:
        assert pbip is tmdl is visual is dummy
        return {"capture.json": json.dumps(
            {"project": name, "tables": tables, "pages": pages}, sort_keys=True
        )}

    monkeypatch.setattr(looker_powerbi, "_render", capture)


def test_core_supported_mapping_without_optional_backend(capture_mapping: None) -> None:
    properties = example()
    properties["measures"] = [
        {"view": "orders", "name": "max_amount", "type": "max", "sql": "${TABLE}.amount"}
    ]
    original = copy.deepcopy(properties)
    one = looker_powerbi.generate_looker_powerbi_project(asset(properties))
    two = looker_powerbi.generate_looker_powerbi_project(asset(copy.deepcopy(properties)))
    assert properties == original
    assert (one.files, one.review) == (two.files, two.review)

    captured = json.loads(one.files["capture.json"])
    table = captured["tables"][0]
    assert table["name"] == "orders"
    assert {col["name"]: col["sourceColumn"] for col in table["columns"]} == {
        "region": "region", "amount": "amount", "active": "active",
    }
    assert {m["name"]: m["expression"] for m in table["measures"]} == {
        "sales": "SUM('orders'[amount])",
        "unique_regions": "COALESCE(DISTINCTCOUNTNOBLANK('orders'[region]), 0)",
        "rows": "COALESCE(COUNTROWS('orders'), 0)",
        "max_amount": "MAX('orders'[amount])",
    }
    assert table["partitions"][0]["source"]["expression"].startswith("error ")
    assert [page[1] for page in captured["pages"]] == ["Revenue", "Overview"]
    assert captured["pages"][0][2][0]["measures"] == ["sales"]
    assert one.review["runtime"] == "not_run"
    assert one.review["security"] == "not_migrated_unverified"


def test_core_unsupported_mapping_without_optional_backend(capture_mapping: None) -> None:
    properties = example()
    marker = "really_sensitive_value_abcd1234"
    properties["access_filters"] = [{"user_attribute": marker}]
    properties["views"][0]["measures"].extend([
        {"name": "filtered", "type": "sum", "sql": "${TABLE}.amount",
         "filters": [{"value": marker}]},
        {"name": "custom", "type": "sum", "sql": marker},
        {"name": "bad_sum", "type": "sum", "sql": "${TABLE}.region"},
    ])
    result = looker_powerbi.generate_looker_powerbi_project(asset(properties))
    assert {"security_not_migrated", "filtered_measure_not_migrated", "unsupported_measure",
            "unsupported_measure_data_type", "unresolved_model_context"} <= set(codes(result))
    captured = json.loads(result.files["capture.json"])
    assert {m["name"] for m in captured["tables"][0]["measures"]} == {
        "sales", "unique_regions", "rows",
    }
    assert all(not page[2] for page in captured["pages"])
    assert marker not in json.dumps({"files": result.files, "review": result.review})


def test_common_visual_types_keep_strict_field_and_context_gates(capture_mapping: None) -> None:
    properties = example()
    properties["dashboards"] = [{"name": "Overview", "elements": [
        {"name": "Trend", "type": "line", "view": "orders",
         "dimensions": ["region"], "measures": ["sales"]},
        {"name": "Columns", "type": "column", "view": "orders",
         "dimensions": ["region"], "measures": ["sales"]},
        {"name": "KPI", "type": "card", "view": "orders",
         "dimensions": [], "measures": ["sales"]},
        {"name": "Ambiguous trend", "type": "line", "view": "orders",
         "dimensions": ["region"], "measures": ["sales", "rows"]},
        {"name": "Trend without category", "type": "line", "view": "orders",
         "dimensions": [], "measures": ["sales"]},
        {"name": "Columns with categories", "type": "column", "view": "orders",
         "dimensions": ["region", "amount"], "measures": ["sales"]},
        {"name": "Columns without measure", "type": "column", "view": "orders",
         "dimensions": ["region"], "measures": []},
        {"name": "Grouped KPI", "type": "card", "view": "orders",
         "dimensions": ["region"], "measures": ["sales"]},
        {"name": "Multiple KPI", "type": "card", "view": "orders",
         "dimensions": [], "measures": ["sales", "rows"]},
    ]}]
    result = looker_powerbi.generate_looker_powerbi_project(asset(properties))
    page = json.loads(result.files["capture.json"])["pages"][0]
    assert [element["type"] for element in page[2]] == ["line", "column", "card"]
    assert codes(result).count("unsupported_visual") == 6

    properties["security"] = [{"unknown": "private_value"}]
    result = looker_powerbi.generate_looker_powerbi_project(asset(properties))
    assert not json.loads(result.files["capture.json"])["pages"][0][2]
    assert "unresolved_model_context" in codes(result)
    assert "private_value" not in json.dumps({"files": result.files, "review": result.review})


def test_display_title_duplicates_are_case_insensitive_and_scoped(capture_mapping: None) -> None:
    properties = example()
    element = properties["dashboards"][0]["elements"][0]
    properties["dashboards"] = [
        {"name": "Revenue by Region", "elements": [element]},
        {"name": "revenue BY region", "elements": [element]},
        {"name": "Other - Page", "elements": [
            {**element, "name": "Sales by Region"},
            {**element, "name": "sales BY region"},
            {**element, "name": "Unique - Sales"},
        ]},
        {"name": "Another Page", "elements": [{**element, "name": "Sales by Region"}]},
    ]
    result = looker_powerbi.generate_looker_powerbi_project(asset(properties))
    assert codes(result).count("duplicate_dashboard") == 2
    assert codes(result).count("duplicate_element") == 2
    pages = json.loads(result.files["capture.json"])["pages"]
    assert [page[1] for page in pages] == ["Other - Page", "Another Page"]
    assert [[element["name"] for element in page[2]] for page in pages] == [
        ["Unique - Sales"], ["Sales by Region"],
    ]


def test_counts_default_to_zero_without_changing_other_aggregates(capture_mapping: None) -> None:
    properties = example()
    properties["views"][0]["measures"].extend([
        {"name": "avg_amount", "type": "average", "sql": "${TABLE}.amount"},
        {"name": "min_amount", "type": "min", "sql": "${TABLE}.amount"},
        {"name": "max_amount", "type": "max", "sql": "${TABLE}.amount"},
        {"name": "invalid_count", "type": "count", "sql": "${TABLE}.amount"},
    ])
    result = looker_powerbi.generate_looker_powerbi_project(asset(properties))
    measures = json.loads(result.files["capture.json"])["tables"][0]["measures"]
    expressions = {measure["name"]: measure["expression"] for measure in measures}
    assert expressions == {
        "sales": "SUM('orders'[amount])",
        "unique_regions": "COALESCE(DISTINCTCOUNTNOBLANK('orders'[region]), 0)",
        "rows": "COALESCE(COUNTROWS('orders'), 0)",
        "avg_amount": "AVERAGE('orders'[amount])",
        "min_amount": "MIN('orders'[amount])",
        "max_amount": "MAX('orders'[amount])",
    }
    assert "unsupported_measure" in codes(result)


@pytest.mark.parametrize("credential", [
    "ghp_" + "A" * 36,
    "gho_" + "B" * 36,
    "github_pat_" + "C" * 20,
    "AKIA" + "D" * 16,
    "ASIA" + "E" * 16,
    "AIza" + "F" * 35,
    "xoxb-" + "G" * 12,
    "xoxp-" + "H" * 12,
    "xoxa-" + "J" * 12,
    "xoxr-" + "K" * 12,
    "xoxs-" + "L" * 12,
    "sk_live_" + "M" * 16,
    "sk_test_" + "N" * 16,
])
def test_credential_shapes_rejected_in_all_names(
    capture_mapping: None, credential: str, caplog: pytest.LogCaptureFixture,
) -> None:
    # Synthetic shape-only strings; none is a real credential.
    properties = example()
    original = properties["dashboards"][0]["elements"][0]
    properties["views"][0]["dimensions"].extend([
        {"name": credential, "type": "string", "sql": "${TABLE}.region"},
        {"name": "new_dim", "type": "string", "sql": "${TABLE}." + credential},
    ])
    properties["views"][0]["measures"].append({"name": credential, "type": "count"})
    properties["dashboards"][0]["elements"].append({**original, "name": "Title " + credential})
    properties["dashboards"].append({"name": "Page " + credential, "elements": [original]})
    result = looker_powerbi.generate_looker_powerbi_project(asset(properties))
    issues = result.review["issues"]
    for path in (
        "views[0].dimensions[2]", "views[0].dimensions[3]", "views[0].measures[3]",
        "dashboards[0].elements[2]", "dashboards[2]",
    ):
        assert any(issue["path"] == path and issue["code"] in {
            "unsafe_or_missing_name", "unsupported_dimension",
        } for issue in issues)
    assert credential not in json.dumps({"files": result.files, "review": result.review})
    assert credential not in caplog.text
    with pytest.raises(ValueError, match="project_name") as exc:
        looker_powerbi.generate_looker_powerbi_project(asset(example()), project_name=credential)
    assert credential not in str(exc.value)
    properties = example()
    properties["views"][0]["name"] = credential
    result = looker_powerbi.generate_looker_powerbi_project(asset(properties))
    assert result.files == {}
    assert "unsafe_or_missing_name" in codes(result)
    assert credential not in json.dumps(result.review)


@pytest.mark.parametrize("credential", [
    "ghp_" + "A" * 36,
    "xoxb-" + "B" * 12,
    "sk_live_" + "C" * 16,
    "sk_test_" + "D" * 16,
])
def test_credential_shape_is_omitted_from_real_pbir(
    backend: None, caplog: pytest.LogCaptureFixture, credential: str,
) -> None:
    properties = example()
    properties["dashboards"][0]["elements"][0]["name"] = "Sales " + credential
    properties["dashboards"][1]["name"] = credential
    result = looker_powerbi.generate_looker_powerbi_project(asset(properties))
    assert codes(result).count("unsafe_or_missing_name") == 2
    assert credential not in json.dumps({"files": result.files, "review": result.review})
    assert credential not in caplog.text


@pytest.mark.parametrize(("value", "expected"), [
    ("ghp_" + "A" * 36, True),
    ("ghp_" + "A" * 40, True),
    ("github_pat_" + "B" * 20, True),
    ("AKIA" + "C" * 16, True),
    ("AIza" + "D" * 35, True),
    ("Title xoxb-" + "E" * 10, True),
    ("Title XOXp-" + "F" * 10, True),
    ("sk_live_" + "G" * 16, True),
    ("sk_test_" + "H" * 16, True),
    ("xoxb-" + "E" * 9, False),
    ("sk_live_" + "G" * 15, False),
    ("ordinary Sales - Report", False),
])
def test_credential_guard_matches_extractor(value: str, expected: bool) -> None:
    # Extractor is under separate ownership and may not be present in all checkouts.
    extractor = pytest.importorskip("bqtofabric.looker_api_export")
    assert bool(looker_powerbi._CREDENTIAL_SHAPE.search(value)) is expected
    assert bool(extractor._CREDENTIAL.search(value)) is expected


@pytest.mark.parametrize("title", [
    "", " x", "x ", " ", "x\nmalicious", "x\tmalicious", "../path",
    "Title' OR 1", 'Title"quoted', "café", "x" * 65, "API-Key",
    "access key", "private - key", "Session Token Rate",
])
def test_rejected_display_titles_are_not_emitted(
    capture_mapping: None, title: str,
) -> None:
    properties = example()
    element = properties["dashboards"][0]["elements"][0]
    properties["dashboards"] = [
        {"name": title, "elements": [element]},
        {"name": "Allowed Page", "elements": [{**element, "name": title}]},
    ]
    result = looker_powerbi.generate_looker_powerbi_project(asset(properties))
    issues = result.review["issues"]
    assert {"path": "dashboards[0]", "code": "unsafe_or_missing_name"} in issues
    assert {"path": "dashboards[1].elements[0]", "code": "unsafe_or_missing_name"} in issues
    pages = json.loads(result.files["capture.json"])["pages"]
    assert len(pages) == 1 and pages[0][1:] == ["Allowed Page", []]


@pytest.mark.parametrize("title", [
    "Revenue by Region", "Quarterly - Revenue", "2026 Sales", "_x", "-", "x" * 64, "CON",
])
def test_valid_display_titles_are_preserved(capture_mapping: None, title: str) -> None:
    properties = example()
    element = properties["dashboards"][0]["elements"][0]
    properties["dashboards"] = [{"name": title, "elements": [{**element, "name": title}]}]
    result = looker_powerbi.generate_looker_powerbi_project(asset(properties))
    pages = json.loads(result.files["capture.json"])["pages"]
    assert pages[0][1] == pages[0][2][0]["name"] == title


def test_semantic_identifiers_remain_strict(capture_mapping: None) -> None:
    properties = example()
    properties["views"][0]["name"] = "orders data"
    result = looker_powerbi.generate_looker_powerbi_project(asset(properties))
    assert result.files == {}
    assert "unsafe_or_missing_name" in codes(result)
    with pytest.raises(ValueError, match="project_name"):
        looker_powerbi.generate_looker_powerbi_project(asset(example()), project_name="Sales 2026")


def test_display_titles_in_real_pbir_are_safe_and_deterministic(backend: None) -> None:
    properties = example()
    properties["dashboards"][0]["name"] = "Revenue by Region"
    properties["dashboards"][0]["elements"][0]["name"] = "Sales - by Region"
    one = looker_powerbi.generate_looker_powerbi_project(asset(properties))
    two = looker_powerbi.generate_looker_powerbi_project(asset(copy.deepcopy(properties)))
    assert (one.files, one.review) == (two.files, two.review)
    pages = [json.loads(v) for k, v in one.files.items() if k.endswith("/page.json")]
    assert "Revenue by Region" in {page["displayName"] for page in pages}
    visuals = [json.loads(v) for k, v in one.files.items() if k.endswith("/visual.json")]
    bar = next(v for v in visuals if v["visual"]["visualType"] == "clusteredBarChart")
    title = bar["visual"]["visualContainerObjects"]["title"][0]["properties"]["text"]
    assert title["expr"]["Literal"]["Value"] == "'Sales - by Region'"
    assert all("Revenue by Region" not in path and "Sales - by Region" not in path
               for path in one.files)


def test_deterministic_and_top_level_measures(backend: None) -> None:
    properties = example()
    properties["measures"] = [
        {"view": "orders", "name": "max_amount", "type": "max", "sql": "${TABLE}.amount"}
    ]
    one = looker_powerbi.generate_looker_powerbi_project(asset(properties))
    two = looker_powerbi.generate_looker_powerbi_project(asset(copy.deepcopy(properties)))
    assert one.files == two.files
    assert one.review == two.review
    assert "measure max_amount = MAX('orders'[amount])" in one.files[
        "LookerMigration.SemanticModel/definition/tables/orders.tmdl"
    ]


def test_unsupported_security_filters_and_secret_values_are_not_copied(backend: None) -> None:
    properties = example()
    marker = "really_sensitive_value_abcd1234"
    properties["access_filters"] = [{"user_attribute": marker}]
    properties["joins"] = [{"sql_on": marker}]
    properties["views"][0]["measures"].extend([
        {"name": "filtered", "type": "sum", "sql": "${TABLE}.amount",
         "filters": [{"value": marker}]},
        {"name": "custom", "type": "sum", "sql": marker},
        {"name": "password", "type": "count"},
        {"name": "bad_sum", "type": "sum", "sql": "${TABLE}.region"},
    ])
    properties["dashboards"][0]["elements"].append({
        "name": "bad", "type": "table", "view": "orders", "dimensions": ["region"],
        "measures": [], "filters": [{"value": marker}],
    })
    result = looker_powerbi.generate_looker_powerbi_project(asset(properties))
    assert {"security_not_migrated", "joins_not_migrated", "filtered_measure_not_migrated",
            "unsupported_measure", "unsafe_or_missing_name", "visual_filters_not_migrated",
            "unresolved_model_context", "unsupported_measure_data_type"} <= set(codes(result))
    assert not any(path.endswith("/visual.json") for path in result.files)
    assert marker not in json.dumps({"files": result.files, "review": result.review})
    model = result.files["LookerMigration.SemanticModel/definition/tables/orders.tmdl"]
    assert "measure filtered" not in model and "measure custom" not in model
    assert "role " not in model


def test_unknown_visual_missing_fields_and_duplicate_names(backend: None) -> None:
    properties = example()
    properties["views"][0]["dimensions"].append(
        {"name": "region", "type": "string", "sql": "${TABLE}.other"}
    )
    properties["dashboards"][0]["elements"].append({
        "name": "scatter", "type": "scatter", "view": "orders",
        "dimensions": ["amount"], "measures": ["sales"],
    })
    result = looker_powerbi.generate_looker_powerbi_project(asset(properties))
    assert "duplicate_field" in codes(result)
    assert "unresolved_element_fields" in codes(result)
    assert "unsupported_visual" in codes(result)
    model = result.files["LookerMigration.SemanticModel/definition/tables/orders.tmdl"]
    assert "\tcolumn region\n" not in model
    assert "measure unique_regions" not in model


def test_missing_structure_does_not_invent_source(backend: None) -> None:
    result = looker_powerbi.generate_looker_powerbi_project(asset({"explores": ["orders"]}))
    assert result.files == {}
    assert "no_convertible_model" in codes(result)
    assert "explores_not_migrated" in codes(result)


def test_malformed_fields_are_diagnosed(backend: None) -> None:
    properties = example()
    properties["views"][0]["dimensions"][0]["type"] = []
    properties["views"][0]["measures"][0]["type"] = {}
    properties["dimensions"] = [{"name": "x", "view": [], "type": "string"}]
    properties["dashboards"][0]["elements"].append({
        "name": "malformed", "type": [], "view": "orders",
        "dimensions": ["amount"], "measures": ["rows"],
    })
    result = looker_powerbi.generate_looker_powerbi_project(asset(properties))
    assert {"unsupported_dimension", "unsupported_measure", "unknown_view",
            "unsupported_visual"} <= set(codes(result))


def test_dependency_failure_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(name: str) -> object:
        raise ModuleNotFoundError("missing")

    monkeypatch.setattr(looker_powerbi.importlib, "import_module", unavailable)
    with pytest.raises(RuntimeError, match="TableauToPowerBI.*PYTHONPATH"):
        looker_powerbi.generate_looker_powerbi_project(asset(example()))


@pytest.mark.parametrize("name", ["../escape", "token", "CON", "a\nb"])
def test_unsafe_project_name_is_rejected(name: str) -> None:
    with pytest.raises(ValueError, match="project_name"):
        looker_powerbi.generate_looker_powerbi_project(asset(example()), project_name=name)


def test_non_looker_asset_is_rejected() -> None:
    with pytest.raises(ValueError, match="LOOKER_ASSET"):
        looker_powerbi.generate_looker_powerbi_project(
            BigQueryObject("x", "x", ObjectKind.TABLE)
        )
