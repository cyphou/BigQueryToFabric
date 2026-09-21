# Development Roadmap

BQToFabric is currently an offline, non-destructive assessment and planning engine. The roadmap
moves it from canonical JSON inventories to evidence-backed live discovery, conversion,
validation, and explicitly approved Fabric deployment.

## Current baseline — v0.1.0

Measured on the committed GCP ecosystem fixture and local validation commands:

| Signal | Verified value |
|---|---|
| Supported source taxonomy | 25 GCP/BigQuery component types |
| Fabric decision surface | 15 primary/supporting target roles |
| Live discovery | BigQuery metadata, read-only, credential-redacting |
| Reference portfolio | 19 assessed components |
| Reference recommendation | Lakehouse primary · hybrid architecture · Airflow retained |
| Public CLI | 7 commands |
| Generated package | 9 deterministic dry-run artifacts |
| Test suite | 73 passed |
| Coverage | 93.25% |
| Static quality | Ruff clean · Pyright clean |
| Agent contracts | 10 agents · exclusive ownership · documentation handoff · 1 skill validated |

### Validated assessment test guide

- **Expected:** Reviewers can reproduce the offline fixture assessment and understand the live
  BigQuery read-only path, generated evidence, and `WARN`/`FAIL` triage without cloud mutation.
- **Implemented:** README and the migration runbook document the exact install, pytest, validate,
  inventory, assess, plan, generate, manifest, and deployment-check commands. They document
  `findings`, `evidence_summary`, `discovery_coverage`, `parity_summary`, `stageReadiness`,
  `manualReview`, `manualReviewReasons`, `processingStage`, and exit code `3`.
- **Validated:** Documentation commands and artifact names were checked against the current CLI
  workflow and generated-package contract; the repository baseline is `73 passed`.
- **Open:** No authorized live-GCP sandbox run is claimed. Non-BigQuery GCP services remain
  offline payload normalization and assessment inputs without live adapters.

### What v0.1.0 proves

- One canonical model can represent BigQuery and the surrounding GCP data platform.
- Fabric targets are selected from workload evidence rather than a universal Lakehouse default.
- Lakehouse/Notebook preferences work as advisory signals.
- Existing Composer DAGs remain Airflow candidates when requested.
- GoogleSQL can be parsed and classified through an AST before translation is attempted.
- Dependency waves, component mappings, findings, lineage, and dry-run artifacts are deterministic.

### Validated processing-chain example

- **Expected:** The generated target manifest makes the complete BigQuery/GCP-to-Fabric processing chain reviewable, assigning each known source kind a processing stage and preserving a deterministic dependency order.
- **Implemented:** `fabric/target-manifest.json` includes `processingStage`, `wave`, and `dependencies` for every entry. Known source kinds are categorized as `ingestion`, `storage`, `transformation`, `orchestration`, `consumption`, `governance`, `integration`, or `operational`.
- **Validated:** `python -m pytest tests/test_cli.py -q` passed with `8 passed`.
- **Open:** This is a deterministic dry-run review artifact only. It does not execute processing paths, connect to GCP or Fabric, deploy anything, or establish runtime data parity.

### Validated stage-readiness summary

- **Expected:** The generated target manifest provides a deterministic per-stage compatibility
  rollup that helps reviewers prioritize migration work without implying runtime readiness.
- **Implemented:** `fabric/target-manifest.json` has a top-level `stageReadiness` object for every
  `processingStage` represented by entries; absent stages are omitted. Each stage includes `total`,
  counts for `direct`, `transform`, `redesign`, and `unsupported`, `manualReview`, and `readiness`.
  `readiness` is the rounded weighted average of component compatibility with `direct=100`,
  `transform=80`, `redesign=50`, and `unsupported=0`.
- **Validated:** `python -m pytest tests/test_cli.py -q` passed with `8 passed`.
- **Open:** The rollup prioritizes migration review only. It is not proof of execution, parity,
  security remediation, or deployment readiness.

### Validated migration-plan findings section

