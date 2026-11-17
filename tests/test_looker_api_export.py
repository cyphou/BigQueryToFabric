"""Contract tests for the offline Looker API response ingester."""
import copy
import json
from pathlib import Path
from typing import Any

import pytest

from bqtofabric.looker_api_export import normalize_looker_api_export
from bqtofabric.models import ObjectKind


def responses() -> dict[str, Any]:
    return {
        "explores": [{
            "id": "commerce::orders", "name": "orders", "model_name": "commerce",
            "view_name": "orders", "sql_table_name": "`warehouse.sales.orders`",
            "joins": [], "always_join": [], "access_filters": [],
            "access_filter_fields": [], "always_filter": [], "conditionally_filter": [],
            "sql_always_where": "", "access_grants": [], "required_access_grants": [],
            "fields": {
                "dimensions": [
                    {"name": "orders.region", "view": "orders", "type": "string",
                     "sql": "${TABLE}.region", "sql_case": None, "dimension_group": None},
                    {"name": "orders.amount", "view": "orders", "type": "number",
                     "sql": "${TABLE}.amount", "sql_case": None, "dimension_group": None},
                ],
                "measures": [
                    {"name": "orders.sales", "view": "orders", "type": "sum",
                     "sql": "${TABLE}.amount", "sql_case": None, "dimension_group": None,
                     "filters": []},
                ],
                "filters": [], "parameters": [],
            },
        }],
        "dashboards": [{
            "id": "12", "title": "Revenue", "dashboard_filters": [],
            "dashboard_elements": [{
                "id": "91", "title": "by_region", "type": "vis",
                "query": {
                    "model": "commerce", "view": "orders",
                    "fields": ["orders.region", "orders.sales"],
                    "filters": {}, "filter_expression": None, "filter_config": None,
                    "pivots": [], "fill_fields": [], "dynamic_fields": None,
                    "has_table_calculations": False, "limit": "-1",
                    "sorts": [], "total": False, "row_total": None, "subtotals": [],
                    "query_timezone": None, "column_limit": None,
                    "vis_config": {"type": "looker_bar"},
                },
            }],
        }],
    }


def report(asset):
    return json.loads(asset.labels["looker_ingestion_report"])


def codes(asset):
    return [entry["code"] for entry in report(asset)]


def test_downloaded_faa_linked_looks_are_diagnosed_without_nested_values():
    path = (Path(__file__).resolve().parents[1] / "examples" / "looker" / "looker-cli"
            / "Dashboard_17_FAA_KPIs.json")
    if not path.is_file():
        pytest.skip("optional downloaded public FAA dashboard is unavailable")
    dashboard = json.loads(path.read_text(encoding="utf-8"))
    assert len(dashboard["dashboard_elements"]) == 6
    for element in dashboard["dashboard_elements"][4:]:
        assert element["title"] is None
        assert isinstance(element["look"], dict)
        assert isinstance(element["look"]["query"], dict)
    asset = normalize_looker_api_export("project", {"explores": [], "dashboards": [dashboard]})
    linked = [item for item in report(asset) if item["code"] == "linked_look_not_migrated"]
    assert linked == [
        {"path": "dashboards[0].elements[4]", "code": "linked_look_not_migrated"},
        {"path": "dashboards[0].elements[5]", "code": "linked_look_not_migrated"},
    ]
    assert not any(item["path"] in {x["path"] for x in linked} and
                   item["code"] == "invalid_element" for item in report(asset))
    identifiers = json.loads(asset.labels["looker_source_identifiers"])
    assert not any(item["path"] in {x["path"] for x in linked} for item in identifiers)
    assert len(asset.properties["dashboards"][0]["elements"]) == 4
    assert "no_explore_responses" in codes(asset)


