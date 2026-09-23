"""Regenerate the embedded OBJECTS dataset in the object deep-dive report.

The report ships a static snapshot of the reference fixture assessment. Keeping it
in sync by hand drifts, so it is rebuilt from a live run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from bqtofabric.assessment import run_assessment
from bqtofabric.inventory import JsonInventoryProvider
from bqtofabric.planner import build_plan

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "gcp_ecosystem_project.json"
REPORT = ROOT / "docs" / "assessment-object-deep-dive.html"


def build_objects() -> list[dict[str, object]]:
    inventory = JsonInventoryProvider(FIXTURE).load()
    report = run_assessment(inventory)
    plan = build_plan(inventory, report)

    plan_items = {item.source_id: item for item in plan.items}
    decisions = {decision.source_id: decision for decision in report.decisions}
    sql_results = {result.source_id: result for result in report.sql_assessments}

    findings_by_source: dict[str, list[str]] = {}
    for finding in report.findings:
        codes = findings_by_source.setdefault(finding.source_id, [])
        if finding.code not in codes:
            codes.append(finding.code)

    rows: list[dict[str, object]] = []
    for source_id in sorted(decisions):
        item = plan_items[source_id]
        evidence = report.evidence_summary.get(source_id, {})
        row: dict[str, object] = {
            "source_id": source_id,
            "target": decisions[source_id].target.value,
            "wave": item.wave,
            "review": item.manual_review,
            "reasons": list(item.manual_review_reasons),
            "missing": list(evidence.get("missing", [])),  # type: ignore[arg-type]
            "findings": findings_by_source.get(source_id, []),
        }
        sql_result = sql_results.get(source_id)
        if sql_result is not None:
            row["sql"] = {
                "status": sql_result.compatibility.value,
                "dialect": sql_result.target_language,
                "converted": sql_result.converted_sql,
                "notes": list(sql_result.notes),
            }
        rows.append(row)
    return rows


def main() -> None:
    rows = build_objects()
    body = ",\n".join(
        f"  {json.dumps(row, separators=(',', ':'))}" for row in rows
    )
    text = REPORT.read_text(encoding="utf-8")
    updated, count = re.subn(
        r"(const OBJECTS = \[\n).*?(\n\];)",
        lambda match: f"{match.group(1)}{body}{match.group(2)}",
        text,
        flags=re.DOTALL,
    )
    if count != 1:
        raise SystemExit(f"expected exactly one OBJECTS block, found {count}")
    REPORT.write_text(updated, encoding="utf-8")
    print(f"Updated {len(rows)} objects in {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