- **Expected:** The human-readable migration plan should make assessment `WARN` and `FAIL` findings
  actionable without requiring reviewers to open `assessment.json` first.
- **Implemented:** Generated `migration-plan.md` includes a `Findings` section. Each finding lists
  `severity`, `code`, `category`, `source`, and `message`, preserving the assessment evidence inside
  the dry-run report.
- **Validated:** `python -m pytest tests/test_cli.py -q` passed with `8 passed`.
- **Open:** Findings in the report are review evidence only. They do not prove remediation,
  deployment readiness, runtime parity, or security parity.

### Validated migration-plan assessment summary

- **Expected:** The human-readable migration plan should provide deterministic rollups that help
  reviewers prioritize findings, processing stages, and manual-review work.
- **Implemented:** Generated `migration-plan.md` includes an `Assessment summary` with a Gate/Value
  table for total, `FAIL`, and `WARN` findings, components requiring manual review, `Parity checks`,
  and `Parity not run` totals. It also includes readiness percentage and manual-review counts by
  processing stage, and deterministic manual-review reason frequencies. `Parity not run` means
  runtime evidence is absent, not that parity succeeded. Existing findings, component, evidence,
  parity, and migration wave sections remain in the report; the detailed `Parity evidence` table
  is unchanged.
- **Validated:** The reporting change was validated with the focused CLI tests and the full test
  suite; Ruff is clean for the changed reporting and CLI test files.
- **Open:** These are deterministic review summaries only. They do not prove deployment readiness,
  runtime parity, security remediation, or finding remediation.

### Validated streaming downstream guardrail

- **Expected:** A `DATAFLOW_JOB` whose `properties.streaming` is `true` causes every transitive
  downstream canonical object to be reviewed as a streaming consumer.
- **Implemented:** Assessment adds the `WARN` finding `STREAMING_DOWNSTREAM_REVIEW` to every
  downstream object, requiring review of deduplication, idempotency, and out-of-order delivery.
  Planner output marks those consumers `manual_review`; the source streaming job is already
  `redesign`/`manual_review`.
- **Validated:** `python -m pytest tests/test_assessment.py -q` passed with `8 passed`.
- **Open:** The guardrail evaluates static inventory dependency evidence only. It does not
  execute or monitor live stream processing, validate data, or deploy Fabric artifacts.

### Validated actionable manual-review reasons

- **Expected:** A `PlanItem` marked `manual_review` retains that decision flag and records a
  deterministic reason list so reviewers can act on the specific planning condition. Both the
  human-readable migration plan and generated target manifest expose the decision and reasons.
- **Implemented:** `PlanItem.manual_review_reasons` uses the codes `external_dependency`,
  `incompatible_mapping`, `streaming_downstream_review`, `incomplete_external_adapter`,
  `depends_on_incomplete_external_adapter`, `sql_incompatibility`, and
  `cycle_or_unresolved_dependency`. `migration-plan.md` renders `manual_review` and the reason
  codes; `fabric/target-manifest.json` exposes the matching `manualReview` and
  `manualReviewReasons` fields. `manual_review` remains the decision flag; reasons make the
  decision actionable.
- **Validated:** `python -m pytest tests/test_assessment.py tests/test_cli.py -q` passed with
  `19 passed`.
- **Open:** This is deterministic, offline planning metadata only. It does not make cloud calls,
  change deployment behavior, establish runtime compatibility, or resolve the listed review
  conditions automatically.

### Validated dataset access review guardrail

- **Expected:** Live dataset `access` entries provide redacted dataset-level evidence only and
  cannot be treated as proof of effective project, organization, group, or inherited IAM access.
- **Implemented:** Discovery serializes every dataset access entry as a redacted `security_policy`
  record with `evidence_scope: dataset_access_entry`. Assessment emits `FAIL`
  `SECURITY_EFFECTIVE_ACCESS_REVIEW`, requiring manual security review. Discovery makes no IAM API
  calls and does not extract project/org IAM, connection IAM, BigQuery Data Policies, policy tags,
  or distinct row access policies.
