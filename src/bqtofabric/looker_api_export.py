"""Offline normalization of saved Looker API 4.0 responses.

``normalize_looker_api_export(project_id, payload)`` returns one LOOKER_ASSET.
The payload is an object containing ``explores`` and ``dashboards`` lists of
individual responses from lookml_model_explore and dashboard, respectively::

    {"explores": [{"model_name": "commerce", "name": "orders",
                   "view_name": "orders", "sql_table_name": "p.d.orders",
                   "joins": [], "always_join": [], "access_filters": [],
                   "access_filter_fields": [], "always_filter": [],
                   "conditionally_filter": [], "sql_always_where": "",
                   "access_grants": [], "required_access_grants": [], "fields": {
                       "dimensions": [{"name": "orders.region", "view": "orders",
                           "type": "string", "sql": "${TABLE}.region",
                           "sql_case": null, "dimension_group": null}],
                       "measures": [], "filters": [], "parameters": []}}],
     "dashboards": []}

This is computed Explore metadata, not raw LookML. SQL is accepted only as a
direct column expression; no arbitrary source text, filter values, URLs,
connection metadata or credentials are retained. The JSON string in
``asset.labels["looker_ingestion_report"]`` contains deterministic diagnostics
using only fixed paths, indexes and codes. ``looker_source_identifiers``
contains only validated identifiers, indexed by source response path.
Unsupported context is represented by value-free markers in properties so
the generator refuses unsafe visuals.
Omitted API fields are not evidence of absence. Even complete responses do
not prove source security or parity; the generator remains review-only.
The three security evidence fields in the example are conservative envelope
extensions, not necessarily returned by Looker's Explore API. Supply explicit
empty values only when supported by independent evidence; a missing, null or
invalid value leaves security unresolved and blocks visual conversion.
Known non-semantic Explore response metadata is ignored; any other nonempty
Explore property is marked unresolved without retaining its name or value.
Tiles linked to a Look are marked unsupported, even if a query is embedded.
Dashboard and tile titles permit 1–64 ASCII letters, digits, underscores,
spaces or hyphens, with no surrounding whitespace, sensitive keywords or
known credential patterns. Pattern detection cannot recognize every secret.
Semantic identifiers remain more restrictive.

References: Looker SDK API 4.0 models and methods:
https://github.com/looker-open-source/sdk-codegen/blob/main/python/looker_sdk/sdk/api40/models.py
https://github.com/looker-open-source/sdk-codegen/blob/main/python/looker_sdk/sdk/api40/methods.py
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any, TypeGuard

from .models import BigQueryObject, ObjectKind

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
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
_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,127}$")
_COLUMN = re.compile(r"^\$\{TABLE\}\.([A-Za-z_][A-Za-z0-9_]*)$")
_TABLE = re.compile(r"^`?([A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*){0,2})`?$")
_DIMENSIONS = {"string", "number", "yesno", "date"}
_MEASURES = {"sum", "average", "min", "max", "count_distinct"}
_VISUAL_TYPES = {
    "looker_grid": "table",
    "looker_bar": "bar",
    "looker_line": "line",
    "looker_column": "column",
    "single_value": "card",
}
# Only identity, explicitly handled semantics, and documented descriptive or
# capability metadata are recognized. Values are not copied as free text.
# Unknown properties, including newly introduced API semantics, fail closed.
_EXPLORE_KEYS = frozenset({
    "id", "name", "model_name", "view_name", "sql_table_name", "fields",
    "joins", "always_join", "access_filters", "access_filter_fields",
    "always_filter", "conditionally_filter", "sql_always_where", "access_grants",
    "required_access_grants", "sql_always_having", "errors",
    "description", "label", "title", "group_label", "lookml_link", "files",
    "source_file", "project_name", "connection_name", "dialect_name", "tags",
    "hidden", "can_total", "can_develop", "can_see_lookml", "can_save",
    "can_explain", "can_pivot_in_db", "can_subtotal", "has_timezone_support",
    "supports_cost_estimate", "index_fields", "supported_measure_types",
})


def _safe(value: Any) -> TypeGuard[str]:
    return (isinstance(value, str) and bool(_NAME.fullmatch(value))
            and not _SENSITIVE.search(value) and not _CREDENTIAL.search(value)
            and not _RESERVED.fullmatch(value))


def _safe_display(value: Any) -> TypeGuard[str]:
    return (isinstance(value, str) and bool(_DISPLAY.fullmatch(value))
            and value == value.strip() and not _SENSITIVE.search(value)
            and not _SENSITIVE.search(re.sub(r"[ _-]", "", value))
            and not _CREDENTIAL.search(value))


def _empty(value: Any) -> bool:
    return value is None or value is False or value == "" or value == [] or value == {}


def normalize_looker_api_export(project_id: str, payload: Any) -> BigQueryObject:
    """Normalize parsed JSON; raise ValueError/TypeError for invalid envelope.

    Only the explicit envelope above is accepted. Individual malformed objects
    are diagnosed and omitted. No network or filesystem operations are made.
    """
    if (not isinstance(project_id, str) or not _ID.fullmatch(project_id)
            or _SENSITIVE.search(project_id) or _CREDENTIAL.search(project_id)):
        raise ValueError("project_id must be a safe non-sensitive identifier")
    if not isinstance(payload, dict) or set(payload) != {"explores", "dashboards"}:
        raise ValueError("payload must contain exactly explores and dashboards")
    if not all(isinstance(payload[k], list) for k in ("explores", "dashboards")):
        raise TypeError("explores and dashboards must be lists")

    issues: list[dict[str, str]] = []
    identifiers: list[dict[str, str]] = []

    def issue(path: str, code: str) -> None:
        issues.append({"path": path, "code": code})

    def retain(path: str, obj: dict[str, Any], keys: tuple[str, ...]) -> None:
        record = {"path": path}
        for key in keys:
            value = obj.get(key)
            if (key == "title" and _safe_display(value) or
                    key != "title" and isinstance(value, str) and len(value) <= 128 and
                    not _CREDENTIAL.search(value) and
                    all(_ID.fullmatch(part) and not _SENSITIVE.search(part)
                        for part in value.split("."))):
                record[key] = value
        if len(record) > 1:
            identifiers.append(record)

    properties: dict[str, Any] = {"views": [], "dashboards": []}
    context: dict[str, list[dict[str, Any]]] = {}

    def mark(key: str, path: str, code: str) -> None:
        issue(path, code)
        context.setdefault(key, []).append({"path": path, "code": code})

    explores = payload["explores"]
    if not explores:
        issue("explores", "no_explore_responses")
    if not payload["dashboards"]:
        issue("dashboards", "no_dashboard_responses")
    names = Counter(
        e["view_name"].casefold() for e in explores
        if isinstance(e, dict) and _safe(e.get("view_name"))
    )
    # Query model/explore identifies an Explore, not necessarily its base view.
    lookup: dict[tuple[str, str], tuple[str, dict[str, str]]] = {}
    explore_ids = Counter(
        (e["model_name"], e["name"]) for e in explores
        if isinstance(e, dict) and _safe(e.get("model_name")) and _safe(e.get("name"))
    )
    for i, explore in enumerate(explores):
        path = f"explores[{i}]"
        if not isinstance(explore, dict):
            mark("explores", path, "expected_object")
            continue
        retain(path, explore, ("model_name", "name", "view_name"))
        model, name, view = (explore.get(k) for k in ("model_name", "name", "view_name"))
        if (not _safe(model) or not _safe(name) or not _safe(view)
                or names[view.casefold()] != 1 or explore_ids[(model, name)] != 1):
            mark("explores", path, "invalid_or_ambiguous_identity")
            continue

        if any(key not in _EXPLORE_KEYS and not _empty(value)
               for key, value in explore.items()):
            mark("explores", path, "unknown_explore_property")

        # Preserve evidence by category without retaining filter/SQL values.
        for key, category in (
            ("joins", "joins"), ("always_join", "joins"),
            ("access_filters", "security"), ("access_filter_fields", "security"),
            ("always_filter", "explores"), ("conditionally_filter", "explores"),
        ):
            value = explore.get(key)
            if key not in explore or not isinstance(value, list):
                mark(category, path, f"{key}_missing_or_invalid")
            elif value:
                mark(category, path, f"{key}_not_migrated")
        for key, expected_type in (("sql_always_where", str), ("access_grants", list),
                                   ("required_access_grants", list)):
            if key not in explore or not isinstance(explore[key], expected_type):
                mark("security", path, f"{key}_missing_or_invalid")
            elif explore[key]:
                mark("security", path, f"{key}_not_migrated")
        for key, category in (("sql_always_having", "explores"), ("errors", "explores")):
            if not _empty(explore.get(key)):
                mark(category, path, f"{key}_not_migrated")

        fields = explore.get("fields")
        if not isinstance(fields, dict):
            mark("explores", path, "fields_missing_or_invalid")
            continue
        for key in ("filters", "parameters"):
            if key not in fields or not isinstance(fields[key], list):
                mark("explores", path + ".fields", f"{key}_missing_or_invalid")
            elif fields[key]:
                mark("explores", path + ".fields", f"{key}_not_migrated")
        table: dict[str, Any] = {"name": view, "dimensions": [], "measures": []}
        table_name = explore.get("sql_table_name")
        match = _TABLE.fullmatch(table_name) if isinstance(table_name, str) else None
        if (isinstance(table_name, str) and match
                and table_name.startswith("`") == table_name.endswith("`")
                and not _SENSITIVE.search(match.group(1))
                and not _CREDENTIAL.search(match.group(1))):
            table["sql_table_name"] = table_name
        else:
            issue(path, "source_table_missing_or_unsupported")
        mapping: dict[str, str] = {}
        for group in ("dimensions", "measures"):
            source_fields = fields.get(group)
            if not isinstance(source_fields, list):
                mark("explores", path + ".fields", f"{group}_missing_or_invalid")
                continue
            for j, field in enumerate(source_fields):
                fpath = f"{path}.fields.{group}[{j}]"
                if not isinstance(field, dict):
                    issue(fpath, "expected_object")
                    continue
                retain(fpath, field, ("name", "view", "original_view"))
                full_name = field.get("name")
                if (not isinstance(full_name, str) or not full_name.startswith(view + ".")
                        or field.get("view") != view or not _safe(full_name[len(view) + 1:])):
                    mark("joins", fpath, "joined_or_invalid_field")
                    continue
                if any(not _empty(field.get(key)) for key in
                       ("required_access_grants", "access_grants")):
                    mark("security", fpath, "field_security_not_migrated")
                    continue
                short = full_name[len(view) + 1:]
                typ, sql = field.get("type"), field.get("sql")
                match = _COLUMN.fullmatch(sql) if isinstance(sql, str) else None
                if (not isinstance(typ, str) or typ not in
                        (_DIMENSIONS if group == "dimensions" else _MEASURES)
                        or not match or not _safe(match.group(1))):
                    issue(fpath, "unsupported_type_or_sql")
                    continue
                if ("sql_case" not in field or "dimension_group" not in field
                        or (group == "measures" and "filters" not in field)):
                    issue(fpath, "field_semantics_missing")
                    continue
                semantic_keys = ("sql_case", "dimension_group", "filters", "dynamic",
                                 "is_timeframe", "convert_tz", "error", "parameter",
                                 "is_filter", "period_over_period_params",
                                 "default_filter_value", "sql_where",
                                 "required_access_grants", "access_grants")
                if (any(not _empty(field.get(key)) for key in semantic_keys)
                        or field.get("original_view") not in (None, "", view)):
                    issue(fpath, "field_semantics_not_migrated")
                    continue
                table[group].append({"name": short, "type": typ, "sql": sql})
                mapping[full_name] = group
                issue(fpath, "additional_field_metadata_not_migrated")
        properties["views"].append(table)
        lookup[(model, name)] = (view, mapping)
        issue(path, "explore_and_security_not_fully_represented")

    for i, dashboard in enumerate(payload["dashboards"]):
        path = f"dashboards[{i}]"
        if not isinstance(dashboard, dict) or not _safe_display(dashboard.get("title")):
            issue(path, "invalid_dashboard")
            continue
        retain(path, dashboard, ("id", "title"))
        result: dict[str, Any] = {"name": dashboard["title"], "elements": []}
        if ("dashboard_filters" not in dashboard or
                not isinstance(dashboard["dashboard_filters"], list) or dashboard["dashboard_filters"]):
            result["filters"] = True
            issue(path, "dashboard_filters_missing_or_not_migrated")
        source_elements = dashboard.get("dashboard_elements")
        if not isinstance(source_elements, list):
            issue(path, "dashboard_elements_missing_or_invalid")
            properties["dashboards"].append(result)
            continue
        for j, element in enumerate(source_elements):
            epath = f"{path}.elements[{j}]"
            # A linked Look is not an inline query, even when both are present.
            # Do not inspect or retain its nested values or invent its title.
            if isinstance(element, dict) and (
                element.get("look") is not None
                or element.get("look_id") not in (None, "")
            ):
                issue(epath, "linked_look_not_migrated")
                continue
            if not isinstance(element, dict) or not _safe_display(element.get("title")):
                issue(epath, "invalid_element")
                continue
            retain(epath, element, ("id", "title", "query_id"))
            visual: dict[str, Any] = {"name": element["title"], "type": "unsupported",
                                      "view": "", "dimensions": [], "measures": []}
            result["elements"].append(visual)
            if any(not _empty(element.get(k)) for k in ("merge_result_id", "result_maker")):
                visual["unsupported"] = True
                issue(epath, "element_context_not_migrated")
            query = element.get("query")
            if not isinstance(query, dict):
                visual["unsupported"] = True
                issue(epath, "query_missing_or_invalid")
                continue
            model, explore = query.get("model"), query.get("view")
            retain(epath + ".query", query, ("id", "model", "view"))
            binding = lookup.get((model, explore)) if _safe(model) and _safe(explore) else None
            selected = query.get("fields")
            if (not binding or not isinstance(selected, list) or not selected
                    or not all(isinstance(v, str) and v in binding[1] for v in selected)):
                visual["unsupported"] = True
                issue(epath, "unresolved_query_fields")
                continue
            visual["view"] = binding[0]
            for full_name in selected:
                visual[binding[1][full_name]].append(full_name.split(".", 1)[1])
            # Filters, pivots, table calculations and query shaping cannot be
            # silently dropped. Missing filter keys are not treated as empty.
            filter_types = {"filters": dict, "filter_expression": str, "filter_config": dict}
            if any(k not in query or (query[k] is not None and not isinstance(query[k], typ))
                   for k, typ in filter_types.items()):
                visual["filters"] = True
                issue(epath, "query_filter_evidence_missing_or_invalid")
            shaping_types = {
                "pivots": list, "fill_fields": list, "dynamic_fields": str,
                "has_table_calculations": bool, "sorts": list, "total": bool,
                "row_total": str, "subtotals": list, "query_timezone": str,
                "column_limit": str, "limit": str,
            }
            if any(k not in query or (query[k] is not None and not isinstance(query[k], typ))
                   for k, typ in shaping_types.items()):
                visual["unsupported"] = True
                issue(epath, "query_semantics_evidence_missing_or_invalid")
            known_query_keys = set(filter_types) | set(shaping_types) | {
                "model", "view", "id", "can", "fields", "vis_config",
                "visible_ui_sections", "slug", "client_id", "share_url",
                "expanded_share_url", "url",
            }
            if any(key not in known_query_keys for key in query):
                visual["unsupported"] = True
                issue(epath, "unknown_query_property")
            for key in ("filters", "filter_expression", "filter_config", "pivots",
                        "fill_fields", "dynamic_fields", "sorts", "total", "row_total",
                        "subtotals", "has_table_calculations", "query_timezone", "column_limit"):
                if not _empty(query.get(key)):
                    visual["filters" if key.startswith("filter") else "unsupported"] = True
                    issue(epath, "query_semantics_not_migrated")
            if query.get("limit") != "-1":
                visual["unsupported"] = True
                issue(epath, "query_limit_not_migrated")
            config = query.get("vis_config")
            config_type = config.get("type") if isinstance(config, dict) else None
            if isinstance(config, dict) and isinstance(config_type, str) and config_type in _VISUAL_TYPES:
                visual["type"] = _VISUAL_TYPES[config_type]
                if set(config) != {"type"}:
                    visual["unsupported"] = True
                    issue(epath, "visual_configuration_not_migrated")
            else:
                issue(epath, "visual_type_missing_or_unsupported")
            issue(epath, "element_layout_and_metadata_not_migrated")
        properties["dashboards"].append(result)
        issue(path, "dashboard_layout_and_metadata_not_migrated")

    properties.update(context)
    report = json.dumps(issues, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return BigQueryObject(
        source_id=f"{project_id}.looker.api_export", name="looker_api_export",
        kind=ObjectKind.LOOKER_ASSET, discovered_from="external_payload",
        labels={"looker_ingestion_report": report,
                "looker_source_identifiers": json.dumps(
                    identifiers, sort_keys=True, separators=(",", ":"), ensure_ascii=True)},
        properties=properties,
    )
