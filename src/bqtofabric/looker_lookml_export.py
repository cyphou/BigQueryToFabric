"""Normalize an offline, versioned LookML-derived metadata export.

The public entry point is :func:`normalize_looker_lookml_export`. Its input
contract is JSON schema ``bqtofabric.looker-lookml-export/1.0``::

    {
      "schema_version": "1.0",
      "project_id": "analytics",
      "explores": [{
        "source_id": "analytics.looker_lookml.explore.orders",
        "name": "orders",
        "sql_table_name": "warehouse.sales.orders",
        "dimensions": [{
          "source_id": "analytics.looker_lookml.field.orders.region",
          "name": "region", "type": "string", "sql": "${TABLE}.region"
        }],
        "measures": [{
          "source_id": "analytics.looker_lookml.field.orders.sales",
          "name": "sales", "type": "sum", "sql": "${TABLE}.amount"
        }]
      }],
      "dashboards": [{
        "source_id": "analytics.looker_lookml.dashboard.sales",
        "title": "Sales",
        "elements": [{
          "source_id": "analytics.looker_lookml.element.sales.trend",
          "title": "Trend",
          "explore_source_id": "analytics.looker_lookml.explore.orders",
          "field_source_ids": ["analytics.looker_lookml.field.orders.region",
                               "analytics.looker_lookml.field.orders.sales"],
          "type": "line"
        }]
      }]
    }

Explore, field, dashboard, and element source IDs are caller-supplied stable
identities and must use the exact project-scoped prefixes shown above. The
normalizer does not derive IDs from names, titles, or positions. Dashboard
references resolve by exact source ID only. This is parsed metadata, not a raw
LookML parser or a live Looker integration. Unknown or unsafe input is never
copied into the canonical properties, labels, or diagnostics.

The output is a review-only ``LOOKER_ASSET`` with ``external_payload``
provenance. Only safe identifiers, direct ``${TABLE}.column`` expressions,
the supported field types and supported visual types are retained. The
diagnostic JSON in ``labels["looker_lookml_ingestion_report"]`` contains only
fixed paths and codes; ``labels["looker_source_identifiers"]`` preserves
validated source IDs for traceability. Security, completeness, effective
access, runtime behavior, and parity remain unverified; omitted fields are
never treated as evidence that the corresponding semantics are absent.
The value-safe ``looker_lookml_provenance`` and
``looker_lookml_dependency_edges`` labels record the validated envelope and
fully resolved element references using exact source IDs.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from .models import BigQueryObject, ObjectKind

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_ID_PART = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,63}$")
_DISPLAY = re.compile(r"^[A-Za-z0-9_ -]{1,64}$")
_SENSITIVE = re.compile(
    r"password|passwd|secret|token|credential|authorization|apikey|api_key|"
    r"privatekey|private_key|accesskey|access_key|connectionstring|connection_string",
    re.IGNORECASE,
)
_CREDENTIAL = re.compile(
    r"gh[opsur]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"(?:AKIA|ASIA)[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{35}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|sk_(?:live|test)_[A-Za-z0-9]{16,}",
    re.IGNORECASE,
)
_RESERVED = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", re.IGNORECASE)
_COLUMN = re.compile(r"^\$\{TABLE\}\.([A-Za-z_][A-Za-z0-9_]*)$")
_TABLE = re.compile(
    r"^`?([A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*){0,2})`?$"
)
_DIMENSIONS = frozenset({"string", "number", "yesno", "date"})
_MEASURES = frozenset({"count", "sum", "average", "min", "max", "count_distinct"})
_VISUALS = frozenset({"table", "bar", "column", "line", "card"})
_MAX_RECORDS = 2_000
_MAX_FIELDS_PER_EXPLORE = 2_000
_MAX_REFERENCES_PER_ELEMENT = 256
_MAX_TOTAL_FIELDS = 20_000
_MAX_TOTAL_ELEMENTS = 20_000


def _safe_name(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(_NAME.fullmatch(value))
        and not _SENSITIVE.search(value)
        and not _CREDENTIAL.search(value)
        and not _RESERVED.fullmatch(value)
    )


def _safe_title(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(_DISPLAY.fullmatch(value))
        and value == value.strip()
        and not _SENSITIVE.search(value)
        and not _SENSITIVE.search(re.sub(r"[ _-]", "", value))
        and not _CREDENTIAL.search(value)
    )


def _safe_project(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(_ID_PART.fullmatch(value))
        and not _SENSITIVE.search(value)
        and not _CREDENTIAL.search(value)
        and not _RESERVED.fullmatch(value)
    )


def _identity(value: Any, project_id: str, kind: str) -> bool:
    if not isinstance(value, str) or len(value) > 512:
        return False
    prefix = f"{project_id}.looker_lookml.{kind}."
    if not value.startswith(prefix):
        return False
    suffix = value[len(prefix):]
    parts = suffix.split(".")
    return (
        bool(parts)
        and all(
            _ID_PART.fullmatch(part)
            and not _SENSITIVE.search(part)
            and not _CREDENTIAL.search(part)
            and not _RESERVED.fullmatch(part)
            for part in parts
        )
    )


def _table_name(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    match = _TABLE.fullmatch(value)
    if not match or value.startswith("`") != value.endswith("`"):
        return False
    return not _SENSITIVE.search(match.group(1)) and not _CREDENTIAL.search(match.group(1))


def normalize_looker_lookml_export(payload: Any) -> BigQueryObject:
    """Normalize schema ``bqtofabric.looker-lookml-export/1.0`` offline.

    The root must contain exactly ``schema_version``, ``project_id``,
    ``explores``, and ``dashboards``. Explore records require ``source_id`` and
    ``name`` and may contain ``sql_table_name``, ``dimensions``, and
    ``measures``. Field records require ``source_id``, ``name``, ``type``,
    and (except ``count`` measures) a direct-column ``sql`` expression.
    Dashboard records require ``source_id``, ``title``, and ``elements``;
    elements require ``source_id``, ``title``, exact ``explore_source_id`` and
    ``field_source_ids`` references, and a supported ``type``. IDs must match
    ``<project>.looker_lookml.{explore,field,dashboard,element}.<stable-id>``.

    Malformed individual records are omitted and diagnosed. Root contract
    errors raise ``ValueError`` or ``TypeError`` without echoing input values.
    Diagnostics are deterministic JSON objects with only ``path`` and ``code``.
    No filesystem, network, credential, or raw LookML access occurs.
    """
    if not isinstance(payload, dict):
        raise TypeError("LookML export must be a JSON object")
    if set(payload) != {"schema_version", "project_id", "explores", "dashboards"}:
        raise ValueError("LookML export root does not match schema 1.0")
    if payload.get("schema_version") != "1.0":
        raise ValueError("Unsupported LookML export schema version")
    project_id = payload.get("project_id")
    if not _safe_project(project_id):
        raise ValueError("LookML export project_id is invalid")
    assert isinstance(project_id, str)
    if not isinstance(payload["explores"], list) or not isinstance(payload["dashboards"], list):
        raise TypeError("LookML export explores and dashboards must be arrays")
    if len(payload["explores"]) > _MAX_RECORDS or len(payload["dashboards"]) > _MAX_RECORDS:
        raise ValueError("LookML export exceeds record limits")

    issues: list[dict[str, str]] = []
    identifiers: list[dict[str, str]] = []
    dependency_edges: list[dict[str, Any]] = []
    properties: dict[str, Any] = {"views": [], "dashboards": []}

    def issue(path: str, code: str) -> None:
        issues.append({"path": path, "code": code})

    # First pass registers all declared identities. Every repeated ID is
    # excluded, even when the duplicate records happen to be identical.
    identity_records: list[tuple[str, str, str, dict[str, Any]]] = []
    total_fields = 0
    total_elements = 0
    for collection, kind in (
        ("explores", "explore"),
        ("dashboards", "dashboard"),
    ):
        for index, record in enumerate(payload[collection]):
            path = f"{collection}[{index}]"
            if not isinstance(record, dict):
                issue(path, "expected_object")
                continue
            source_id = record.get("source_id")
            if not isinstance(source_id, str) or not _identity(source_id, project_id, kind):
                issue(
                    path,
                    "missing_identity" if source_id is None or source_id == ""
                    else "invalid_identity",
                )
                continue
            identity_records.append((source_id, kind, path, record))
            identifiers.append({"kind": kind, "path": path, "source_id": source_id})
            if collection == "explores":
                for group in ("dimensions", "measures"):
                    fields = record.get(group)
                    if not isinstance(fields, list):
                        continue
                    if total_fields >= _MAX_TOTAL_FIELDS:
                        issue(path, "total_field_limit_exceeded")
                        break
                    if len(fields) > _MAX_FIELDS_PER_EXPLORE:
                        issue(path, "field_limit_exceeded")
                        continue
                    for field_index, field in enumerate(fields):
                        if total_fields >= _MAX_TOTAL_FIELDS:
                            issue(path, "total_field_limit_exceeded")
                            break
                        total_fields += 1
                        field_path = f"{path}.{group}[{field_index}]"
                        if not isinstance(field, dict):
                            issue(field_path, "expected_object")
                            continue
                        field_id = field.get("source_id")
                        if not isinstance(field_id, str) or not _identity(
                            field_id, project_id, "field"
                        ):
                            issue(
                                field_path,
                                "missing_identity" if field_id is None or field_id == ""
                                else "invalid_identity",
                            )
                            continue
                        identity_records.append((field_id, "field", field_path, field))
                        identifiers.append({
                            "kind": "field",
                            "parent_source_id": source_id,
                            "path": field_path,
                            "source_id": field_id,
                        })

            if collection == "dashboards":
                elements = record.get("elements")
                if isinstance(elements, list):
                    if total_elements >= _MAX_TOTAL_ELEMENTS:
                        issue(path, "total_element_limit_exceeded")
                        continue
                    if len(elements) > _MAX_RECORDS:
                        issue(path, "element_limit_exceeded")
                        continue
                    for element_index, element in enumerate(elements):
                        if total_elements >= _MAX_TOTAL_ELEMENTS:
                            issue(path, "total_element_limit_exceeded")
                            break
                        total_elements += 1
                        element_path = f"{path}.elements[{element_index}]"
                        if not isinstance(element, dict):
                            issue(element_path, "expected_object")
                            continue
                        element_id = element.get("source_id")
                        if not isinstance(element_id, str) or not _identity(
                            element_id, project_id, "element"
                        ):
                            issue(
                                element_path,
                                "missing_identity" if element_id is None or element_id == ""
                                else "invalid_identity",
                            )
                            continue
                        identity_records.append((element_id, "element", element_path, element))
                        identifiers.append({
                            "kind": "element",
                            "parent_source_id": source_id,
                            "path": element_path,
                            "source_id": element_id,
                        })

    identity_counts = Counter(record[0] for record in identity_records)
    duplicate_groups: dict[str, list[tuple[str, str, str, dict[str, Any]]]] = {}
    for entry in identity_records:
        if identity_counts[entry[0]] > 1:
            duplicate_groups.setdefault(entry[0], []).append(entry)
    for source_id in sorted(duplicate_groups):
        occurrences = duplicate_groups[source_id]
        identity_values = set()
        for _, kind, _, record in occurrences:
            identity_value = record.get("name", record.get("title"))
            valid_identity_value = (
                _safe_title(identity_value) if kind in {"dashboard", "element"}
                else _safe_name(identity_value)
            )
            if valid_identity_value:
                identity_values.add(identity_value)
        for _, _, path, _ in occurrences:
            issue(path, "duplicate_identity")
            if len(identity_values) > 1:
                issue(path, "conflicting_identity")

    unique_identity = {
        source_id: (kind, path, record)
        for source_id, kind, path, record in identity_records
        if identity_counts[source_id] == 1
    }
    valid_fields: dict[str, tuple[str, str, str]] = {}
    valid_explores: dict[str, dict[str, Any]] = {}
    field_identity_owner: dict[str, str] = {}
    unsupported_field_ids: set[str] = set()
    processed_fields = 0

    for index, explore in enumerate(payload["explores"]):
        path = f"explores[{index}]"
        if not isinstance(explore, dict):
            continue
        source_id = explore.get("source_id")
        if (not isinstance(source_id, str) or source_id not in unique_identity
                or unique_identity[source_id][0] != "explore"):
            continue
        unsupported_explore_properties = bool(
            set(explore) - {"source_id", "name", "sql_table_name", "dimensions", "measures"}
        )
        if unsupported_explore_properties:
            issue(path, "unsupported_input_property")
        name = explore.get("name")
        if not _safe_name(name):
            issue(path, "invalid_explore_name")
            continue
        assert isinstance(name, str)
        view: dict[str, Any] = {"name": name, "dimensions": [], "measures": []}
        if "sql_table_name" in explore:
            if _table_name(explore["sql_table_name"]):
                view["sql_table_name"] = explore["sql_table_name"]
            else:
                issue(path, "source_table_unsupported")
        valid_explores[source_id] = {
            "name": name,
            "view": view,
            "path": path,
            "unsupported_properties": unsupported_explore_properties,
        }

        for group in ("dimensions", "measures"):
            fields = explore.get(group)
            if not isinstance(fields, list):
                issue(path, f"{group}_metadata_missing_or_invalid")
                continue
            if processed_fields >= _MAX_TOTAL_FIELDS:
                issue(path, "total_field_limit_exceeded")
                break
            if len(fields) > _MAX_FIELDS_PER_EXPLORE:
                continue
            seen_names: Counter[str] = Counter(
                field["name"].casefold()
                for field in fields
                if isinstance(field, dict) and _safe_name(field.get("name"))
            )
            for field_index, field in enumerate(fields):
                if processed_fields >= _MAX_TOTAL_FIELDS:
                    issue(path, "total_field_limit_exceeded")
                    break
                processed_fields += 1
                field_path = f"{path}.{group}[{field_index}]"
                if not isinstance(field, dict):
                    continue
                field_id = field.get("source_id")
                if (not isinstance(field_id, str) or field_id not in unique_identity
                        or unique_identity[field_id][0] != "field"):
                    continue
                unsupported_field_properties = bool(
                    set(field) - {"source_id", "name", "type", "sql"}
                )
                if unsupported_field_properties:
                    issue(field_path, "unsupported_input_property")
                field_name = field.get("name")
                field_type = field.get("type")
                if not _safe_name(field_name):
                    issue(field_path, "invalid_field_name")
                    continue
                assert isinstance(field_name, str)
                if seen_names[field_name.casefold()] != 1:
                    issue(field_path, "duplicate_field_name")
                    continue
                allowed_types = _DIMENSIONS if group == "dimensions" else _MEASURES
                if not isinstance(field_type, str) or field_type not in allowed_types:
                    issue(field_path, "unsupported_field_type")
                    continue
                sql = field.get("sql")
                if group == "measures" and field_type == "count" and sql in (None, ""):
                    retained_sql = None
                else:
                    match = _COLUMN.fullmatch(sql) if isinstance(sql, str) else None
                    if not match or not _safe_name(match.group(1)):
                        issue(field_path, "unsupported_field_expression")
                        continue
                    retained_sql = sql
                output_field: dict[str, str] = {"name": field_name, "type": field_type}
                if retained_sql is not None:
                    output_field["sql"] = retained_sql
                valid_fields[field_id] = (source_id, group, field_name)
                field_identity_owner[field_id] = source_id
                if unsupported_field_properties:
                    unsupported_field_ids.add(field_id)
                    continue
                view[group].append(output_field)

        all_names = [
            item["name"].casefold()
            for group in ("dimensions", "measures")
            for item in view[group]
        ]
        repeated_names = {name for name, count in Counter(all_names).items() if count > 1}
        if repeated_names:
            # The canonical generator rejects same-named measures/dimensions;
            # leave them out rather than choosing an arbitrary interpretation.
            for group in ("dimensions", "measures"):
                view[group] = [
                    item for item in view[group] if item["name"].casefold() not in repeated_names
                ]
            for field_id, (owner, group, field_name) in list(valid_fields.items()):
                if owner == source_id and field_name.casefold() in repeated_names:
                    del valid_fields[field_id]
                    del field_identity_owner[field_id]
                    issue(path, "duplicate_field_name")

        properties["views"].append(view)

    # Resolve each dashboard element by exact stable identities, never by title
    # or array position. Invalid references make the visual unsupported.
    processed_elements = 0
    for index, dashboard in enumerate(payload["dashboards"]):
        path = f"dashboards[{index}]"
        if not isinstance(dashboard, dict):
            continue
        source_id = dashboard.get("source_id")
        if (not isinstance(source_id, str) or source_id not in unique_identity
                or unique_identity[source_id][0] != "dashboard"):
            continue
        unsupported_dashboard_properties = bool(
            set(dashboard) - {"source_id", "title", "elements"}
        )
        if unsupported_dashboard_properties:
            issue(path, "unsupported_input_property")
        title = dashboard.get("title")
        if not _safe_title(title):
            issue(path, "invalid_dashboard_title")
            continue
        output_dashboard: dict[str, Any] = {"name": title, "elements": []}
        elements = dashboard.get("elements")
        if not isinstance(elements, list):
            issue(path, "elements_missing_or_invalid")
            properties["dashboards"].append(output_dashboard)
            continue
        if len(elements) > _MAX_RECORDS:
            issue(path, "element_limit_exceeded")
            properties["dashboards"].append(output_dashboard)
            continue
        for element_index, element in enumerate(elements):
            if processed_elements >= _MAX_TOTAL_ELEMENTS:
                issue(path, "total_element_limit_exceeded")
                break
            processed_elements += 1
            epath = f"{path}.elements[{element_index}]"
            if not isinstance(element, dict):
                continue
            element_id = element.get("source_id")
            if (not isinstance(element_id, str) or element_id not in unique_identity
                    or unique_identity[element_id][0] != "element"):
                continue
            unsupported_element_properties = bool(
                set(element)
                - {"source_id", "title", "explore_source_id", "field_source_ids", "type"}
            )
            if unsupported_element_properties:
                issue(epath, "unsupported_input_property")
            element_title = element.get("title")
            if not _safe_title(element_title):
                issue(epath, "invalid_element_title")
                continue
            visual: dict[str, Any] = {
                "name": element_title, "type": "unsupported", "view": "",
                "dimensions": [], "measures": [],
            }
            output_dashboard["elements"].append(visual)

            explore_id = element.get("explore_source_id")
            explore = valid_explores.get(explore_id) if isinstance(explore_id, str) else None
            if explore is None:
                issue(epath, "unresolved_or_ambiguous_explore_reference")
                visual["unsupported"] = True
                continue
            field_ids = element.get("field_source_ids")
            if not isinstance(field_ids, list) or len(field_ids) > _MAX_REFERENCES_PER_ELEMENT:
                issue(epath, "field_references_missing_or_invalid")
                visual["unsupported"] = True
                continue
            resolved: list[tuple[str, str]] = []
            unresolved = False
            for field_id in field_ids:
                field = valid_fields.get(field_id) if isinstance(field_id, str) else None
                if field is None or field_identity_owner.get(field_id) != explore_id:
                    unresolved = True
                    break
                resolved.append((field[1], field[2]))
            if unresolved or not field_ids:
                issue(epath, "unresolved_or_ambiguous_field_reference")
                visual["unsupported"] = True
                continue
            dependency_edges.append({
                "element_source_id": element_id,
                "explore_source_id": explore_id,
                "field_source_ids": sorted(field_ids),
            })
            refs = [(group, name) for group, name in resolved]
            if len(set(refs)) != len(refs):
                issue(epath, "duplicate_field_reference")
                visual["unsupported"] = True
                continue

            if (
                unsupported_element_properties
                or unsupported_dashboard_properties
                or explore["unsupported_properties"]
                or any(field_id in unsupported_field_ids for field_id in field_ids)
            ):
                visual["unsupported"] = True
                continue

            visual_type = element.get("type")
            dimensions = [name for group, name in refs if group == "dimensions"]
            measures = [name for group, name in refs if group == "measures"]
            valid_visual = (
                isinstance(visual_type, str)
                and visual_type in _VISUALS
                and (visual_type not in {"bar", "column", "line"}
                     or len(dimensions) == 1 and len(measures) == 1)
                and (visual_type != "card" or not dimensions and len(measures) == 1)
            )
            if not valid_visual:
                issue(epath, "unsupported_visual_or_field_shape")
                visual["unsupported"] = True
                continue
            visual.update({
                "type": visual_type,
                "view": explore["name"],
                "dimensions": dimensions,
                "measures": measures,
            })
        properties["dashboards"].append(output_dashboard)

    properties["security"] = [{"path": "project", "code": "security_evidence_unresolved"}]
    properties["explores"] = [
        {"path": "project", "code": "lookml_semantics_and_parity_unverified"}
    ]
    report = json.dumps(
        sorted(issues, key=lambda item: (item["path"], item["code"])),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    source_identifiers = json.dumps(
        sorted(identifiers, key=lambda item: (item["source_id"], item["kind"], item["path"])),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return BigQueryObject(
        source_id=f"{project_id}.looker_lookml_export",
        name="looker_lookml_export",
        kind=ObjectKind.LOOKER_ASSET,
        discovered_from="external_payload",
        labels={
            "looker_lookml_ingestion_report": report,
            "looker_source_identifiers": source_identifiers,
            "looker_lookml_provenance": json.dumps(
                {"project_id": project_id, "schema_version": payload["schema_version"]},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ),
            "looker_lookml_dependency_edges": json.dumps(
                sorted(
                    dependency_edges,
                    key=lambda edge: (
                        edge["element_source_id"],
                        edge["explore_source_id"],
                        edge["field_source_ids"],
                    ),
                ),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ),
        },
        properties=properties,
    )