@pytest.mark.parametrize("linked_field", ["look", "look_id"])
def test_titled_linked_look_never_copies_values_or_uses_inline_query(linked_field):
    source = responses()
    element = source["dashboards"][0]["dashboard_elements"][0]
    marker = "sensitive_nested_value_abcd1234"
    if linked_field == "look":
        element["look"] = {"title": marker, "query": {"filters": {"field": marker}}}
    else:
        element["look_id"] = "42"
    before = copy.deepcopy(source)
    asset = normalize_looker_api_export("project", source)
    assert source == before
    assert {"path": "dashboards[0].elements[0]", "code": "linked_look_not_migrated"} in report(asset)
    assert asset.properties["dashboards"][0]["elements"] == []
    assert marker not in repr(asset)
    assert not any(x["path"].startswith("dashboards[0].elements[0]")
                   for x in json.loads(asset.labels["looker_source_identifiers"]))


def test_linked_look_emits_no_visual_and_does_not_assume_security(monkeypatch):
    sibling = Path(__file__).resolve().parents[2] / "TableauToPowerBI"
    if not (sibling / "powerbi_import" / "pbip_generator.py").is_file():
        pytest.skip("optional TableauToPowerBI source tree not available")
    monkeypatch.syspath_prepend(str(sibling))
    from bqtofabric.generator.looker_powerbi import generate_looker_powerbi_project

    source = responses()
    del source["explores"][0]["access_grants"]
    source["dashboards"][0]["dashboard_elements"][0]["look"] = {
        "title": "sensitive_nested_value_abcd1234",
        "query": {"filters": {"field": "sensitive_nested_value_abcd1234"}},
    }
    asset = normalize_looker_api_export("project", source)
    result = generate_looker_powerbi_project(asset)
    assert "access_grants_missing_or_invalid" in codes(asset)
    assert asset.properties["security"]
    assert not any(path.endswith("/visual.json") for path in result.files)
    assert "sensitive_nested_value_abcd1234" not in repr((asset, result))


@pytest.mark.parametrize("element", [None, {}, {"title": None, "look": None, "look_id": None}])
def test_invalid_nonlinked_elements_keep_invalid_diagnostic(element):
    source = responses()
    source["dashboards"][0]["dashboard_elements"] = [element]
    asset = normalize_looker_api_export("project", source)
    assert {"path": "dashboards[0].elements[0]", "code": "invalid_element"} in report(asset)
    assert "linked_look_not_migrated" not in codes(asset)


def test_real_shaped_response_converts_via_generator(monkeypatch):
    sibling = Path(__file__).resolve().parents[2] / "TableauToPowerBI"
    if not (sibling / "powerbi_import" / "pbip_generator.py").is_file():
        pytest.skip("optional TableauToPowerBI source tree not available")
    monkeypatch.syspath_prepend(str(sibling))
    from bqtofabric.generator.looker_powerbi import generate_looker_powerbi_project

    def no_network(*args, **kwargs):
        raise AssertionError("offline only")

    monkeypatch.setattr("socket.socket.connect", no_network)
    source = responses()
    source["dashboards"][0]["title"] = "Revenue by Region"
    source["dashboards"][0]["dashboard_elements"][0]["title"] = "Sales - by Region"
    before = copy.deepcopy(source)
    asset = normalize_looker_api_export("project", source)
    assert source == before
    assert asset.kind is ObjectKind.LOOKER_ASSET and asset.discovered_from == "external_payload"
    identifiers = json.loads(asset.labels["looker_source_identifiers"])
    assert {"path": "explores[0]", "model_name": "commerce", "name": "orders",
            "view_name": "orders"} in identifiers
    assert {"path": "dashboards[0]", "id": "12", "title": "Revenue by Region"} in identifiers
    assert asset.properties["views"][0]["dimensions"][0]["name"] == "region"
    assert asset.properties["dashboards"][0]["elements"][0]["measures"] == ["sales"]
    result = generate_looker_powerbi_project(asset)
    model = result.files["LookerMigration.SemanticModel/definition/tables/orders.tmdl"]
    assert "measure sales = SUM('orders'[amount])" in model
    assert any(path.endswith("/visual.json") for path in result.files)
    pages = [json.loads(v) for k, v in result.files.items() if k.endswith("/page.json")]
    assert pages[0]["displayName"] == "Revenue by Region"
    assert "Sales - by Region" in next(v for k, v in result.files.items()
                                         if k.endswith("/visual.json"))
    assert result.review["security"] == "not_migrated_unverified"
    assert normalize_looker_api_export("project", copy.deepcopy(source)) == asset
    assert generate_looker_powerbi_project(asset).files == result.files


