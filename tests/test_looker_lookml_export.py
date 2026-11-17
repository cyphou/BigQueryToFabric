"""Focused offline contract tests for the versioned LookML export normalizer."""

import copy
import json

import pytest

from bqtofabric.looker_api_export import normalize_looker_api_export
from bqtofabric.looker_lookml_export import normalize_looker_lookml_export
from bqtofabric.models import ObjectKind

PROJECT = "analytics"
EXPLORE_ID = f"{PROJECT}.looker_lookml.explore.orders"
REGION_ID = f"{PROJECT}.looker_lookml.field.orders.region"
SALES_ID = f"{PROJECT}.looker_lookml.field.orders.sales"
DASHBOARD_ID = f"{PROJECT}.looker_lookml.dashboard.sales"
ELEMENT_ID = f"{PROJECT}.looker_lookml.element.sales.trend"


def export_payload() -> dict:
    return {
        "schema_version": "1.0",
        "project_id": PROJECT,
        "explores": [{
            "source_id": EXPLORE_ID,
            "name": "orders",
            "sql_table_name": "warehouse.sales.orders",
            "dimensions": [{
                "source_id": REGION_ID,
                "name": "region",
                "type": "string",
                "sql": "${TABLE}.region",
            }],
            "measures": [{
                "source_id": SALES_ID,
                "name": "sales",
                "type": "sum",
                "sql": "${TABLE}.amount",
            }],
        }],
        "dashboards": [{
            "source_id": DASHBOARD_ID,
            "title": "Sales",
            "elements": [{
                "source_id": ELEMENT_ID,
                "title": "Trend",
                "explore_source_id": EXPLORE_ID,
                "field_source_ids": [REGION_ID, SALES_ID],
                "type": "line",
            }],
        }],
    }


def scoped_unknown_property_payload() -> dict:
    orders_id = f"{PROJECT}.looker_lookml.explore.orders"
    customers_id = f"{PROJECT}.looker_lookml.explore.customers"
    products_id = f"{PROJECT}.looker_lookml.explore.products"
    orders_region_id = f"{PROJECT}.looker_lookml.field.orders.region"
    orders_sales_id = f"{PROJECT}.looker_lookml.field.orders.sales"
    customers_email_id = f"{PROJECT}.looker_lookml.field.customers.email"
    customers_country_id = f"{PROJECT}.looker_lookml.field.customers.country"
    customers_spend_id = f"{PROJECT}.looker_lookml.field.customers.spend"
    products_category_id = f"{PROJECT}.looker_lookml.field.products.category"
    products_units_id = f"{PROJECT}.looker_lookml.field.products.units"

    def element(source_id: str, title: str, explore_id: str, field_ids: list[str]) -> dict:
        return {
            "source_id": source_id,
            "title": title,
            "explore_source_id": explore_id,
            "field_source_ids": field_ids,
            "type": "line",
        }

    return {
        "schema_version": "1.0",
        "project_id": PROJECT,
        "explores": [
            {
                "source_id": orders_id,
                "name": "orders",
                "sql_table_name": "warehouse.sales.orders",
                "dimensions": [{
                    "source_id": orders_region_id,
                    "name": "region",
                    "type": "string",
                    "sql": "${TABLE}.region",
                }],
                "measures": [{
                    "source_id": orders_sales_id,
                    "name": "sales",
                    "type": "sum",
                    "sql": "${TABLE}.amount",
                }],
                "private_explore_value": "secret_explore_value",
            },
            {
                "source_id": customers_id,
                "name": "customers",
                "sql_table_name": "warehouse.crm.customers",
                "dimensions": [
                    {
                        "source_id": customers_email_id,
                        "name": "email",
                        "type": "string",
                        "sql": "${TABLE}.email",
                        "private_field_value": "secret_field_value",
                    },
                    {
                        "source_id": customers_country_id,
                        "name": "country",
                        "type": "string",
                        "sql": "${TABLE}.country",
                    },
                ],
                "measures": [{
                    "source_id": customers_spend_id,
                    "name": "spend",
                    "type": "sum",
                    "sql": "${TABLE}.spend",
                }],
            },
            {
                "source_id": products_id,
                "name": "products",
                "sql_table_name": "warehouse.catalog.products",
                "dimensions": [{
                    "source_id": products_category_id,
                    "name": "category",
                    "type": "string",
                    "sql": "${TABLE}.category",
                }],
                "measures": [{
                    "source_id": products_units_id,
                    "name": "units",
                    "type": "sum",
                    "sql": "${TABLE}.units",
                }],
            },
        ],
        "dashboards": [
            {
                "source_id": f"{PROJECT}.looker_lookml.dashboard.private",
                "title": "Private dashboard",
                "private_dashboard_value": "secret_dashboard_value",
                "elements": [
                    element(
                        f"{PROJECT}.looker_lookml.element.private.first",
                        "Private first",
                        products_id,
                        [products_category_id, products_units_id],
                    ),
                    element(
                        f"{PROJECT}.looker_lookml.element.private.second",
                        "Private second",
                        products_id,
                        [products_category_id, products_units_id],
                    ),
                ],
            },
            {
                "source_id": f"{PROJECT}.looker_lookml.dashboard.reviewed",
                "title": "Reviewed dashboard",
                "elements": [
                    element(
                        f"{PROJECT}.looker_lookml.element.reviewed.orders",
                        "Orders visual",
                        orders_id,
                        [orders_region_id, orders_sales_id],
                    ),
                    element(
                        f"{PROJECT}.looker_lookml.element.reviewed.email",
                        "Email visual",
                        customers_id,
                        [customers_email_id, customers_spend_id],
                    ),
                    element(
                        f"{PROJECT}.looker_lookml.element.reviewed.country",
                        "Country visual",
                        customers_id,
                        [customers_country_id, customers_spend_id],
                    ),
                    {
                        **element(
                            f"{PROJECT}.looker_lookml.element.reviewed.tagged",
                            "Tagged visual",
                            products_id,
                            [products_category_id, products_units_id],
                        ),
                        "private_element_value": "secret_element_value",
                    },
                    element(
                        f"{PROJECT}.looker_lookml.element.reviewed.independent",
                        "Independent visual",
                        products_id,
                        [products_category_id, products_units_id],
                    ),
                ],
            },
        ],
    }


