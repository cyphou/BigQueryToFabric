"""Bounded offline Looker -> review-only PBIP conversion.

``generate_looker_powerbi_project(asset, *, project_name="LookerMigration")``
returns a :class:`LookerPowerBIProject` with ``files`` (relative POSIX paths to
UTF-8 text) and ``review`` (JSON-serializable diagnostics). It never writes to
the caller's directory. The caller decides how to persist those files safely.

Requires the sibling ``tableau-to-powerbi`` project's ``powerbi_import`` and
``tableau_export`` packages on Python's import path. This adapter uses its
PBIP manifest generator, TMDL writers and PBIR projection finalizer. Those are
internal interfaces; tested against the sibling 44.0.0 source tree. No code
from that project is vendored. Import or API failures are explicit.

Input is a canonical LOOKER_ASSET with properties:

* views: [{name, sql_table_name?, dimensions: [{name, type, sql}],
  measures: [{name, type, sql?}]}]
* optional top-level dimensions/measures: same fields plus ``view``.
* dashboards: [{name, elements: [{name, type, view,
  dimensions: [name], measures: [name]}]}]

For example, after putting the sibling checkout on ``PYTHONPATH``::

    from bqtofabric.models import BigQueryObject, ObjectKind
    from bqtofabric.generator.looker_powerbi import generate_looker_powerbi_project
    asset = BigQueryObject("source", "model", ObjectKind.LOOKER_ASSET, properties={
        "views": [{"name": "orders", "sql_table_name": "project.dataset.orders",
                   "dimensions": [{"name": "amount", "type": "number",
                                   "sql": "${TABLE}.amount"}],
                   "measures": [{"name": "sales", "type": "sum",
                                 "sql": "${TABLE}.amount"}]}],
        "dashboards": [{"name": "Revenue", "elements": [
            {"name": "Totals", "type": "table", "view": "orders",
             "dimensions": [], "measures": ["sales"]}]}]})
    result = generate_looker_powerbi_project(asset)
    print(sorted(result.files), result.review)

Only direct ``${TABLE}.column`` dimensions and simple unfiltered aggregates
over an explicitly declared dimension are emitted. Supported dimensions are
string, number, yesno, and date; measures are count, sum, average, min, max,
and count_distinct. Dashboard elements are tables, bars, columns, lines or
single-measure cards, from exactly one view. Cartesian charts require exactly
one dimension and one measure; cards require only one measure.
All other constructs are diagnosed, never pasted as SQL/DAX or evaluated.
Identifiers are restricted. Unknown object keys cause that object to be
omitted; top-level unknown properties are reported without copying their values.
Dashboard and element display titles allow 1-64 ASCII letters, digits,
underscores, spaces or hyphens, with no leading/trailing whitespace or
sensitive keywords (including variants separated by spaces, underscores or
hyphens) or known credential shapes. The same credential-shape restriction
applies to semantic identifiers and project names. Titles are not paths and
must be case-insensitively unique within
their dashboard list or their owning dashboard's elements, respectively.

All partitions deliberately fail on refresh; no credentials, source names, raw
SQL, security predicates or other free text are copied. Power BI security,
runtime, precision, joins and parity are not verified. A page/visual grid is a
review scaffold, not the original dashboard layout. Empty or list-only Looker
exports produce diagnostics, not invented models or dashboards.
"""

from __future__ import annotations

