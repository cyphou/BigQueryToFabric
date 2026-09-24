# v0.3 to v0.4 Migration Review

**Reviewer:** Reviewer agent  
**Date:** 2026-09-21  
**Scope:** commits `3f82eb6` through `face250`: SQL/Spark conversion, Dataproc/Dataform/Composer discovery, Fabric generators, CLI integration, and tests.

## Findings

1. **High | SQL statements are silently dropped.** `src/bqtofabric/converter/sql_converter.py:61-109` parses all statements but converts only `statements[0]`. A probe converting `SELECT 1 AS first; SELECT 2 AS second` emitted only the first statement with `direct` compatibility. **Owner: Conversion, P0.** Convert each statement in order or return `REDESIGN` with a blocking manual step.
2. **High | Generated Warehouse SQL changes semantics and is invalid T-SQL.** `src/bqtofabric/generator/warehouse_generator.py:223-245` globally changes `EXCEPT` to `EXCEPT ALL`. Fabric Warehouse T-SQL does not support `EXCEPT ALL`, and it changes BigQuery's default distinct set behavior. The probe generated `SELECT id FROM a EXCEPT ALL SELECT id FROM b`. **Owner: Artifact Generation, P0.** Remove string replacements; use AST conversion and block unsupported output.
3. **High | Generated artifacts are not executable.** `notebook_generator.py:165-252` can emit `df_transformed = df_source` without defining `df_source`, and references undefined `lakehouse_id`. `eventstream_generator.py:180-216` emits invalid KQL for zero columns. `pipeline_generator.py:82-114` depends on nonexistent `Main Activity` for Composer DAGs. **Owner: Artifact Generation, P0.** Label output non-executable until target validators and smoke tests pass.
4. **High | Credential hygiene is incomplete.** `src/bqtofabric/discovery.py:16-64` does not redact `service_account_path`; a probe preserved `C:\secrets\gcp-sa.json`. `converter/spark_converter.py:124-139,204-217` detects embedded credentials but preserves the raw code/path in `source_text` and warnings. **Owner: Security/Conversion, P0.** Redact before persistence/logging, including key-file/service-account path patterns.
5. **High | Warehouse generator invents primary keys.** `warehouse_generator.py:119-140` declares a primary key from BigQuery clustering fields. Clustering does not establish uniqueness. **Owner: Artifact Generation, P0.** Emit index suggestions only unless explicit PK evidence exists.
6. **Medium | Adapter/assessment contracts disagree.** Dataproc outputs `runtime`, not required `runtime_version`/`language` (`dataproc_discovery.py:91-166`); Composer omits required `runtime_version`/`connections`; Dataform workflows omit `models`/`assertions`/`incremental`. Fixture probes show missing evidence on every Dataproc object and Composer DAG, and every Dataform workflow. **Owner: Discovery/Assessment, P1.** Align canonical keys and add contract tests.
7. **Medium | Dataform can silently lose lineage.** `dataform_discovery.py:123-130` catches `DiscoveryError` and returns no target/finding. **Owner: Discovery, P1.** Surface a deterministic review-required component/finding.
8. **Medium | Eventstream and semantic-model outputs are scaffolds, not deployable Fabric definitions.** Eventstream topology is a custom `nodes`/`edges` document with invented connection IDs (`eventstream_generator.py:49-160`), not a tested Fabric Items REST definition. Semantic model mixes DirectQuery/directLake placeholders and crashes on an empty table by indexing `item.columns[0]` (`semantic_model_generator.py:59-75,151-162`). **Owner: Artifact Generation, P1.** Generate official versioned schemas and validate them.
9. **Medium | Quality-gate claims are false.** Full pytest passes 276 tests; focused v0.3/v0.4 modules pass 211. But `python -m pyright` reports 29 errors and `python -m ruff check src tests` fails. Artifact determinism tests compare counts, not bytes (`tests/test_artifact_generation.py:627-696`). **Owner: Quality, P1.** Make both static tools required CI gates and replace weak assertions.

## Executive Summary

**Quality score: 2/5 stars. Risk: Red for production deployment; yellow for offline assessment-only use with prominent caveats.**

This release has a solid assessment foundation: offline discovery is mostly deterministic, canonical objects preserve provenance, SQL uses an AST parser, and artifacts carry source lineage. Discovery tests exercise pagination, snapshot stability, redaction, and safe HTTP errors. The 276-test regression suite is consistently green.

Those strengths do not establish production readiness. The converter silently discards subsequent SQL statements. The Warehouse generator alters set semantics and infers primary keys from clustering. Generated notebooks, KQL, and pipelines have reproducible execution/deployment failures, while Eventstream and semantic-model documents are not validated against Fabric definitions. Secret-bearing paths may be serialized in redaction and Spark-conversion records. New discovery output also fails its own assessment-evidence contract.