def test_security_join_filter_and_unknown_values_are_not_copied():
    source = responses()
    marker = "really_sensitive_value_abcd1234"
    exp = source["explores"][0]
    exp["joins"] = [{"name": "customers", "sql_on": marker}]
    exp["access_filters"] = [{"field": "orders.region", "user_attribute": marker}]
    exp["fields"]["dimensions"].append({
        "name": "customers.region", "view": "customers", "type": "string",
        "sql": "${TABLE}.region", "sql_case": None, "dimension_group": None,
    })
    exp["fields"]["measures"][0]["filters"] = [{"field": "orders.region", "value": marker}]
    tile = source["dashboards"][0]["dashboard_elements"][0]
    tile["query"]["filters"] = {"orders.region": marker}
    tile["query"]["dynamic_fields"] = marker
    tile["query"]["fields"] = ["orders.region"]
    tile["query"]["vis_config"]["custom_secret"] = marker
    asset = normalize_looker_api_export("project", source)
    assert marker not in json.dumps({"properties": asset.properties, "labels": asset.labels})
    assert {"joins", "security"} <= asset.properties.keys()
    assert not asset.properties["views"][0]["measures"]
    assert {"field_semantics_not_migrated", "query_semantics_not_migrated",
            "visual_configuration_not_migrated", "joined_or_invalid_field"} <= set(codes(asset))
    assert asset.properties["dashboards"][0]["elements"][0]["filters"]


def test_missing_filtered_and_unsupported_fields_are_explicit():
    source = responses()
    exp = source["explores"][0]
    del exp["access_filters"]
    del exp["fields"]["measures"][0]["filters"]
    exp["fields"]["dimensions"][0]["sql"] = None
    tile = source["dashboards"][0]["dashboard_elements"][0]
    del tile["query"]["filter_config"]
    tile["query"]["fields"] = ["orders.amount"]
    asset = normalize_looker_api_export("project", source)
    assert {"access_filters_missing_or_invalid", "field_semantics_missing",
            "unsupported_type_or_sql", "query_filter_evidence_missing_or_invalid"} <= set(codes(asset))
    assert asset.properties["security"]
    assert asset.properties["dashboards"][0]["elements"][0]["filters"]


@pytest.mark.parametrize(("key", "value"), [
    ("look_id", "private_look_identifier"),
    ("look", {"id": "private_look_identifier", "description": "private_description"}),
    ("look", {}),
    ("look_id", []),
])
def test_linked_look_is_unresolved_even_with_embedded_query(key, value):
    source = responses()
    source["dashboards"][0]["dashboard_elements"][0][key] = value
    asset = normalize_looker_api_export("project", source)
    assert asset.properties["dashboards"][0]["elements"] == []
    assert {"path": "dashboards[0].elements[0]", "code": "linked_look_not_migrated"} in report(asset)
    assert "private_look_identifier" not in repr(asset)
    assert "private_description" not in repr(asset)


def test_null_look_fields_do_not_block_unlinked_query():
    source = responses()
    source["dashboards"][0]["dashboard_elements"][0].update({"look": None, "look_id": None})
    asset = normalize_looker_api_export("project", source)
    assert "linked_look_not_migrated" not in codes(asset)
    assert "unsupported" not in asset.properties["dashboards"][0]["elements"][0]