- **Validated:** `python -m pytest tests/test_discovery.py tests/test_assessment.py -q` passed
  with `25 passed`.
- **Open:** This is not an effective-access calculation and establishes no source-rights or
  Fabric-security parity. Manual security review must account for project, organization, group,
  inherited IAM, and the unextracted governance controls.

### Validated discovery provenance

- **Expected:** Assessment evidence must distinguish objects obtained through the BigQuery API from
  canonical JSON inventory and supplied external GCP payloads, without claiming freshness or live
  discovery coverage for associated services.
- **Implemented:** `BigQueryObject.discovered_from` defaults imported canonical JSON to `inventory`;
  the live BigQuery provider stamps `bigquery_api`; and normalized external GCP payloads stamp
  `external_payload`. Assessment exposes provenance per object in `evidence_summary` and reports
  deterministic counts per source in `AssessmentReport.discovery_coverage`.
- **Validated:** `python -m pytest tests/test_models.py tests/test_discovery.py
  tests/test_gcp_components.py tests/test_assessment.py -q` passed with `29 passed`.
- **Open:** Provenance distinguishes collection paths only. It does not validate metadata freshness
  and does not implement live adapters for Dataflow, Composer, Dataproc, Dataform, Workflows,
  Pub/Sub, GCS, Looker, Vertex AI, Dataplex, Cloud SQL, or Spanner.

### Validated incomplete external-payload guardrail

- **Expected:** An externally supplied component marked `discovered_from: external_payload` that
  lacks required offline evidence must fail closed without implying a live adapter, and its complete
  downstream dependency chain must require review.
- **Implemented:** Assessment emits exactly one `FAIL` `EXTERNAL_PAYLOAD_INCOMPLETE_ADAPTER`
  finding in category `adapter`, explaining that offline evidence must be completed because no live
  adapter is implemented. The planner marks the component and all direct/transitive dependents
  `manual_review`. These review states are not unresolved dependencies:
  `unresolved_dependencies` remains for missing or external source IDs and dependency cycles.
- **Validated:** `python -m pytest tests/test_assessment.py -q` passed with `11 passed`.
- **Open:** The behavior is offline and non-destructive. It makes no cloud calls and does not
  implement external GCP live adapters; users must supply complete offline evidence before a
  reviewed migration decision can rely on the affected component.

### What v0.1.0 does not prove

- Completeness against a live GCP organization or project.
- Executable equivalence of generated SQL, Spark, Airflow, pipeline, or Fabric definitions.
- Data parity, performance parity, security parity, refresh success, or deployment success.
- Production readiness of generated notebook and pipeline skeletons.

## Delivery principles

1. **Evidence before automation.** A stage cannot claim success without a check that proves it.
2. **Dry-run first.** Discovery is read-only; deployment remains explicit and opt-in.
3. **Native connectors first.** Use Fabric's BigQuery connector and OneLake capabilities before introducing custom movement code.
4. **Preserve source intent.** Airflow remains Airflow when that reduces migration risk; each workload retains an appropriate target.
5. **Fail closed on security.** Missing policy equivalence is a blocker, not a warning to ignore.
6. **Deterministic artifacts.** The same inventory and configuration must produce byte-stable output.

## Release tracks

### v0.2 — Live GCP discovery *(in progress)*

**Goal:** replace hand-authored inventories with reproducible, read-only discovery.

- **Expected:** An authenticated user can produce a deterministic, credential-safe canonical
  inventory from the supported BigQuery metadata surface, then use the existing offline assessment
  workflow without claiming IAM or governance-policy completeness.
