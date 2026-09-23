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
- **`SparkConverter` performs no real Spark code transformation.** It produces review records with
  GCS path mapping, credential redaction, and language/runtime evidence. Generated notebooks do
  **not** carry over the source Dataproc or Spark logic; the transformation body must be written by
  hand. Treat a generated notebook as a scaffold with metadata, not as a converted job.
- The `converter/` package is now reachable production code: `sql_assessment` delegates to
  `SqlConverter`, so SQL conversion has a single implementation. This removes a dead-code path; it
  does not improve Spark conversion, which remains unimplemented as described above.
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
- Workflows, Pub/Sub, GCS, Looker, Vertex AI, Dataplex, Cloud SQL, and Spanner have **no** live
  adapter and are limited to offline payload normalization and assessment. Conversion and deployment
  remain outside every adapter's behavior.