@pytest.mark.parametrize(("source_type", "target_type", "fields"), [
    ("looker_line", "line", ["orders.region", "orders.sales"]),
    ("looker_column", "column", ["orders.region", "orders.sales"]),
    ("single_value", "card", ["orders.sales"]),
])
def test_common_visual_types_are_normalized_without_dropping_configuration(
    source_type, target_type, fields
):
    source = responses()
    query = source["dashboards"][0]["dashboard_elements"][0]["query"]
    query["fields"] = fields
    query["vis_config"] = {"type": source_type}
    asset = normalize_looker_api_export("project", source)
    visual = asset.properties["dashboards"][0]["elements"][0]
    assert visual["type"] == target_type
    assert "unsupported" not in visual
    assert "visual_type_missing_or_unsupported" not in codes(asset)

    query["vis_config"]["unsupported_option"] = "private_value"
    asset = normalize_looker_api_export("project", source)
    assert asset.properties["dashboards"][0]["elements"][0]["unsupported"]
    assert "visual_configuration_not_migrated" in codes(asset)
    assert "private_value" not in repr(asset)


def test_linked_look_without_query_is_diagnosed():
    source = responses()
    element = source["dashboards"][0]["dashboard_elements"][0]
    element["look_id"] = "private_look_identifier"
    del element["query"]
    asset = normalize_looker_api_export("project", source)
    assert "linked_look_not_migrated" in codes(asset)
    assert "private_look_identifier" not in repr(asset)


@pytest.mark.parametrize(("key", "invalid", "nonempty"), [
    ("sql_always_where", [], "region = 'confidential_value'"),
    ("access_grants", "", ["confidential_value"]),
    ("required_access_grants", "", ["confidential_value"]),
])
def test_explore_security_evidence_must_be_explicit_and_well_typed(key, invalid, nonempty):
    for mode in ("missing", "null", "invalid", "nonempty"):
        source = responses()
        explore = source["explores"][0]
        if mode == "missing":
            del explore[key]
        else:
            explore[key] = {"null": None, "invalid": invalid, "nonempty": nonempty}[mode]
        asset = normalize_looker_api_export("project", source)
        expected = f"{key}_{'not_migrated' if mode == 'nonempty' else 'missing_or_invalid'}"
        assert expected in codes(asset)
        assert any(item["code"] == expected for item in asset.properties["security"])
        assert "confidential_value" not in repr(asset)


def test_unknown_explore_properties_fail_closed_without_copying_values():
    source = responses()
    explore = source["explores"][0]
    explore["unknown_restriction"] = {"user": "confidential_value"}
    explore["description"] = "description_never_copied"
    asset = normalize_looker_api_export("project", source)
    assert "unknown_explore_property" in codes(asset)
    assert asset.properties["explores"] == [
        {"path": "explores[0]", "code": "unknown_explore_property"}
    ]
    assert "confidential_value" not in repr(asset)
    assert "unknown_restriction" not in repr(asset)
    assert "description_never_copied" not in repr(asset)

    explore["unknown_restriction"] = None
    asset = normalize_looker_api_export("project", source)
    assert "unknown_explore_property" not in codes(asset)


@pytest.mark.parametrize("credential", [
    "ghp_" + "X" * 36,
    "github_pat_" + "X" * 20,
    "AKIA" + "A" * 16,
    "AIza" + "A" * 35,
    "xoxb-" + "A" * 12,
    "sk_live_" + "A" * 16,
])
def test_credential_patterns_are_not_retained_in_titles_and_identifiers(credential):
    source = responses()
    source["dashboards"][0]["title"] = f"Title {credential}"
    asset = normalize_looker_api_export("project", source)
    assert not asset.properties["dashboards"]
    assert credential not in repr(asset)

    source = responses()
    element = source["dashboards"][0]["dashboard_elements"][0]
    element["title"] = f"Tile {credential}"
    element["id"] = credential
    asset = normalize_looker_api_export("project", source)
    assert not asset.properties["dashboards"][0]["elements"]
    assert credential not in repr(asset)

    source = responses()
    source["dashboards"][0]["id"] = credential
    source["dashboards"][0]["dashboard_elements"][0]["query_id"] = credential
    source["explores"][0]["sql_table_name"] = f"project.dataset.{credential}"
    asset = normalize_looker_api_export("project", source)
    assert credential not in repr(asset)
    assert "sql_table_name" not in asset.properties["views"][0]