def diagnostic_report(asset) -> list[dict[str, str]]:
    return json.loads(asset.labels["looker_lookml_ingestion_report"])


def diagnostic_codes(asset) -> set[str]:
    return {entry["code"] for entry in diagnostic_report(asset)}


def test_valid_small_export_has_generator_canonical_shape_without_migration_claims():
    asset = normalize_looker_lookml_export(export_payload())

    assert asset.kind is ObjectKind.LOOKER_ASSET
    assert asset.discovered_from == "external_payload"
    assert asset.properties["views"] == [{
        "name": "orders",
        "dimensions": [{"name": "region", "type": "string", "sql": "${TABLE}.region"}],
        "measures": [{"name": "sales", "type": "sum", "sql": "${TABLE}.amount"}],
        "sql_table_name": "warehouse.sales.orders",
    }]
    assert asset.properties["dashboards"] == [{
        "name": "Sales",
        "elements": [{
            "name": "Trend",
            "type": "line",
            "view": "orders",
            "dimensions": ["region"],
            "measures": ["sales"],
        }],
    }]

    # This is the documented input shape consumed by generate_looker_powerbi_project.
    assert set(asset.properties) == {"views", "dashboards", "security", "explores"}
    assert {"name", "dimensions", "measures"} <= set(asset.properties["views"][0])
    assert {
        "name", "type", "view", "dimensions", "measures"
    } <= set(asset.properties["dashboards"][0]["elements"][0])
    assert asset.properties["security"] == [
        {"path": "project", "code": "security_evidence_unresolved"}
    ]
    assert asset.properties["explores"] == [
        {"path": "project", "code": "lookml_semantics_and_parity_unverified"}
    ]
    assert "security_verified" not in repr(asset)
    assert "parity_verified" not in repr(asset)


def test_schema_version_and_source_project_provenance_are_auditable():
    asset = normalize_looker_lookml_export(export_payload())

    assert asset.source_id == f"{PROJECT}.looker_lookml_export"
    assert asset.discovered_from == "external_payload"
    provenance = json.loads(asset.labels["looker_lookml_provenance"])
    assert provenance == {"project_id": PROJECT, "schema_version": "1.0"}


