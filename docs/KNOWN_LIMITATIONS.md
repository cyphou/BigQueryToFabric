# Known limitations

- **Live adapters exist for BigQuery, Dataflow, Dataproc, Dataform, and Composer, and none of them
  has been validated against an authorized GCP sandbox.** The adapter code exists and is verified
  offline against committed API payloads; the live verification does not exist. `create_rest_client`,
  the `gcp` extra, and live permission coverage remain unverified.
- The Dataflow, Dataproc, Dataform, and Composer adapters are **live, credentialed, read-only
  Google API calls**, not offline payload normalization. They are opt-in per CLI flag, and all four
  request `https://www.googleapis.com/auth/cloud-platform.read-only`, which is broader than the
  BigQuery path's `https://www.googleapis.com/auth/bigquery.readonly`. Have a security
  administrator approve that scope before first use.
- Component discovery records provenance explicitly as `inventory`, `bigquery_api`, `dataflow_api`,
  `composer_api`, `dataproc_api`, `dataform_api`, or `external_payload`. These values identify the
  input origin only; they are not freshness, trusted-execution, or effective-access proof.
- Dataflow and Dataproc live discovery are regional through repeatable flags; they do not scan all
  regions. Dataflow records job identity, state, type, streaming classification, labels, timestamps,
  and present environment/pipeline metadata only. `portable` and `connector_compatible` remain
  absent unless directly supplied by the API payload, so assessment reports missing evidence rather
  than inferring compatibility.
- Composer connection extraction and Dataflow job-ID deduplication are validated deterministic
  offline contracts. They do not establish live API parity, permission coverage, metadata freshness,
  or an authorized live-GCP sandbox result.
- An associated GCP component supplied through `external_payload` without required adapter
  evidence produces FAIL `EXTERNAL_PAYLOAD_INCOMPLETE_ADAPTER` and propagates a manual-review
  requirement to downstream components. This signals incomplete scope or evidence, not a missing
  dependency. It is an offline assessment rule and does not call cloud APIs, prove freshness or
  access, or implement a live adapter.
- BigQuery discovery supports metadata for jobs, scheduled queries, connections, and dataset
  `access` entries. Dataset ACLs are emitted only as redacted canonical `security_policy`
  records, each labeled `evidence_scope: dataset_access_entry`, with principal identities
  pseudonymized as stable non-reversible `principal:<12 hex>` values. They document declared
  dataset access and do not prove effective access after project, organization, group, or inherited
  IAM evaluation. Assessment treats this as incomplete security evidence and emits FAIL
  `SECURITY_EFFECTIVE_ACCESS_REVIEW`; discovery does not query IAM APIs or prove those effective
  permissions. Pseudonymization protects the artifact; it does not make the evidence an
  effective-access calculation.
- Generated Fabric artifacts are skeletons and are not production deployment payloads. An artifact
  `valid: true` flag now comes from a real structural validator rather than a generator assertion,
  but a structurally valid skeleton is still a skeleton.
- **`SparkConverter` applies only mechanical Spark rewrites.** When the inventory carries the job
  body in `properties.code`, it rewrites mapped GCS paths to OneLake, replaces `SparkSession` and
  `SparkContext` construction with the Fabric-provided session, and redacts credentials; Scala gets
  the same mechanical rewrites but still requires manual translation to Python. Business logic is
  carried over, not verified. Without `properties.code` the notebook is a scaffold that loads
  `INPUT_PATH` and says the original job must be reimplemented.
- The `converter/` package is reachable production code: `sql_assessment` delegates to
  `SqlConverter`, so SQL conversion has a single implementation. Converted Spark and SQL remain
  review-only; neither is equivalence-tested.
- Generated operational pipeline activities use deterministic retry and secure-policy defaults,
  but retry behavior still requires validation against the official Fabric/ADF schema and runtime;
  the defaults do not establish deployment readiness or execution parity.
- Generated numeric `Count of <column>` measures use DAX `COUNT` to count populated values, but
  generated semantic models still require validation against the official Fabric semantic-model
  schema/API; the artifact-generation fidelity fix does not establish deployment readiness or
  runtime parity.
- Credential scanning is implemented for persisted `.json`, `.ipynb`, `.sql`, and `.kql` text.
  `validate_artifact` uses `CredentialScanner` and reports only the finding type, never the
  matched secret value; `validate_directory` applies the scan recursively. Discovery also
  classifies `service_account` and `serviceaccount` keys as sensitive, redacting
  `service_account_path` before canonical inventory persistence. The artifact-wide contract was
  validated with `python -m pytest tests/test_artifact_validation.py tests/test_security.py`, which
  passes in CI. Pattern scanning is heuristic and is not a substitute for official Fabric
  schema validation, deployment validation, or a complete secret-management audit.
- GoogleSQL is parsed and classified with a SQL AST; generated translations remain review-only.
- BQML, JavaScript UDFs, dynamic SQL, and complex scripts require redesign.
- Discovery does not extract project or organization IAM bindings, connection IAM policies,
  BigQuery Data Policies or policy tags, distinct row access policy resources, or permissions for
  external GCP services. Policy tags, row access policies, authorized views, and cross-project
  access therefore require manual security review.
- Partitioning and clustering recommendations are not assumed to be behaviorally equivalent.
- `manual_review_reasons` make known assessment constraints explicit in dry-run evidence only.
  They do not prove remediation, parity, effective access, or deployment readiness.