def test_credential_patterns_are_rejected_in_project_and_semantic_names():
    credential = "ghp_" + "X" * 36
    with pytest.raises(ValueError):
        normalize_looker_api_export(credential, responses())
    source = responses()
    source["explores"][0]["model_name"] = credential
    source["explores"][0]["fields"]["dimensions"][0]["name"] = f"orders.{credential}"
    asset = normalize_looker_api_export("project", source)
    assert credential not in repr(asset)
    assert not asset.properties["views"]

    source = responses()
    field = source["explores"][0]["fields"]["dimensions"][0]
    field["name"] = f"orders.{credential}"
    field["sql"] = "${TABLE}." + credential
    asset = normalize_looker_api_export("project", source)
    assert credential not in repr(asset)
    assert "joined_or_invalid_field" in codes(asset)


def test_malformed_and_ambiguous_responses_do_not_raise_or_invent():
    source = responses()
    source["explores"].append(copy.deepcopy(source["explores"][0]))
    source["explores"].append(None)
    source["dashboards"].extend([None, {"title": "bad", "dashboard_elements": 4}])
    source["dashboards"][0]["dashboard_elements"][0]["query"]["model"] = []
    asset = normalize_looker_api_export("project", source)
    assert not asset.properties["views"]
    assert {"invalid_or_ambiguous_identity", "expected_object",
            "unresolved_query_fields", "dashboard_elements_missing_or_invalid"} <= set(codes(asset))


@pytest.mark.parametrize("payload,exception", [
    (None, ValueError), ({}, ValueError), ({"explores": [], "dashboards": [], "extra": 1}, ValueError),
    ({"explores": {}, "dashboards": []}, TypeError),
])
def test_invalid_envelope(payload, exception):
    with pytest.raises(exception):
        normalize_looker_api_export("project", payload)


def test_unsafe_input_identifiers_and_arbitrary_sql_are_not_retained():
    with pytest.raises(ValueError):
        normalize_looker_api_export("my-password", responses())
    source = responses()
    source["explores"][0]["sql_table_name"] = "password=secret"
    source["explores"][0]["fields"]["dimensions"][0]["sql"] = "secret123"
    source["dashboards"][0]["title"] = "my_token"
    asset = normalize_looker_api_export("project", source)
    assert "secret123" not in repr(asset) and "password=secret" not in repr(asset)
    assert "source_table_missing_or_unsupported" in codes(asset)
    assert "invalid_dashboard" in codes(asset)


def test_display_titles_and_strict_semantic_names():
    source = responses()
    dashboard = source["dashboards"][0]
    dashboard["title"] = "Revenue by Region"
    dashboard["description"] = "private arbitrary freeform description"
    dashboard["dashboard_elements"][0]["title"] = "Sales - by Region"
    asset = normalize_looker_api_export("test-project", source)
    assert asset.properties["dashboards"][0]["name"] == "Revenue by Region"
    assert asset.properties["dashboards"][0]["elements"][0]["name"] == "Sales - by Region"
    ids = json.loads(asset.labels["looker_source_identifiers"])
    assert any(x.get("title") == "Revenue by Region" for x in ids)
    assert any(x.get("title") == "Sales - by Region" for x in ids)
    assert "private arbitrary freeform description" not in repr(asset)

    source["explores"][0]["view_name"] = "orders by region"
    strict_asset = normalize_looker_api_export("test-project", source)
    assert not strict_asset.properties["views"]
    assert "invalid_or_ambiguous_identity" in codes(strict_asset)


@pytest.mark.parametrize("title", [
    "", " leading", "trailing ", "with\ttab", "with\nnewline", "é",
    "Revenue/Region", "my secret", "api_key-1", "api key", "pass word",
    "private-key", "a" * 65,
])
def test_invalid_display_titles_are_not_retained(title):
    source = responses()
    source["dashboards"][0]["title"] = title
    asset = normalize_looker_api_export("project", source)
    assert not asset.properties["dashboards"]
    assert "invalid_dashboard" in codes(asset)

    source = responses()
    source["dashboards"][0]["dashboard_elements"][0]["title"] = title
    asset = normalize_looker_api_export("project", source)
    assert not asset.properties["dashboards"][0]["elements"]
    assert "invalid_element" in codes(asset)


