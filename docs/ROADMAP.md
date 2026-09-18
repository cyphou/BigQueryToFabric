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
| Test suite | 30 passed |
| Coverage | 93.25% |
| Static quality | Ruff clean · Pyright clean |
| Agent contracts | 10 agents · exclusive ownership · documentation handoff · 1 skill validated |

### What v0.1.0 proves

- One canonical model can represent BigQuery and the surrounding GCP data platform.
- Fabric targets are selected from workload evidence rather than a universal Lakehouse default.
- Lakehouse/Notebook preferences work as advisory signals.
- Existing Composer DAGs remain Airflow candidates when requested.
- GoogleSQL can be parsed and classified through an AST before translation is attempted.
- Dependency waves, component mappings, findings, lineage, and dry-run artifacts are deterministic.

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
  nullability, and modes with deterministic differences; nested-field and precision extensions
  remain open.
- Add row-count, aggregate, checksum, sample, and null-distribution checks.
- Add SQL result parity for approved test queries.
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