import importlib
import json
import re
import tempfile
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import BigQueryObject, ObjectKind

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_DISPLAY_TITLE = re.compile(r"^[A-Za-z0-9_ -]{1,64}$")
_SENSITIVE = re.compile(
    r"password|passwd|secret|token|credential|authorization|apikey|api_key|"
    r"privatekey|private_key|accesskey|access_key|connectionstring|connection_string",
    re.IGNORECASE,
)
# Guard known credential formats even when their labels do not contain words
# such as "token". Search, rather than fullmatch, so embedded values also fail.
_CREDENTIAL_SHAPE = re.compile(
    r"gh[opsur]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"(?:AKIA|ASIA)[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{35}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|sk_(?:live|test)_[A-Za-z0-9]{16,}",
    re.IGNORECASE,
)
_WINDOWS_RESERVED = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", re.IGNORECASE)
_COLUMN = re.compile(r"^\$\{TABLE\}\.([A-Za-z_][A-Za-z0-9_]*)$")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b")
_DIM_TYPES = {"string": "string", "number": "double", "yesno": "boolean", "date": "dateTime"}
_AGG = {
    "sum": "SUM", "average": "AVERAGE", "min": "MIN", "max": "MAX",
    "count_distinct": "DISTINCTCOUNTNOBLANK",
}
_AXIS_VISUALS = {
    "bar": "clusteredBarChart",
    "column": "clusteredColumnChart",
    "line": "lineChart",
}
_SECURITY = {
    "access_filters", "access_grants", "sql_always_where", "always_filter",
    "row_level_security", "security", "permissions", "user_attributes",
}
_NS = uuid.UUID("88e97c6d-7301-4cc4-8615-7dbb77e9ec54")


@dataclass(frozen=True, slots=True)
class LookerPowerBIProject:
    """Review-only files and diagnostics. Contents are not deployment evidence."""

    files: dict[str, str]
    review: dict[str, Any]


def _safe(value: Any) -> bool:
    return (isinstance(value, str) and bool(_NAME.fullmatch(value))
            and not _SENSITIVE.search(value) and not _CREDENTIAL_SHAPE.search(value)
            and not _WINDOWS_RESERVED.fullmatch(value))


def _safe_display_title(value: Any) -> bool:
    """Validate display-only names; they are never used for filenames or identifiers."""
    return (
        isinstance(value, str)
        and bool(_DISPLAY_TITLE.fullmatch(value))
        and value == value.strip()
        and not _SENSITIVE.search(value)
        and not _SENSITIVE.search(re.sub(r"[ _-]", "", value))
        and not _CREDENTIAL_SHAPE.search(value)
    )


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _issue(issues: list[dict[str, str]], path: str, code: str) -> None:
    # Paths contain only fixed labels and numeric indexes, never source text.
    issues.append({"path": path, "code": code})


def _list(value: Any, path: str, issues: list[dict[str, str]]) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        _issue(issues, path, "expected_list")
        return []
    return list(value)


def _unknown(obj: dict[str, Any], allowed: set[str]) -> bool:
    return any(key not in allowed for key in obj)


def _duplicates(items: list[Any], valid: Callable[[Any], bool] = _safe) -> set[str]:
    names = [item["name"].casefold() for item in items
             if isinstance(item, dict) and valid(item.get("name"))]
    return {name for name, count in Counter(names).items() if count > 1}


def _load_backend() -> tuple[Any, Any, Any]:
    try:
        pbip = importlib.import_module("powerbi_import.pbip_generator")
        tmdl = importlib.import_module("powerbi_import.tmdl_writers")
        visual = importlib.import_module("powerbi_import.visual_generator")
        for module, names in (
            (pbip, ("PowerBIProjectGenerator", "_L", "SCHEMA_PAGE", "SCHEMA_VISUAL")),
            (tmdl, ("_write_database_tmdl", "_write_model_tmdl", "_write_table_tmdl")),
            (visual, ("finalize_native_query_refs",)),
        ):
            for name in names:
                getattr(module, name)
        return pbip, tmdl, visual
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(
            "Looker PBIP generation requires compatible TableauToPowerBI 44.0.0 "
            "powerbi_import and tableau_export packages on PYTHONPATH."
        ) from exc


def generate_looker_powerbi_project(
    asset: BigQueryObject, *, project_name: str = "LookerMigration"
) -> LookerPowerBIProject:
    """Convert one canonical Looker asset to in-memory PBIP files for review."""
    if not isinstance(asset, BigQueryObject) or asset.kind is not ObjectKind.LOOKER_ASSET:
        raise ValueError("asset must be a canonical LOOKER_ASSET")
    if not _safe(project_name):
        raise ValueError("project_name must be a safe non-sensitive identifier")
    pbip, tmdl, visual_backend = _load_backend()
    props = asset.properties
    issues: list[dict[str, str]] = []
    review: dict[str, Any] = {
        "status": "review_required",
        "runtime": "not_run",
        "parity": "not_run",
        "security": "not_migrated_unverified",
        "source_binding": "disabled",
        "issues": issues,
        "converted": [],
    }
    if not isinstance(props, dict):
        _issue(issues, "properties", "expected_object")
        return LookerPowerBIProject({}, review)
    unknown_context = False
    for key in sorted(props, key=str):
        if key not in {"views", "dimensions", "measures", "dashboards"}:
            unknown_context |= bool(props[key])
            code = ("security_not_migrated" if key in _SECURITY else
                    "joins_not_migrated" if key == "joins" else
                    "explores_not_migrated" if key == "explores" else
                    "unsupported_property")
            _issue(issues, "properties", code)

    views = _list(props.get("views"), "views", issues)
    top_dims = _list(props.get("dimensions"), "dimensions", issues)
    top_measures = _list(props.get("measures"), "measures", issues)
    duplicate_views = _duplicates(views)
    valid_view_names = {
        view["name"] for view in views if isinstance(view, dict) and _safe(view.get("name"))
    }
    for label, fields in (("dimensions", top_dims), ("measures", top_measures)):
        for idx, field in enumerate(fields):
            if (not isinstance(field, dict) or not isinstance(field.get("view"), str)
                    or field["view"] not in valid_view_names):
                _issue(issues, f"{label}[{idx}]", "unknown_view")

    tables: list[dict[str, Any]] = []
    bindings: dict[str, dict[str, set[str]]] = {}
    for vi, view in enumerate(views):
        path = f"views[{vi}]"
        if not isinstance(view, dict) or not _safe(view.get("name")):
            _issue(issues, path, "unsafe_or_missing_name")
            continue
        name = view["name"]
        if name.casefold() in duplicate_views:
            _issue(issues, path, "duplicate_view")
            continue
        if _unknown(view, {"name", "sql_table_name", "dimensions", "measures"}):
            _issue(issues, path, "derived_table_not_migrated" if "derived_table" in view
                   else "unsupported_view_property")
            continue
        if not isinstance(view.get("sql_table_name"), str) or not view["sql_table_name"]:
            _issue(issues, path, "source_table_missing")
        else:
            _issue(issues, path, "source_binding_omitted")
        dims = _list(view.get("dimensions"), f"{path}.dimensions", issues)
        measures = _list(view.get("measures"), f"{path}.measures", issues)
        dims += [x for x in top_dims if isinstance(x, dict) and x.get("view") == name]
        measures += [x for x in top_measures if isinstance(x, dict) and x.get("view") == name]
        duplicates = _duplicates(dims + measures)
        columns: list[dict[str, Any]] = []
        converted_fields: list[dict[str, str]] = []
        source_to_names: dict[str, list[str]] = {}
        dimension_types: dict[str, str] = {}
        for di, dim in enumerate(dims):
            dpath = f"{path}.dimensions[{di}]"
            if not isinstance(dim, dict) or not _safe(dim.get("name")):
                _issue(issues, dpath, "unsafe_or_missing_name")
                continue
            if dim["name"].casefold() in duplicates:
                _issue(issues, dpath, "duplicate_field")
                continue
            if (_unknown(dim, {"name", "type", "sql", "view"})
                    or "view" in dim and dim["view"] != name):
                _issue(issues, dpath, "unsupported_dimension_property")
                continue
            kind = dim.get("type")
            match = _COLUMN.fullmatch(dim.get("sql", "")) if isinstance(dim.get("sql"), str) else None
            if not isinstance(kind, str) or kind not in _DIM_TYPES or not match or not _safe(match.group(1)):
                _issue(issues, dpath, "unsupported_dimension")
                continue
            column = match.group(1)
            columns.append({"name": dim["name"], "dataType": _DIM_TYPES[kind],
                            "sourceColumn": column, "summarizeBy": "none"})
            source_to_names.setdefault(column.casefold(), []).append(dim["name"])
            dimension_types[dim["name"]] = kind
            converted_fields.append({"path": dpath, "kind": "dimension"})
        dax_measures: list[dict[str, str]] = []
        for mi, measure in enumerate(measures):
            mpath = f"{path}.measures[{mi}]"
            if not isinstance(measure, dict) or not _safe(measure.get("name")):
                _issue(issues, mpath, "unsafe_or_missing_name")
                continue
            if measure["name"].casefold() in duplicates:
                _issue(issues, mpath, "duplicate_field")
                continue
            if (_unknown(measure, {"name", "type", "sql", "view"})
                    or "view" in measure and measure["view"] != name):
                _issue(issues, mpath, "filtered_measure_not_migrated" if "filters" in measure
                       else "unsupported_measure_property")
                continue
            kind = measure.get("type")
            sql = measure.get("sql", "")
            if kind == "count" and sql in ("", None):
                expression = f"COALESCE(COUNTROWS('{name}'), 0)"
            else:
                match = _COLUMN.fullmatch(sql) if isinstance(sql, str) else None
                matches = source_to_names.get(match.group(1).casefold(), []) if match else []
                if not isinstance(kind, str) or kind not in _AGG or len(matches) != 1:
                    _issue(issues, mpath, "unsupported_measure")
                    continue
                field_type = dimension_types[matches[0]]
                if ((kind in {"sum", "average"} and field_type != "number")
                        or (kind in {"min", "max"} and field_type not in {"number", "date"})):
                    _issue(issues, mpath, "unsupported_measure_data_type")
                    continue
                expression = f"{_AGG[kind]}('{name}'[{matches[0]}])"
                if kind == "count_distinct":
                    expression = f"COALESCE({expression}, 0)"
            dax_measures.append({"name": measure["name"], "expression": expression})
            converted_fields.append({"path": mpath, "kind": "measure"})
        if not columns:
            _issue(issues, path, "no_supported_dimensions")
            continue
        review["converted"].extend(converted_fields)
        tables.append({
            "name": name, "columns": columns, "measures": dax_measures,
            "partitions": [{"mode": "import", "source": {"type": "m", "expression":
                'error "Review-only: source binding and security must be configured manually"'}}],
        })
        bindings[name] = {"dimensions": {x["name"] for x in columns},
                          "measures": {x["name"] for x in dax_measures}}

    if not tables:
        _issue(issues, "views", "no_convertible_model")
        return LookerPowerBIProject({}, review)

    dashboards = _list(props.get("dashboards"), "dashboards", issues)
    pages: list[tuple[str, str, list[dict[str, Any]]]] = []
    duplicates = _duplicates(dashboards, _safe_display_title)
    for di, dashboard in enumerate(dashboards):
        dpath = f"dashboards[{di}]"
        if not isinstance(dashboard, dict) or not _safe_display_title(dashboard.get("name")):
            _issue(issues, dpath, "unsafe_or_missing_name")
            continue
        if dashboard["name"].casefold() in duplicates:
            _issue(issues, dpath, "duplicate_dashboard")
            continue
        if _unknown(dashboard, {"name", "elements"}):
            _issue(issues, dpath, "dashboard_filters_not_migrated" if "filters" in dashboard
                   else "unsupported_dashboard_property")
            continue
        page_id = "ReportSection" + uuid.uuid5(_NS, f"page:{di}").hex[:12]
        elements: list[dict[str, Any]] = []
        if "elements" not in dashboard:
            _issue(issues, dpath, "dashboard_elements_missing")
        source_elements = _list(dashboard.get("elements"), f"{dpath}.elements", issues)
        duplicate_elements = _duplicates(source_elements, _safe_display_title)
        for ei, element in enumerate(source_elements):
            epath = f"{dpath}.elements[{ei}]"
            if not isinstance(element, dict) or not _safe_display_title(element.get("name")):
                _issue(issues, epath, "unsafe_or_missing_name")
                continue
            if element["name"].casefold() in duplicate_elements:
                _issue(issues, epath, "duplicate_element")
                continue
            if _unknown(element, {"name", "type", "view", "dimensions", "measures"}):
                _issue(issues, epath, "visual_filters_not_migrated" if "filters" in element
                       else "unsupported_element_property")
                continue
            if unknown_context:
                _issue(issues, epath, "unresolved_model_context")
                continue
            view_name = element.get("view")
            dim_names, measure_names = element.get("dimensions", []), element.get("measures", [])
            if (not isinstance(view_name, str) or view_name not in bindings
                    or not isinstance(dim_names, list) or not isinstance(measure_names, list)
                    or not all(_safe(x) for x in dim_names + measure_names)
                    or any(x not in bindings[view_name]["dimensions"] for x in dim_names)
                    or any(x not in bindings[view_name]["measures"] for x in measure_names)):
                _issue(issues, epath, "unresolved_element_fields")
                continue
            if (len(set(dim_names + measure_names)) != len(dim_names + measure_names)
                    or not dim_names and not measure_names):
                _issue(issues, epath, "invalid_element_fields")
                continue
            chart_type = element.get("type")
            if (not isinstance(chart_type, str)
                    or chart_type not in {"table", "card", *_AXIS_VISUALS}
                    or (chart_type in _AXIS_VISUALS
                        and (len(dim_names) != 1 or len(measure_names) != 1))
                    or (chart_type == "card"
                        and (len(dim_names) != 0 or len(measure_names) != 1))):
                _issue(issues, epath, "unsupported_visual")
                continue
            if len(elements) >= 6:
                _issue(issues, epath, "layout_capacity_exceeded")
                continue
            elements.append({"name": element["name"], "view": view_name,
                             "type": chart_type, "dimensions": dim_names,
                             "measures": measure_names, "source_index": ei})
            review["converted"].append({"path": epath, "kind": "visual"})
        pages.append((page_id, dashboard["name"], elements))
        review["converted"].append({"path": dpath, "kind": "dashboard"})

    if not pages:
        _issue(issues, "dashboards", "review_page_scaffold")
        pages.append(("ReportSectionReview", "Review", []))
    _issue(issues, "project", "unverified_runtime_security_and_parity")
    _issue(issues, "project", "dashboard_layout_not_migrated")
    _issue(issues, "project", "numeric_date_and_aggregate_semantics_unverified")

    files = _render(pbip, tmdl, visual_backend, project_name, tables, pages)
    return LookerPowerBIProject(files, review)


def _render(pbip: Any, tmdl: Any, visual_backend: Any, name: str,
            tables: list[dict[str, Any]],
            pages: list[tuple[str, str, list[dict[str, Any]]]]) -> dict[str, str]:
    # Sibling writers write only inside our own ephemeral directory.
    with tempfile.TemporaryDirectory(prefix="looker-pbip-") as tmp:
        root = Path(tmp)
        pbip.PowerBIProjectGenerator(output_dir=tmp).create_pbip_file(tmp, name)
        definition = root / f"{name}.SemanticModel" / "definition"
        table_dir = definition / "tables"
        table_dir.mkdir(parents=True)
        tmdl._write_database_tmdl(str(definition), {})
        tmdl._write_model_tmdl(str(definition), {}, tables)
        # The sibling's generic writer assumes a file DataFolder parameter;
        # replace it with an explicitly unbound shared expression.
        model_path = definition / "model.tmdl"
        model_path.write_text(model_path.read_text(encoding="utf-8").replace(
            "ref expression DataFolder\n", "ref expression ReviewOnly\n"), encoding="utf-8")
        (definition / "expressions.tmdl").write_text(
            'expression ReviewOnly = error "Review-only: source binding is disabled"\n',
            encoding="utf-8",
        )
        for table in tables:
            tmdl._write_table_tmdl(str(table_dir), table)
        files: dict[str, str] = {}
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            text = path.read_text(encoding="utf-8")
            # Sibling serializer uses random lineage/partition UUIDs. Replace each
            # occurrence deterministically; no relationship references are emitted.
            index = 0

            def stable_uuid(match: re.Match[str], relative_path: str = relative) -> str:
                nonlocal index
                index += 1
                return str(uuid.uuid5(_NS, f"{relative_path}:{index}"))

            files[relative] = _UUID.sub(stable_uuid, text)

    sm = f"{name}.SemanticModel"
    report = f"{name}.Report"
    files[f"{sm}/definition.pbism"] = _json({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.2", "settings": {},
    })
    for folder, typ in ((sm, "SemanticModel"), (report, "Report")):
        files[f"{folder}/.platform"] = _json({
            "$schema": pbip.SCHEMA_PLATFORM,
            "metadata": {"type": typ, "displayName": name},
            "config": {"version": "2.0", "logicalId": str(uuid.uuid5(_NS, f"{name}:{typ}"))},
        })
    files[f"{report}/definition.pbir"] = _json({
        "$schema": pbip.SCHEMA_DEFINITION_PBIR, "version": "4.0",
        "datasetReference": {"byPath": {"path": f"../{sm}"}},
    })
    base = f"{report}/definition"
    files[f"{base}/version.json"] = _json({"$schema": pbip.SCHEMA_VERSION, "version": "2.0.0"})
    files[f"{base}/report.json"] = _json({
        "$schema": pbip.SCHEMA_REPORT,
        "themeCollection": {"baseTheme": {
            "name": pbip.PBI_BASE_THEME_NAME, "reportVersionAtImport": pbip.PBI_REPORT_VERSION_AT_IMPORT,
            "type": "SharedResources"}},
        "resourcePackages": [{"name": "SharedResources", "type": "SharedResources",
                              "items": [{"name": pbip.PBI_BASE_THEME_NAME,
                                         "path": f"BaseThemes/{pbip.PBI_BASE_THEME_NAME}.json",
                                         "type": "BaseTheme"}]}],
        "settings": {"exportDataMode": "None"},
    })
    files[f"{base}/pages/pages.json"] = _json({
        "$schema": pbip.SCHEMA_PAGES_METADATA, "pageOrder": [x[0] for x in pages],
        "activePageName": pages[0][0],
    })
    for page_id, display, elements in pages:
        page_base = f"{base}/pages/{page_id}"
        files[f"{page_base}/page.json"] = _json({
            "$schema": pbip.SCHEMA_PAGE, "name": page_id, "displayName": display,
            "displayOption": "FitToPage", "height": 720, "width": 1280,
        })
        for index, element in enumerate(elements):
            visual_id = uuid.uuid5(_NS, f"{page_id}:{element['source_index']}").hex[:20]
            view_name = element["view"]

            def projection(field: str, kind: str, table: str = view_name) -> dict[str, Any]:
                return {"field": {kind: {"Expression": {"SourceRef": {"Entity": table}},
                                         "Property": field}},
                        "queryRef": f"{table}.{field}", "nativeQueryRef": field}

            dims = [projection(x, "Column") for x in element["dimensions"]]
            measures = [projection(x, "Measure") for x in element["measures"]]
            if element["type"] in _AXIS_VISUALS:
                query = {"Category": {"projections": dims}, "Y": {"projections": measures}}
                visual_type = _AXIS_VISUALS[element["type"]]
            elif element["type"] == "card":
                query = {"Data": {"projections": measures}}
                visual_type = "cardVisual"
            else:
                query = {"Values": {"projections": dims + measures}}
                visual_type = "tableEx"
            # The predicate disallows apostrophes, but escape again at the literal
            # boundary so future changes cannot silently introduce PBIR injection.
            title = element["name"].replace("'", "''")
            visual_body = {
                "visualType": visual_type, "query": {"queryState": query},
                "visualContainerObjects": {"title": [{"properties": {
                    "show": pbip._L("true"), "text": pbip._L(f"'{title}'"),
                }}]},
            }
            visual_backend.finalize_native_query_refs(query, visual=visual_body)
            files[f"{page_base}/visuals/{visual_id}/visual.json"] = _json({
                "$schema": pbip.SCHEMA_VISUAL, "name": visual_id,
                "position": {"x": (index % 2) * 640, "y": (index // 2) * 240,
                             "width": 640, "height": 240, "z": index, "tabOrder": index},
                "visual": visual_body,
            })
    return dict(sorted(files.items()))