- **Implemented:** `bqtofabric discover` uses user Application Default Credentials with
  `https://www.googleapis.com/auth/bigquery.readonly`. It discovers datasets, tables, views,
  materialized views, external tables, routines, procedures, BQML models, jobs, scheduled-query
  transfer configurations, connections, and dataset GET `access` entries. Access entries are
  redacted into canonical `security_policy` records with `evidence_scope:
  dataset_access_entry`. Assessment emits `FAIL` `SECURITY_EFFECTIVE_ACCESS_REVIEW`, requiring
  manual security review because this evidence does not establish effective project, organization,
  group, or inherited IAM access. It makes no IAM API calls and does not extract project/org IAM,
  connection IAM, BigQuery Data Policies, policy tags, or distinct row access policies. Discovery
  failures return exit code `3` without printing provider response bodies. Dataflow, Composer,
  Dataproc, Dataform, Workflows, Pub/Sub, GCS, Looker, Vertex AI, Dataplex, Cloud SQL, and Spanner remain offline
  normalization/assessment only.
- **Validated:** Discovery mapping, deterministic serialization, redaction, pagination, and
  provider-failure body suppression are covered by offline fixture tests.
- **Open:** No authorized live-GCP sandbox test has run. The three required APIs, dataset metadata
  visibility, and project-level job-history visibility must be verified in a live project before
  this can claim live metadata parity. Project/org IAM, connection IAM, distinct row access
  policies, data policies, policy tags, and all external-family adapters remain unimplemented and
  require security review where they affect migration decisions.

- **Implement `GoogleCloudInventoryProvider` behind an optional `gcp` dependency group.** *Done.*
  The provider consumes BigQuery REST resources through a `BigQueryMetadataClient` protocol, so
  discovery is exercised offline against committed API payloads and needs no credentials to test.
- **Redact credential-like metadata by construction.** *Done.* Labels and properties pass through
  `redact`, which replaces secret-like keys and values with `[redacted]`. Failed requests raise
  `DiscoveryError` carrying only a status code, because response bodies can echo request headers.
- **Discover BigQuery datasets, schemas, views, routines, partitioning, sizes, labels, locations.**
  *Done.* Tables, views, materialized views, external tables, routines, procedures, and BQML models
  map to canonical objects. Legacy REST type names (`INTEGER`, `FLOAT`, `BOOLEAN`, `RECORD`) are
  normalized to `INT64`, `FLOAT64`, `BOOL`, and `STRUCT`; without that the type mapper would treat
  every discovered column as an unknown type.
- **Capture cross-project dependencies and unresolved references explicitly.** *Done.* View and
  routine bodies are parsed with `sqlglot`; two-part and bare references are completed with the
  owning project and dataset. Bodies that do not parse — JavaScript UDFs, for example — record an
  `unresolved_references` note instead of a guessed dependency.
- **Add a CLI command for live discovery and sanitized export.** *Done.* `bqtofabric discover`
  writes a deterministic canonical inventory and returns a dedicated exit code when credentials
  are unavailable.
- **Discover BigQuery jobs, scheduled queries, connections, and access policies.** *Done.*
  Jobs preserve type, SQL dependencies, location, state, priority, and write dispositions;
  scheduled queries preserve schedule, owner, parameters, and transfer identity; connections and
  dataset access policies are sanitized into canonical components.
- **Normalize external GCP adapter payloads into canonical `components`.** *Done.* The shared
  normalizer redacts metadata, preserves dependencies, sorts output deterministically, and ignores
  unknown kinds without inventing a source type.
- **Add live adapters for Dataproc, Dataflow, Dataform, Composer, Workflows, Pub/Sub, GCS, Looker,
  Vertex AI, Dataplex, Cloud SQL, and Spanner.** *Open.* Endpoint coverage, permissions, and an
  authorized sandbox are still required; normalization alone does not claim live discovery.

**Exit gate**

- A read-only integration test against an authorized sandbox inventories all enabled adapters.
  *`not_run`.* `create_rest_client` and the `gcp` extra are unverified until an authorized
  environment exists; no local check can promote them.
- No secret value appears in logs, JSON, snapshots, or exception messages. *Proven* by redaction
  tests over secret keys, nested private keys, bearer values, and a failing request.
- Repeated discovery of an unchanged project produces equivalent canonical inventories. *Proven*
  by a determinism test and a committed snapshot of the serialized inventory.