def test_resolved_dependency_edges_are_auditable_by_source_identity():
    asset = normalize_looker_lookml_export(export_payload())

    edges = json.loads(asset.labels["looker_lookml_dependency_edges"])
    assert edges == [{
        "element_source_id": ELEMENT_ID,
        "explore_source_id": EXPLORE_ID,
        "field_source_ids": [REGION_ID, SALES_ID],
    }]


def test_versioned_envelope_is_required_and_invalid_versions_are_rejected():
    payload = export_payload()
    payload["schema_version"] = "2.0"
    with pytest.raises(ValueError):
        normalize_looker_lookml_export(payload)

    payload = export_payload()
    del payload["schema_version"]
    with pytest.raises(ValueError):
        normalize_looker_lookml_export(payload)


def test_stable_project_scoped_identities_are_required_not_inferred():
    payload = export_payload()
    del payload["explores"][0]["source_id"]
    del payload["dashboards"][0]["elements"][0]["source_id"]

    asset = normalize_looker_lookml_export(payload)

    assert "missing_identity" in diagnostic_codes(asset)
    assert not asset.properties["views"]
    assert not asset.properties["dashboards"][0]["elements"]
    assert all(
        entry["source_id"] not in {EXPLORE_ID, ELEMENT_ID}
        for entry in json.loads(asset.labels["looker_source_identifiers"])
    )


def test_identity_is_not_inferred_from_title_name_or_record_order():
    payload = export_payload()
    payload["explores"][0]["source_id"] = f"{PROJECT}.looker_lookml.explore.Sales"
    payload["dashboards"][0]["elements"][0]["explore_source_id"] = EXPLORE_ID
    payload["dashboards"][0]["elements"][0]["field_source_ids"] = ["region", "sales"]

    asset = normalize_looker_lookml_export(payload)

    assert "unresolved_or_ambiguous_explore_reference" in diagnostic_codes(asset)
    assert asset.properties["dashboards"][0]["elements"][0]["unsupported"] is True
    assert asset.properties["views"][0]["name"] == "orders"


def test_exact_references_resolve_only_by_ids_not_matching_names():
    payload = export_payload()
    payload["dashboards"][0]["elements"][0]["field_source_ids"] = ["region", "sales"]

    asset = normalize_looker_lookml_export(payload)

    visual = asset.properties["dashboards"][0]["elements"][0]
    assert "unresolved_or_ambiguous_field_reference" in diagnostic_codes(asset)
    assert visual["unsupported"] is True
    assert visual["dimensions"] == []
    assert visual["measures"] == []


def test_duplicate_and_conflicting_identities_are_omitted_and_ambiguous():
    payload = export_payload()
    payload["explores"].append(copy.deepcopy(payload["explores"][0]))
    payload["explores"][1]["name"] = "orders_archive"

    asset = normalize_looker_lookml_export(payload)

    assert {"duplicate_identity", "conflicting_identity"} <= diagnostic_codes(asset)
    assert not asset.properties["views"]
    assert "unresolved_or_ambiguous_explore_reference" in diagnostic_codes(asset)
    serialized = json.dumps(diagnostic_report(asset), sort_keys=True)
    assert "orders_archive" not in serialized
    assert EXPLORE_ID not in serialized


def test_missing_and_cross_explore_references_do_not_resolve():
    payload = export_payload()
    payload["dashboards"][0]["elements"][0]["explore_source_id"] = (
        f"{PROJECT}.looker_lookml.explore.missing"
    )

    asset = normalize_looker_lookml_export(payload)

    assert "unresolved_or_ambiguous_explore_reference" in diagnostic_codes(asset)
    assert asset.properties["dashboards"][0]["elements"][0]["unsupported"] is True


def test_unsupported_values_fail_closed_and_diagnostics_are_deterministic():
    payload = export_payload()
    marker = "private_value_should_never_be_retained"
    payload["explores"][0]["dimensions"][0]["sql"] = marker
    payload["explores"][0]["unexpected_option"] = {"value": marker}
    before = copy.deepcopy(payload)

    first = normalize_looker_lookml_export(payload)
    second = normalize_looker_lookml_export(copy.deepcopy(payload))

    assert payload == before
    assert "unsupported_field_expression" in diagnostic_codes(first)
    assert "unsupported_input_property" in diagnostic_codes(first)
    assert first.labels["looker_lookml_ingestion_report"] == second.labels[
        "looker_lookml_ingestion_report"
    ]
    assert marker not in repr(first)
    assert marker not in first.labels["looker_lookml_ingestion_report"]
    assert not first.properties["views"][0]["dimensions"]


