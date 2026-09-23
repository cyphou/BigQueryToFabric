---
name: assisted-evidence
description: >-
  Infer BQToFabric inventory evidence from source artifacts an adapter cannot read,
  and record it as assisted provenance. Use when a Dataproc or Spark job body, a
  Composer DAG, a Dataflow pipeline, LookML, or a BQML DDL is available in a
  repository but not captured by discovery. Triggers: "read the job code and fill
  the inventory", "infer evidence", "assisted provenance", "fill properties.code",
  "agent-discovered evidence", "déduire l'évidence depuis le code source".
---

# Assisted evidence

Discovery reads APIs. It cannot read a Dataproc job body, a DAG file, or a LookML
model, because those live in repositories and buckets. An agent can read them, and
that inference is genuinely useful — provided it enters the system as **evidence**
and never as a **verdict**.

## The one rule

> Supply evidence. Never supply a conclusion.

Do **not** decide `compatibility`, `target`, `wave`, `manual_review`, or a parity
status. Those are derived by the deterministic engine from the evidence you provide,
and that derivation is what makes the assessment reproducible and auditable.

Your job is to fill `properties` and model fields, then let `bqtofabric assess` decide.

## Marking the work

Set `discovered_from` to `assisted` on every object whose evidence you inferred:

```json
{
  "source_id": "acme.dataproc.nightly_etl",
  "name": "nightly_etl",
  "kind": "dataproc_job",
  "discovered_from": "assisted",
  "properties": {
    "language": "python",
    "runtime_version": "2.1",
    "code": "from pyspark.sql import SparkSession\n..."
  }
}
```

Consequences, which are deliberate:

- Incomplete evidence is a `FAIL` `ASSISTED_EVIDENCE_INCOMPLETE`.
- Complete evidence still emits `WARN` `ASSISTED_EVIDENCE_UNVERIFIED` and sets the
  `assisted_evidence` manual-review reason. It can never reach a wave unreviewed.

Never label inferred evidence `bigquery_api`, `dataproc_api`, or any other `*_api`
value. Those assert the evidence was read from the source system. Mislabelling turns
a reviewable inference into an invisible one.

## Inference recipes

| Kind | Read | Fill |
|---|---|---|
| `dataproc_job`, `spark_job` | The main file referenced by `main_file`, plus the cluster or batch config | `code` (full body), `language` (`python`/`scala`/`java`), `runtime_version` (image or runtime version) |
| `composer_dag` | The DAG `.py` file | `operators` (operator class names used), `runtime_version` (Composer image), `connections` (every `conn_id` referenced) |
| `dataflow_job` | The pipeline source | `streaming` (true when reading an unbounded source), `portable` (Beam portable runner), `connector_compatible` |
| `dataform_workflow` | `definitions/` | `models`, `assertions`, `incremental` |
| `looker_asset` | LookML model and view files | `explores`, `measures`, `joins` |
| `bqml_model` | `CREATE MODEL` DDL | `model_type`, `features`, `evaluation_metrics` |
| `routine`, `procedure` | `CREATE FUNCTION`/`PROCEDURE` DDL | `language`, `sql` |
| `view`, `materialized_view`, `sql_script` | The SQL body | `sql` (model field, not a property) |

`columns`, `sql`, `size_bytes`, `partition_field` and `clustering_fields` are **model
fields**, not `properties` entries.

## What you must refuse to infer

Some evidence cannot be derived from source artifacts. Leaving it absent produces an
honest gap; inventing it produces a confident wrong answer that survives review.

- **`size_bytes`** — a measurement, not a property of code. Never estimate it.
- **`columns` for a `table`** — infer only from authoritative DDL or a schema export.
  Do not reconstruct a schema from `SELECT` statements.
- **Parity evidence** — requires measuring both platforms. An agent that has not run
  the queries has nothing to record.
- **`policy_type` and effective access** — ACLs are not proof of effective IAM.
- **Anything ambiguous.** A `FAIL` for missing evidence is a better outcome than a
  plausible guess, because the `FAIL` gets fixed and the guess does not.

If a field is uncertain, omit it and say so in your report.

## Verify before handing off

```powershell
bqtofabric validate inventory.json
bqtofabric assess inventory.json
```

Then confirm:

- `discoveryCoverage` shows the expected `assisted` count — no more, no less.
- No object you touched claims an `*_api` provenance.
- `ASSISTED_EVIDENCE_INCOMPLETE` appears only where you knowingly left a gap.
- The score moved because evidence arrived, not because a gate was bypassed.

Report what you inferred, from which artifact, and what you deliberately left absent.
A reviewer confirming your inference needs to know where to look.

## References

- [Inventory authoring](../inventory-authoring/SKILL.md)
- [Finding triage](../finding-triage/SKILL.md)
- [Inventory schema](../../../docs/INVENTORY_SCHEMA.md)