### v0.3 — Conversion workbench

**Goal:** turn assessment recipes into reviewable source conversions.

- Expand GoogleSQL AST analysis and transpilation to Spark SQL and Fabric Warehouse T-SQL.
- Cover BigQuery functions, scripting, `QUALIFY`, `UNNEST`, arrays, structs, UDFs, procedures, and materialization patterns.
- Convert Spark/Dataproc code to Fabric notebooks, including GCS path and runtime substitutions.
- Translate Dataform graphs, assertions, variables, and incremental models.
- Produce Composer/Airflow compatibility reports for operators, providers, sensors, pools, connections, SLAs, and plugins.
- Add negative controls proving unsupported constructs remain explicit.

**Exit gate**

- Every conversion records source, target dialect/runtime, compatibility, warnings, and manual steps.
- Golden tests cover representative SQL, Spark, Dataform, and Airflow patterns.
- No regex-only SQL rewriting enters the production conversion path.

### v0.4 — Fabric project generation

**Goal:** generate structurally valid, importable Fabric project definitions.

- Generate Lakehouse metadata and Delta DDL with Bronze/Silver/Gold layouts.
- Generate Fabric notebooks with valid metadata, parameters, lakehouse bindings, outputs, and dependencies.
- Generate Warehouse schemas, tables, views, procedures, and load scripts.
- Generate Data Pipelines using native BigQuery Copy/Lookup activities and parameterized schedules.
- Generate Eventstream/Eventhouse definitions for supported streaming patterns.
- Generate Airflow Job packages for compatible Composer DAGs.
- Generate semantic-model and Data Science scaffolds for Looker, BQML, and Vertex AI.

**Exit gate**

- Every generated JSON, notebook, SQL file, and item definition passes a format-specific validator.
- Generated bundles are deterministic and contain no environment-specific secret.
- Unsupported operational bindings remain explicit placeholders rather than fabricated IDs.

### v0.5 — Parity and migration evidence

**Goal:** prove behavior instead of only proving structure.

- **Implemented:** Offline source/target schema comparison covers field presence, types,
  nullability, modes, and nested fields with deterministic differences; precision-specific
  extension rules remain open.
- **Implemented:** Offline per-column null-distribution comparison requires valid, non-negative
  `null_count` and `row_count` evidence on each side, with `null_count <= row_count`. It returns
  `passed` only when column sets and values match, `failed` with deterministic differences for
  missing columns or value mismatches, and `not_run` for missing or invalid evidence. Live query
  execution remains open.
- **Implemented:** Offline row-count comparison returns `passed`, `failed`, or `not_run` from
  supplied evidence; live query execution remains open.
- **Implemented:** Offline named aggregate comparison reports deterministic metric differences;
  live aggregate query execution remains open.
- **Implemented:** Offline checksum evidence comparison returns `passed` only when source and
  target provide complete matching algorithm, canonical ordering, and digest; it returns
  `failed` for any difference and `not_run` for missing evidence. Live checksum query
  execution remains open.
- **Implemented:** Offline sample comparison requires each source and target to provide a
  method, ordering, and rows list. It returns `passed` only when all three values match,
  `failed` with deterministic field differences otherwise, and `not_run` when evidence is
  missing or malformed. Live sample query execution remains open.
- **Implemented:** Offline SQL-result comparison requires source and target evidence with an
  approved `query_id`, ordering, and rows list. It returns `passed` only when all three values
  match, `failed` with deterministic field differences otherwise, and `not_run` when evidence
  is missing or malformed. The parity summary includes `sql_result`. Live source/Fabric SQL
  query execution remains open. *Validated by `python -m pytest tests/test_parity.py -q` (16
  passed).*
- Add partition, clustering, file-size, and performance recommendations from measured workloads.
- Add security matrices for IAM, policy tags, authorized views, Fabric permissions, and RLS.
- Produce a portable evidence package for architecture review and migration sign-off.

**Exit gate**