def test_unknown_properties_are_isolated_by_scope_without_leaking_values():
    payload = scoped_unknown_property_payload()
    before = copy.deepcopy(payload)

    first = normalize_looker_lookml_export(payload)
    second = normalize_looker_lookml_export(copy.deepcopy(payload))

    assert payload == before
    assert first.labels["looker_lookml_ingestion_report"] == second.labels[
        "looker_lookml_ingestion_report"
    ]
    report = diagnostic_report(first)
    assert all(set(entry) == {"path", "code"} for entry in report)
    assert {
        entry["path"]
        for entry in report
        if entry["code"] == "unsupported_input_property"
    } == {
        "explores[0]",
        "explores[1].dimensions[0]",
        "dashboards[0]",
        "dashboards[1].elements[3]",
    }
    for secret in (
        "secret_explore_value",
        "secret_field_value",
        "secret_dashboard_value",
        "secret_element_value",
    ):
        assert secret not in repr(first)
        assert secret not in first.labels["looker_lookml_ingestion_report"]

    views = {view["name"]: view for view in first.properties["views"]}
    # Unknown explore metadata does not discard its safe view fields.
    assert views["orders"] == {
        "name": "orders",
        "dimensions": [{"name": "region", "type": "string", "sql": "${TABLE}.region"}],
        "measures": [{"name": "sales", "type": "sum", "sql": "${TABLE}.amount"}],
        "sql_table_name": "warehouse.sales.orders",
    }
    # The field with unknown metadata is omitted; its sibling fields remain.
    assert views["customers"]["dimensions"] == [
        {"name": "country", "type": "string", "sql": "${TABLE}.country"}
    ]
    assert views["customers"]["measures"] == [
        {"name": "spend", "type": "sum", "sql": "${TABLE}.spend"}
    ]

    dashboards = {dashboard["name"]: dashboard for dashboard in first.properties["dashboards"]}
    private_elements = dashboards["Private dashboard"]["elements"]
    assert [visual["unsupported"] for visual in private_elements] == [True, True]

    reviewed = {
        visual["name"]: visual for visual in dashboards["Reviewed dashboard"]["elements"]
    }
    assert reviewed["Orders visual"]["unsupported"] is True
    assert reviewed["Email visual"]["unsupported"] is True
    assert "unsupported" not in reviewed["Country visual"]
    assert reviewed["Country visual"]["view"] == "customers"
    assert reviewed["Tagged visual"]["unsupported"] is True
    # A clean element in the same dashboard remains convertible at the normalizer layer.
    assert reviewed["Independent visual"] == {
        "name": "Independent visual",
        "type": "line",
        "view": "products",
        "dimensions": ["category"],
        "measures": ["units"],
    }
    assert first.properties["security"] == [
        {"path": "project", "code": "security_evidence_unresolved"}
    ]
    assert first.properties["explores"] == [
        {"path": "project", "code": "lookml_semantics_and_parity_unverified"}
    ]
    assert first.properties.keys() == {"views", "dashboards", "security", "explores"}


def test_unsafe_project_and_foreign_project_identities_are_not_retained():
    with pytest.raises(ValueError):
        normalize_looker_lookml_export({
            **export_payload(),
            "project_id": "private-password-project",
        })

    payload = export_payload()
    payload["explores"][0]["source_id"] = "another_project.looker_lookml.explore.orders"
    asset = normalize_looker_lookml_export(payload)

    assert "invalid_identity" in diagnostic_codes(asset)
    assert not asset.properties["views"]
    assert "another_project" not in repr(asset)


def test_existing_api_normalizer_contract_remains_unchanged():
    asset = normalize_looker_api_export("project", {"explores": [], "dashboards": []})

    assert asset.source_id == "project.looker.api_export"
    assert asset.kind is ObjectKind.LOOKER_ASSET
    assert asset.discovered_from == "external_payload"
    assert "looker_ingestion_report" in asset.labels
    assert "looker_source_identifiers" in asset.labels
    assert asset.properties["views"] == []
    assert asset.properties["dashboards"] == []