Top strengths: deterministic offline discovery; explainable compatibility categories; safe BigQuery error handling. Top recommendations: block executable generation pending target validation; centralize/redact all persisted evidence; add semantic parity, deployment, and adapter-contract tests before v0.5.

## Detailed Audit

### Fidelity and semantic correctness

`SqlConverter` detects joins, windows, aggregates, `QUALIFY`, `UNNEST`, nested types, DML, and procedural patterns, and its warnings/manual steps are a good audit base. It warns that Spark `QUALIFY` needs a derived-table rewrite and that T-SQL `UNNEST` needs manual handling. However, it analyses/emits only the first statement and its compatibility classification is structural, not result-parity based. Tests typically assert non-empty output rather than expected results. No test covers NULL comparison semantics, `NOT IN` with NULL, empty result sets, window-frame/partition boundaries, `SAFE_CAST`, timezone behavior, aggregate ordering/nulls, or multi-statement transactions.

Type mapping correctly marks BIGNUMERIC as a transform and warns that BigQuery precision exceeds Fabric decimal capacity. STRUCT/ARRAY are redesign for Warehouse and JSON has Bronze/Silver guidance. Missing: BIGNUMERIC boundary tests, repeated nested STRUCT lineage, TIME/UTC/JSON/GEOGRAPHY conversions, and generated DDL nullability validation. Warehouse's fallback `varchar(max)` can mask a destructive type conversion.

### Security posture

ADC/read-only boundaries, response-body suppression, and common secret-key/value redaction are sound. Generated values use placeholders rather than hardcoded passwords. But the shared redactor misses service-account paths and other key-file/connection patterns. Spark conversion returns the original code and logs raw paths after detecting credential risk, so conversion evidence can leak secrets. Pipelines set `secureInput` and `secureOutput` to false. Add serialized-output secret scans for inventories, conversion records, warnings, manifests, notebooks, SQL, and JSON.

### Compatibility and warnings

The DIRECT/TRANSFORM/REDESIGN/UNSUPPORTED vocabulary is clear and assessment findings retain source, code, category, severity, and rationale. Yet `TRANSFORM` is considered production-ready even when manual work remains. Dataform discovery can suppress failure without a warning. Artifacts emit TODOs but remain executable-looking. Require machine-readable blocking steps for transforms and emit no deployable artifact for redesign/unsupported cases.

### Artifact quality and deployability

Notebook JSON has superficial Jupyter structure and useful lineage but is not compiled/run. It has undefined variables, unsafe overwrite/merge-schema defaults, and questionable OneLake URI construction. Warehouse scripts are destructive by default, lack source-load logic, and do not validate identifiers, constraints, or T-SQL. Eventhouse can generate invalid KQL; its ingestion mapping syntax is unverified. Eventstream files are descriptive, not accepted Fabric REST payloads. Semantic models lack valid endpoint definitions and have incorrect “Count” measure semantics (`COUNTBLANK`). Pipelines have undeclared linked services/datasets, no core retry policy, invalid Composer dependency edges, and a fixed 2024 trigger start date.

### Determinism and reproducibility

Discovery sorts components; canonical BigQuery output and redaction sort keys; SQL repeat-output tests exist; the artifact manifest uses `{{timestamp}}`. These are good starts. Artifact tests only compare counts. Generator iteration follows input order, JSON does not use `sort_keys=True`, and names such as `warehouse_{item.name}` can overwrite artifacts from different datasets. Add a byte-for-byte two-directory comparison, name-collision fixtures, and equivalent reordered-inventory checks.

### Integration and backward compatibility

Existing default CLI behavior remains offline and new live discovery is opt-in; existing BigQuery/Dataflow tests pass. New kinds reach assessment without crashing. However, adapter property names conflict with `_required_evidence`, and Composer records `schedule` while pipeline generation reads `schedule_interval`, so discovered schedules do not become triggers. Dataproc clusters are modeled as Spark jobs without the evidence Spark-job assessment requires. Add adapter-to-assessment contracts and planner lineage-resolution tests.

### Performance and scale

REST clients page through tokens and use a 60-second timeout. There is no retry/backoff, `Retry-After` support, page-size strategy, bounded concurrency, streaming output, memory benchmark, or 1,000-object test. Dataform details each compilation result and BigQuery details per dataset/table, risking rate limits and memory growth. Add retry/backoff, request accounting, and an estate-scale benchmark before live deployment.

### Documentation and traceability

Public methods mostly have docstrings, generated artifacts preserve source IDs, and fixture payloads are realistic. `docs/SECURITY.md` has a malformed split bullet around dataset ACL evidence and documentation overstates production readiness. Update `docs/KNOWN_LIMITATIONS.md` and `docs/SECURITY.md` with this report's limitations; describe v0.4 as dry-run scaffolding, not deployable output.

## Code Review Highlights

Positive patterns:

- `src/bqtofabric/discovery.py`: non-200 response bodies are never exposed.
- `src/bqtofabric/discovery.py`: sorted canonical output and redaction improve reproducibility.
- `src/bqtofabric/converter/sql_converter.py`: AST-based pattern inventory makes warnings explainable.
- `src/bqtofabric/converter/storage_mapping.py`: clear distinction between shortcut candidates and redesign paths.
- `src/bqtofabric/assessment.py`: evidence and findings are structured and traceable.
- `src/bqtofabric/generator/artifact_generator.py`: fixed timestamp placeholder avoids clock churn.
- `tests/test_discovery.py`: pagination, safe-error, fixture, and determinism coverage is meaningful.

Improvement priorities:

| Severity | Recommendation | Owner |
|---|---|---|
| High | Preserve every SQL statement or block conversion. | Conversion |
| High | Replace Warehouse string substitutions with AST conversion. | Artifact Generation |
| High | Redact conversion source/warnings before serialization. | Security/Conversion |
| High | Remove inferred PKs and destructive default DDL. | Artifact Generation |
| High | Validate notebook, KQL, pipeline, Eventstream, and semantic definitions. | Quality/Artifact Generation |
| Medium | Align adapter properties and assessment evidence. | Discovery/Assessment |
| Medium | Surface Dataform detail-fetch failure. | Discovery |
| Medium | Make paths collision-safe and test artifact bytes. | Artifact Generation |
| Medium | Add rate-limit controls and 1,000-object benchmark. | Discovery |
| Low | Resolve Ruff/Pyright findings. | Quality |

## Test Coverage Analysis

The executed suite has **276 passing tests**; SQL converter, Spark converter, discovery, and artifact generation have **211 focused passing tests**. They cover common parsing/pattern detection, simple null functions, basic storage detection, adapter mapping/redaction, JSON shape, pagination, and repeat conversions/discovery.

Gaps: no result-set parity or target execution; no multi-statement, empty/NULL/partition-boundary behavior; no BIGNUMERIC/nested/JSON/GEOGRAPHY boundaries; no notebook compile or `nbformat` validation; no T-SQL/KQL/Fabric-schema validation; no secret scan of serialized records; no adapter evidence-contract test; no byte-for-byte determinism/collision/reordered-input test; and no scale/rate-limit test. Add golden result fixtures, property tests for NULL/empty/boundary behavior, official schema validation, disposable-workspace integration tests, and CI quality gates.

## Risk Assessment

**Decision: Red.** Production deployment can fail from invalid T-SQL/KQL/pipelines, undeclared connections, collisions, and invalid semantic endpoints. More critically, output can omit statements or alter set semantics while reporting direct/transform compatibility. Credential-bearing conversion evidence can leak.

Mitigation: close P0 findings; mark all generated artifacts non-deployable until official validation passes; redact at every persistence/log boundary; require semantic parity tests; conduct security review and a disposable-workspace deployment rehearsal; then add rate-limit and scale controls.

Pre-production sign-off:

- [ ] P0 fidelity, redaction, DDL, and artifact validity regressions resolved.
- [ ] Ruff and Pyright pass in CI.
- [ ] Every definition validates against its official Fabric parser/schema.
- [ ] Disposable non-production deployment succeeds with rollback evidence.
- [ ] Parity suite covers NULL, empty, boundaries, windows, aggregates, subqueries, and scripts.
- [ ] Secret scan covers inventories, logs, manifests, and all artifacts.
- [ ] Every supported adapter object meets the evidence contract or produces a finding.
- [ ] 1,000-object benchmark meets agreed time/memory/API budgets.

## Handoff Readiness

| Exit criterion | Status | Notes |
|---|---|---|
| Offline, non-destructive default | Yes | Default path remains dry-run. |
| Deterministic assessment/discovery | Partial | Artifact byte stability/collision behavior unproven. |
| Complete warnings | No | SQL truncation and Dataform failure can be silent. |
| Semantics-preserving conversion | No | P0 truncation and set-operation drift. |
| Credential hygiene | No | Service-account/raw Spark paths can persist. |
| Deployable artifacts | No | Reproduced notebook, KQL, pipeline, and endpoint failures. |
| Tests and static gates green | No | Tests pass; Ruff/Pyright fail. |
| Scale readiness evidence | No | No benchmark/retry/rate-limit validation. |

**Blockers for Documentation agent: No procedural blocker.** Documentation can incorporate these results now, but must characterize v0.4 as dry-run scaffolding and list P0/P1 limitations.

**Blockers for production deployment: Yes.** P0 items and all pre-production checks are release blockers.

**Recommended v0.5:** conversion-fidelity harness; centralized serialized-output redaction; canonical adapter/assessment contract repair; official Fabric artifact schemas; non-production deployment validation; byte determinism/collision/scale tests as CI requirements.