@pytest.mark.parametrize("title", ["A", "1", "_", "-", "A B-C_1", "a" * 64])
def test_allowed_display_title_boundaries(title):
    source = responses()
    source["dashboards"][0]["title"] = title
    source["dashboards"][0]["dashboard_elements"][0]["title"] = title
    asset = normalize_looker_api_export("project", source)
    assert asset.properties["dashboards"][0]["name"] == title
    assert asset.properties["dashboards"][0]["elements"][0]["name"] == title


def test_incomplete_or_joined_context_blocks_generator_visuals(monkeypatch):
    sibling = Path(__file__).resolve().parents[2] / "TableauToPowerBI"
    if not (sibling / "powerbi_import" / "pbip_generator.py").is_file():
        pytest.skip("optional TableauToPowerBI source tree not available")
    monkeypatch.syspath_prepend(str(sibling))
    from bqtofabric.generator.looker_powerbi import generate_looker_powerbi_project

    source = responses()
    source["explores"][0]["joins"] = [{"name": "customers"}]
    asset = normalize_looker_api_export("test-project", source)
    result = generate_looker_powerbi_project(asset)
    assert not any(path.endswith("/visual.json") for path in result.files)
    assert {"joins_not_migrated", "unresolved_model_context"} <= {
        issue["code"] for issue in result.review["issues"]
    }


def test_linked_look_blocks_generator_visuals(monkeypatch):
    sibling = Path(__file__).resolve().parents[2] / "TableauToPowerBI"
    if not (sibling / "powerbi_import" / "pbip_generator.py").is_file():
        pytest.skip("optional TableauToPowerBI source tree not available")
    monkeypatch.syspath_prepend(str(sibling))
    from bqtofabric.generator.looker_powerbi import generate_looker_powerbi_project

    source = responses()
    source["dashboards"][0]["dashboard_elements"][0]["look_id"] = "private_look_identifier"
    asset = normalize_looker_api_export("project", source)
    result = generate_looker_powerbi_project(asset)
    assert not any(path.endswith("/visual.json") for path in result.files)
    assert "linked_look_not_migrated" in codes(asset)
    assert "private_look_identifier" not in repr((asset, result))


@pytest.mark.parametrize("key", [
    "sql_always_where", "access_grants", "required_access_grants", "unknown_restriction",
])
def test_unresolved_explore_evidence_blocks_generator_visuals(key, monkeypatch):
    sibling = Path(__file__).resolve().parents[2] / "TableauToPowerBI"
    if not (sibling / "powerbi_import" / "pbip_generator.py").is_file():
        pytest.skip("optional TableauToPowerBI source tree not available")
    monkeypatch.syspath_prepend(str(sibling))
    from bqtofabric.generator.looker_powerbi import generate_looker_powerbi_project

    source = responses()
    if key == "unknown_restriction":
        source["explores"][0][key] = {"confidential_value": "value"}
    else:
        del source["explores"][0][key]
    asset = normalize_looker_api_export("project", source)
    result = generate_looker_powerbi_project(asset)
    assert not any(path.endswith("/visual.json") for path in result.files)
    assert "unresolved_model_context" in {item["code"] for item in result.review["issues"]}
    assert "confidential_value" not in repr((asset, result))


def test_missing_query_shaping_and_empty_export():
    source = responses()
    del source["dashboards"][0]["dashboard_elements"][0]["query"]["dynamic_fields"]
    asset = normalize_looker_api_export("project", source)
    assert "query_semantics_evidence_missing_or_invalid" in codes(asset)
    assert asset.properties["dashboards"][0]["elements"][0]["unsupported"]
    empty = normalize_looker_api_export("project", {"explores": [], "dashboards": []})
    assert {"no_explore_responses", "no_dashboard_responses"} <= set(codes(empty))