- Each migrated object has a parity status: `passed`, `failed`, `not_run`, or `not_applicable`.
- Missing runtime evidence can never be rendered as success.
- Security blockers prevent a production-ready verdict.

### v0.6 — Controlled deployment

**Goal:** deploy reviewed artifacts safely into Microsoft Fabric.

- Add Entra authentication through environment or managed identity boundaries.
- Discover workspaces and capacities without hardcoded IDs.
- Implement plan/apply separation with an immutable deployment manifest.
- **Implemented:** Generate and verify an immutable dry-run manifest with `manifest-verify`;
  authenticated Fabric apply, identity, retries, and rollback remain open.
- **Implemented:** `deployment-check` blocks tampered manifests, invalid artifacts, unresolved
  dependencies, and unsupported components; it returns `ready_for_review`, never `apply`.
- Create and update supported Fabric items through documented APIs.
- Add idempotency, retries, long-running-operation handling, rollback guidance, and audit logs.
- Require explicit confirmation for every mutating operation.

**Exit gate**

- Dry-run and apply produce matching manifests.
- Integration tests deploy to and remove from an isolated Fabric sandbox.
- Reapplying an unchanged bundle is idempotent.
- No credentials or bearer tokens appear in logs or artifacts.

### v1.0 — Production migration program

**Goal:** support repeatable portfolio migration with governance and operational evidence.

- Portfolio dashboards, wave planning, ownership, effort estimates, dependencies, and blockers.
- Incremental migration and change detection for source schema and code evolution.
- Environment promotion across development, test, and production workspaces.
- Plugin contracts for organization-specific mappings and policy controls.
- Versioned inventory, plan, artifact, and evidence schemas with upgrade tooling.
- Release packaging, upgrade notes, support matrix, and operational runbooks.

**Exit gate**

- Two representative migrations complete discovery, conversion, generation, validation, deployment, and parity evidence.
- Backward compatibility is documented and tested for public schemas and CLI commands.
- Production readiness requires runtime evidence; static checks alone cannot grant it.

## Cross-cutting backlog

### Quality and contracts

- JSON Schema for inventory, assessment, plan, and deployment manifests.
- Producer/consumer contract tests between every pipeline stage.
- Stable finding codes and remediation categories rather than message-text coupling.
- Corpus gate over sanitized real-world inventories.
- One owner per implementation path, validated by `scripts/validate_agents.py`.
- Every validated implementation change is followed by a Documentation-agent update comparing
  expected, implemented, validated, and open behavior.

### Security and governance

- Credential-redaction tests for every provider and deployment error path.
- Least-privilege role matrix for GCP discovery and Fabric deployment.
- Data residency and region compatibility checks.
- Purview glossary, classification, lineage, and ownership mapping.

### Developer experience

- Example inventory generator and schema documentation.
- Machine-readable CLI output and CI-friendly exit policies.
- Windows, Linux, and container development instructions.
- Release automation, changelog, contribution guide, and issue templates.

### Performance and scale

- Streaming inventory readers for large estates.
- Cached SQL parsing and parallel assessment with deterministic ordering.
- Portfolio benchmarks for 1K, 10K, and 100K components.
- Memory and runtime budgets enforced in CI.

## Priority now

**v0.2 continues with the remaining BigQuery surface**: jobs, scheduled queries, connections, and
access policies. Scheduled queries and policies matter most, because the assessment already treats
them as a Data Pipeline target and a security blocker respectively, so a project inventoried today
looks safer than it is.

The wider GCP adapters follow the same seam: each one only has to emit `components` entries for
kinds the mapping engine already understands. `create_rest_client` stays unverified until a
read-only sandbox is available; that gap is recorded in the v0.2 exit gate rather than hidden.

## Non-goals

- A proprietary BigQuery-to-OneLake data mover when native Fabric connectors meet the need.
- Automatic conversion of unsupported security semantics without human approval.
- Treating DAX as an ETL language.
- Declaring deployment or data parity from static validation alone.
- Forcing every workload into Lakehouse when another Fabric service or Airflow is a better fit.