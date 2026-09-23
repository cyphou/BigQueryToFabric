---
name: finding-triage
description: >-
  Triage BQToFabric assessment findings and decide what blocks a migration wave.
  Use when reviewing assessment output, interpreting a finding code, deciding whether
  a WARN can be accepted, or explaining why deployment-check reports blocked.
  Triggers: "what does this finding mean", "triage findings", "why is deployment
  blocked", "can I ignore this WARN", "MAPPING_UNSUPPORTED", "PARITY_NOT_RUN",
  "EXTERNAL_PAYLOAD_INCOMPLETE_ADAPTER", "trier les findings".
---

# Finding triage

Assessment emits 16 stable codes. Severity is not advisory decoration: every `FAIL`
clamps its component's readiness score to zero and blocks `deployment-check`.

## Triage order

1. **`blockers` in `assessment-summary.json`** — every FAIL, with its source id.
2. **Adapter and security FAILs** — these mean evidence is absent or unproven, which
   is usually cheaper to fix than a redesign.
3. **Mapping and SQL redesigns** — real migration work; schedule into a wave.
4. **Evidence WARNs** — fix by completing the inventory, not by suppressing.
5. **Advisory WARNs** — `ACTION_REQUIRED` and `PERFORMANCE_*` are per-kind guidance.

## Code reference

| Code | Sev | Category | Trigger | Action |
|---|---|---|---|---|
| `MAPPING_UNSUPPORTED` | FAIL | mapping | No Fabric target can run the workload | Redesign or descope. Blocks the wave. |
| `PARITY_FAILED` | FAIL | parity | Supplied evidence disagrees between source and target | Investigate the data difference before migrating. |
| `SECURITY_EFFECTIVE_ACCESS_REVIEW` | FAIL | security | Dataset ACL entry found | ACLs are not proof of effective IAM. Review inherited and org-level access. |
| `SECURITY_EVIDENCE_MISSING` | FAIL | security | Required evidence absent on a `security_policy` | Complete the policy evidence. |
| `EXTERNAL_PAYLOAD_INCOMPLETE_ADAPTER` | FAIL | adapter | `discovered_from: external_payload` with missing required evidence | No live adapter exists, so offline evidence must be complete. |
| `DATAFORM_COMPILATION_DETAILS_UNAVAILABLE` | FAIL | adapter | Dataform compilation could not be read | Lineage is unproven; supply compilation output. |
| `MAPPING_REDESIGN` | WARN | mapping | Target requires structural rework | Plan the redesign; it already forces manual review. |
| `SQL_REDESIGN` | WARN | sql | GoogleSQL has no faithful translation | Rewrite and add parity evidence. |
| `TYPE_REDESIGN` | WARN | schema | Column type needs a modelling decision | Decide flattening or nesting; check the listed column paths. |
| `TYPE_UNSUPPORTED` | FAIL | schema | Unrecognized type name | Confirm whether it is a discovery gap or genuinely unsupported. |
| `PARITY_NOT_RUN` | WARN | parity | No parity evidence supplied | Not success. Supply evidence or accept the risk explicitly. |
| `EVIDENCE_MISSING` | WARN | evidence | Required evidence absent | Complete the inventory. |
| `STREAMING_DOWNSTREAM_REVIEW` | WARN | processing | Component consumes a streaming source | Review dedup, idempotency and out-of-order delivery. |
| `ACTION_REQUIRED` | WARN | mapping | Per-kind migration advice | Informational; one per mapping action. |
| `PERFORMANCE_PARTITION_REVIEW` | WARN | performance | Large table with no partition field | Review partitioning before load. |
| `PERFORMANCE_CLUSTERING_REVIEW` | WARN | performance | Large table with no clustering | Review clustering keys. |

## Reading counts correctly

`ACTION_REQUIRED` and `EVIDENCE_MISSING` dominate WARN totals on most estates. A high
WARN count is therefore not a risk signal on its own — read `blockers`,
`manualReviewReasons` and `paritySummary` instead.

`TYPE_REDESIGN` is emitted once per distinct type per object, listing the affected
column paths, so counts reflect distinct risks rather than schema width.

## Why deployment-check blocks

`deployment-check` is blocked by any of:

- artifact validation not passing
- unresolved plan dependencies
- unsupported components
- any FAIL blocker or FAIL finding count
- failed parity checks
- components requiring redesign
- components awaiting manual review

Blocked is the expected state until evidence is supplied. It is not a tool error.

## References

- [Mapping reference](../../../docs/MAPPING_REFERENCE.md)
- [Migration runbook](../../../docs/MIGRATION_RUNBOOK.md)
