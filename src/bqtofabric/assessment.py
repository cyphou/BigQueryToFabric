"""Compatibility assessment for a canonical BigQuery inventory."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from typing import cast

from .mapping import MappingDecision, map_component
from .models import BigQueryInventory, BigQueryObject, Column, ObjectKind
from .parity import assess_parity
from .sql_assessment import SqlAssessment, assess_sql
from .strategy import StrategyRecommendation, recommend_strategy
from .type_mapping import Compatibility, TypeMapping, map_type


@dataclass(frozen=True, slots=True)
class AssessmentFinding:
    severity: str
    source_id: str
    message: str
    code: str = ""
    category: str = ""


@dataclass(frozen=True, slots=True)
class AssessmentReport:
    project_id: str
    score: int
    component_summary: dict[str, int]
    target_summary: dict[str, int]
    compatibility_summary: dict[str, int]
    decisions: tuple[MappingDecision, ...]
    strategy: StrategyRecommendation
    type_mappings: tuple[TypeMapping, ...]
    sql_assessments: tuple[SqlAssessment, ...]
    findings: tuple[AssessmentFinding, ...]
    evidence_summary: dict[str, dict[str, object]]
    evidence_coverage: int
    parity_summary: dict[str, dict[str, object]]
    discovery_coverage: dict[str, int]


def run_assessment(inventory: BigQueryInventory) -> AssessmentReport:
    preferences = inventory.metadata.get("preferences", {})
    typed_preferences = preferences if isinstance(preferences, dict) else {}
    streaming_consumers = _streaming_consumers(inventory)
    decisions = tuple(map_component(item, typed_preferences) for item in inventory.objects())
    column_types = {
        item.source_id: tuple(
            (path, map_type(column.data_type))
            for path, column in _walk_columns_with_path(item.columns)
        )
        for item in inventory.objects()
    }
    mapped_types = tuple(
        mapping for entries in column_types.values() for _, mapping in entries
    )
    sql_assessments = tuple(
        result
        for item, decision in zip(inventory.objects(), decisions, strict=True)
        if (result := assess_sql(item, decision)) is not None
    )
    findings: list[AssessmentFinding] = []
    evidence_summary: dict[str, dict[str, object]] = {}
    parity_summary: dict[str, dict[str, object]] = {}
    readiness = {
        Compatibility.DIRECT: 100,
        Compatibility.TRANSFORM: 80,
        Compatibility.REDESIGN: 50,
        Compatibility.UNSUPPORTED: 0,
    }
    for decision in decisions:
        if decision.compatibility is Compatibility.REDESIGN:
            findings.append(AssessmentFinding(
                "WARN", decision.source_id, decision.rationale, "MAPPING_REDESIGN", "mapping"
            ))
        elif decision.compatibility is Compatibility.UNSUPPORTED:
            findings.append(AssessmentFinding(
                "FAIL", decision.source_id, decision.rationale, "MAPPING_UNSUPPORTED", "mapping"
            ))
        for action in decision.actions:
            findings.append(AssessmentFinding(
                "WARN", decision.source_id, action, "ACTION_REQUIRED", "mapping"
            ))
        if decision.source_id in streaming_consumers:
            findings.append(AssessmentFinding(
                "WARN",
                decision.source_id,
                "Upstream streaming ingestion requires deduplication, idempotency, and "
                "out-of-order delivery review.",
                "STREAMING_DOWNSTREAM_REVIEW",
                "processing",
            ))
    for item in inventory.objects():
        parity = assess_parity(item.properties, applicable=_parity_applicable(item))
        parity_summary[item.source_id] = parity
        findings.extend(_storage_layout_findings(item))
        if parity["status"] == "failed":
            findings.append(AssessmentFinding(
                "FAIL", item.source_id, "Parity evidence failed.", "PARITY_FAILED", "parity"
            ))
        elif parity["status"] == "not_run":
            findings.append(AssessmentFinding(
                "WARN",
                item.source_id,
                "No parity evidence was supplied; migration correctness is unverified.",
                "PARITY_NOT_RUN",
                "parity",
            ))
        if (
            item.kind is ObjectKind.SECURITY_POLICY
            and item.properties.get("evidence_scope") == "dataset_access_entry"
        ):
            findings.append(AssessmentFinding(
                "FAIL",
                item.source_id,
                "Dataset ACL entries are not proof of effective project, organization, group, or "
                "inherited IAM access and require security review.",
                "SECURITY_EFFECTIVE_ACCESS_REVIEW",
                "security",
            ))
        if item.properties.get("discovery_incomplete") is True:
            findings.append(AssessmentFinding(
                "FAIL",
                item.source_id,
                "Dataform compilation details could not be read; dependency lineage and "
                "transformation evidence require manual review.",
                "DATAFORM_COMPILATION_DETAILS_UNAVAILABLE",
                "adapter",
            ))
        required = _required_evidence(item.kind)
        missing = _missing_evidence(item)
        present = tuple(field_name for field_name in required if field_name not in missing)
        coverage = round(100 * len(present) / len(required)) if required else 100
        evidence_summary[item.source_id] = {
            "kind": item.kind.value,
            "discovered_from": item.discovered_from,
            "required": list(required),
            "present": list(present),
            "missing": list(missing),
            "coverage": coverage,
        }
        if item.discovered_from == "external_payload" and missing:
            findings.append(AssessmentFinding(
                "FAIL",
                item.source_id,
                f"{item.kind.value} is missing required offline evidence: {', '.join(missing)}. "
                "The live adapter is not implemented, so offline evidence must be completed.",
                "EXTERNAL_PAYLOAD_INCOMPLETE_ADAPTER",
                "adapter",
            ))
        if item.discovered_from == "assisted":
            findings.append(AssessmentFinding(
                "WARN",
                item.source_id,
                "Evidence was inferred by an assistant rather than read from a source "
                "system; confirm it against the source before relying on this decision.",
                "ASSISTED_EVIDENCE_UNVERIFIED",
                "provenance",
            ))
            if missing:
                findings.append(AssessmentFinding(
                    "FAIL",
                    item.source_id,
                    f"{item.kind.value} has inferred evidence but is still missing: "
                    f"{', '.join(missing)}. Inference did not close the gap.",
                    "ASSISTED_EVIDENCE_INCOMPLETE",
                    "provenance",
                ))
        findings.extend(
            AssessmentFinding(
                "FAIL" if item.kind is ObjectKind.SECURITY_POLICY else "WARN",
                item.source_id,
                f"Assessment evidence missing: {field_name}.",
                "SECURITY_EVIDENCE_MISSING" if item.kind is ObjectKind.SECURITY_POLICY
                else "EVIDENCE_MISSING",
                "security" if item.kind is ObjectKind.SECURITY_POLICY else "evidence",
            )
            for field_name in missing
        )
    # One finding per (object, type), listing the affected columns, so that finding
    # counts reflect distinct risks rather than schema width.
    for source_id, entries in column_types.items():
        grouped: dict[str, tuple[TypeMapping, list[str]]] = {}
        for path, mapping in entries:
            if mapping.compatibility not in {Compatibility.REDESIGN, Compatibility.UNSUPPORTED}:
                continue
            grouped.setdefault(mapping.source_type, (mapping, []))[1].append(path)
        for source_type, (mapping, paths) in sorted(grouped.items()):
            findings.append(AssessmentFinding(
                "WARN" if mapping.compatibility is Compatibility.REDESIGN else "FAIL",
                source_id,
                f"{source_type} at {', '.join(sorted(paths))}: {mapping.note}",
                "TYPE_REDESIGN" if mapping.compatibility is Compatibility.REDESIGN
                else "TYPE_UNSUPPORTED",
                "schema",
            ))
    for sql_result in sql_assessments:
        if sql_result.compatibility is Compatibility.REDESIGN:
            findings.append(AssessmentFinding(
                "WARN",
                sql_result.source_id,
                "; ".join(sql_result.notes) or "SQL requires manual redesign.",
                "SQL_REDESIGN",
                "sql",
            ))

    # Score once per component. Type and SQL risk fold into the owning component so a
    # wide table cannot outvote a genuinely blocked one.
    blocked = {finding.source_id for finding in findings if finding.severity == "FAIL"}
    sql_by_id = {result.source_id: result for result in sql_assessments}
    component_scores: dict[str, int] = {}
    for decision in decisions:
        source_id = decision.source_id
        levels = [decision.compatibility]
        levels.extend(mapping.compatibility for _, mapping in column_types.get(source_id, ()))
        if source_id in sql_by_id:
            levels.append(sql_by_id[source_id].compatibility)
        coverage = cast(int, evidence_summary[source_id]["coverage"])
        base = readiness[_worst_compatibility(levels)]
        component_scores[source_id] = (
            0 if source_id in blocked else round(base * coverage / 100)
        )
    evidence_scores = list(component_scores.values())

    strategy = recommend_strategy(inventory, decisions)
    component_summary = dict(sorted(Counter(item.kind.value for item in inventory.objects()).items()))
    target_summary = dict(sorted(Counter(item.target.value for item in decisions).items()))
    compatibility_summary = dict(
        sorted(Counter(item.compatibility.value for item in decisions).items())
    )
    discovery_coverage = dict(
        sorted(Counter(getattr(item, "discovered_from", "") for item in inventory.objects()).items())
    )
    return AssessmentReport(
        inventory.project_id,
        round(sum(evidence_scores) / len(evidence_scores)) if evidence_scores else 0,
        component_summary,
        target_summary,
        compatibility_summary,
        decisions,
        strategy,
        mapped_types,
        sql_assessments,
        tuple(findings),
        dict(sorted(evidence_summary.items())),
        round(
            sum(cast(int, item["coverage"]) for item in evidence_summary.values())
            / len(evidence_summary)
        )
        if evidence_summary else 100,
        dict(sorted(parity_summary.items())),
        discovery_coverage,
    )


def _walk_columns(columns: tuple[Column, ...]) -> Iterator[Column]:
    for column in columns:
        yield column
        yield from _walk_columns(column.fields)


def _walk_columns_with_path(
    columns: tuple[Column, ...], prefix: str = ""
) -> Iterator[tuple[str, Column]]:
    """Yield each column with its dotted path so findings identify the source column."""
    for column in columns:
        path = f"{prefix}.{column.name}" if prefix else column.name
        yield path, column
        yield from _walk_columns_with_path(column.fields, path)


_COMPATIBILITY_ORDER = (
    Compatibility.DIRECT,
    Compatibility.TRANSFORM,
    Compatibility.REDESIGN,
    Compatibility.UNSUPPORTED,
)

# Kinds that hold data and can therefore be compared row-for-row after migration.
_DATA_BEARING_KINDS = {
    ObjectKind.TABLE,
    ObjectKind.EXTERNAL_TABLE,
    ObjectKind.MATERIALIZED_VIEW,
    ObjectKind.VIEW,
}


def _worst_compatibility(levels: list[Compatibility]) -> Compatibility:
    """Return the least favourable compatibility level in the list."""
    return max(levels, key=_COMPATIBILITY_ORDER.index) if levels else Compatibility.DIRECT


def _parity_applicable(item: BigQueryObject) -> bool:
    """Parity applies to data-bearing objects whether or not a schema was captured.

    Keying this on recorded columns would turn a discovery gap into ``not_applicable``,
    which reads as "nothing to check" rather than "nothing was checked".
    """
    return item.kind in _DATA_BEARING_KINDS


def _storage_layout_findings(item: BigQueryObject) -> tuple[AssessmentFinding, ...]:
    """Recommend layout review from recorded size, partition, and clustering evidence."""
    if item.kind not in {ObjectKind.TABLE, ObjectKind.EXTERNAL_TABLE, ObjectKind.MATERIALIZED_VIEW}:
        return ()
    if item.size_bytes is None or item.size_bytes < 10 * 1024**3:
        return ()

    findings: list[AssessmentFinding] = []
    if not item.partition_field:
        findings.append(AssessmentFinding(
            "WARN",
            item.source_id,
            "Large table has no recorded partition field; review partitioning for scan and refresh efficiency.",
            "PERFORMANCE_PARTITION_REVIEW",
            "performance",
        ))
    if not item.clustering_fields:
        findings.append(AssessmentFinding(
            "WARN",
            item.source_id,
            "Large table has no recorded clustering fields; review workload-driven clustering or indexing.",
            "PERFORMANCE_CLUSTERING_REVIEW",
            "performance",
        ))
    return tuple(findings)


def _streaming_consumers(inventory: BigQueryInventory) -> set[str]:
    objects = {item.source_id: item for item in inventory.objects()}
    streaming_sources = {
        item.source_id
        for item in objects.values()
        if item.kind in {ObjectKind.STREAM, ObjectKind.PUBSUB_TOPIC}
        or item.properties.get("streaming") is True
    }
    consumers: set[str] = set()
    remaining = set(streaming_sources)
    while remaining:
        dependency = remaining.pop()
        direct_consumers = {
            item.source_id
            for item in objects.values()
            if dependency in item.dependencies and item.source_id not in consumers
        }
        consumers.update(direct_consumers)
        remaining.update(direct_consumers)
    return consumers


# Evidence carried on the model itself rather than in the free-form properties bag.
_MODEL_EVIDENCE = {"columns", "sql", "size_bytes", "partition_field", "clustering_fields"}


def _missing_evidence(item: BigQueryObject) -> tuple[str, ...]:
    return tuple(
        field_name
        for field_name in _required_evidence(item.kind)
        if not _has_evidence(
            getattr(item, field_name) if field_name in _MODEL_EVIDENCE
            else item.properties.get(field_name),
            allow_empty=field_name in {"connections", "models"},
        )
    )


def _required_evidence(kind: ObjectKind) -> tuple[str, ...]:
    required: dict[ObjectKind, tuple[str, ...]] = {
        # Core BigQuery kinds. Without these the object was listed, not assessed.
        ObjectKind.TABLE: ("columns", "size_bytes"),
        ObjectKind.EXTERNAL_TABLE: ("columns",),
        ObjectKind.VIEW: ("sql",),
        ObjectKind.MATERIALIZED_VIEW: ("sql", "columns"),
        ObjectKind.ROUTINE: ("language", "sql"),
        ObjectKind.PROCEDURE: ("language", "sql"),
        ObjectKind.SQL_SCRIPT: ("sql",),
        ObjectKind.SPARK_JOB: ("language", "runtime_version", "code"),
        ObjectKind.DATAPROC_JOB: ("language", "runtime_version", "code"),
        ObjectKind.DATAFLOW_JOB: ("streaming", "portable", "connector_compatible"),
        ObjectKind.COMPOSER_DAG: ("operators", "runtime_version", "connections"),
        ObjectKind.DATAFORM_WORKFLOW: ("models", "assertions", "incremental"),
        ObjectKind.LOOKER_ASSET: ("explores", "measures", "joins"),
        ObjectKind.BQML_MODEL: ("model_type", "features", "evaluation_metrics"),
        ObjectKind.VERTEX_AI_PIPELINE: ("pipeline_steps", "models", "endpoints"),
        ObjectKind.SECURITY_POLICY: ("policy_type",),
        ObjectKind.CONNECTION: ("connection_type", "location"),
        ObjectKind.CLOUD_SQL_DATABASE: ("engine", "version", "replication"),
        ObjectKind.SPANNER_DATABASE: ("dialect", "replication", "change_streams"),
    }
    return required.get(kind, ())


def _has_evidence(value: object, *, allow_empty: bool = False) -> bool:
    if value is None:
        return False
    # A recorded boolean is evidence in either state; mapping already acts on False.
    if isinstance(value, bool):
        return True
    if isinstance(value, str) and value.strip().lower() in {"", "unknown", "not specified"}:
        return False
    if isinstance(value, (str, bytes, list, tuple, dict, set)):
        return allow_empty or bool(value)
    return True