- Generated `Findings` are review evidence for migration planning. They do not prove remediation,
  security parity, effective access, or deployment readiness.
- Parity comparisons consume supplied evidence only. No source or Fabric query is executed, so a
  `passed` check means the supplied source and target evidence agree — it does not establish runtime
  or data parity. A declared `status` in an inventory is always recomputed and never trusted.
- Generated Warehouse view bodies are converted GoogleSQL → T-SQL offline. Result-set equivalence
  between the source view and the converted T-SQL is unproven. When conversion fails or the result
  uses unsupported Fabric Warehouse constructs, the body is omitted and the artifact is marked
  invalid rather than emitting an unverified translation.
- Generated pipeline connection references and managed-identity bindings are review placeholders.
  They are not resolved against a Fabric workspace and grant no access.
- `connection-transcode.json` is a dry-run mapping record, not a Fabric connection definition or
  connectivity test. Identity bindings, access rights, and official connector configuration remain
  open for authoring and review.
- The self-healing loop is deliberately narrow and opt-in. It repairs only misplaced pipeline
  `triggers` and exact duplicate schema fields; conflicting duplicate definitions and unsupported
  artifact defects remain manual review. With `max_passes > 1` a value still changing on the last
  pass is `manual_review` (`repair did not converge`). It does not execute workloads, call cloud
  services, or rewrite persisted inventory files, and a repaired artifact is still re-reviewed.
- The agent feedback loop is a process contract, not an enforced control. The review ledger
  (`artifacts/review-ledger.jsonl`) is local, git-ignored, and unsigned, and nothing blocks a
  handoff that was never recorded. CI runs `review_ledger.py verify` on verdicts committed under
  `.github/reviews/`, but committing a verdict is not yet required. `review_ledger.py` checks
  verdicts with a stdlib subset of JSON Schema that covers only the keywords the verdict schema
  uses.
- Agent ownership is enforced for `src/` only. Documentation, scripts, and skills are checked for
  existence and single ownership, not for complete coverage.
- The parity kit only generates SQL; it never runs a query or connects to either platform.
  - **Checks covered:** `row_count`, `null_distribution`, and `aggregate` (integer and decimal
    columns only; floats are excluded because summation order changes their totals).
  - **Checks not covered:** `schema`, `checksum`, `sample`, and `sql_result` are not generated.
  - **Target names:** target table names are proposals and must match what was actually deployed.
  - **What `passed` means:** ingested results show that the two supplied result sets agree. They
    are not proof of end-to-end data parity.
- Review-board decisions in `wave-decisions.json` are trusted as authored. The file is hashed but
  not signed, and the tool does not verify who the reviewer is.
- The SQL corpus (`tests/fixtures/sql_corpus.json`) protects one case per documented construct.
  Detection of semantic risk is pattern-based, so a construct written in an unusual form can still
  be under-rated.
- Spark conversion flags dynamic SQL when `spark.sql()` receives anything other than a plain
  string literal. Queries built elsewhere and passed through helper functions are not traced.
- `import-export` reads only the fields each GCP list method returns. Subscriptions, triggers, data
  formats, Looker measures and joins, Vertex models and endpoints, and Spanner replication stay
  `EVIDENCE_MISSING` until they are supplied from a verified source.
- `security-proposals.json` names a candidate Fabric control for each policy.
  - **RLS templates:** the Warehouse row-level-security template is deny-all (`WHERE 1 = 0`) and
    disabled (`STATE = OFF`). The source filter must be translated by hand.
  - **Unmapped policy types:** they are `unsupported`.
  - **Effective access:** effective access and permission parity stay `not_recorded`.
- LookML-to-DAX conversion covers only `count`, `sum`, `average`, `min`, `max`, and
  `count_distinct` over a single column. Filtered measures, SQL expressions, and other types are
  listed as unconverted. Data Science scaffolds suggest a starting library only, and
  `modelParity` is always `not_run`.
- `inventory_drift` compares two inventories structurally. It is groundwork for the P14 sandbox run
  and has not been run against live discovery output.
- The dbt target is offline and review-only.
  - **Jinja:** only `ref`, `source`, and `config` are translated. Blocks such as
    `{% if is_incremental() %}`, and any other macro, leave the model body commented out with
    `jinja_macro_review`.
  - **Tests:** only `unique` and `not_null` become dbt tests; other tests and Dataform assertions
    are listed for manual translation.
  - **Incremental models:** incremental models without a `unique_key` are flagged.
  - **Profile:** `profiles.yml` is a placeholder reference, and a Fabric dbt job sets the
    connection in its own UI.
  - **Preview:** the Fabric dbt job is a preview feature (`DBT_JOB_PREVIEW`).
- The T-SQL converter rewrites GoogleSQL `DATE(x)` to `CAST(x AS DATE)` and ordinal `GROUP BY n`
  to the projected expression. Other GoogleSQL functions that sqlglot passes through unchanged may
  still be invalid in Fabric Warehouse, so structural validation is not proof of executability.
- Workflows, Pub/Sub, GCS, Looker, Vertex AI, Dataplex, Cloud SQL, and Spanner have **no** live
  adapter and are limited to offline payload normalization and assessment. Conversion and deployment
  remain outside every adapter's behavior.
