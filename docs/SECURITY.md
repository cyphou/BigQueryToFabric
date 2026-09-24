# Security

- Never store service-account JSON, OAuth tokens, secrets, tenant IDs, or connection passwords.
- Authenticate with Application Default Credentials (ADC); service-account JSON is explicitly
  prohibited. See [Provide credentials to ADC](https://docs.cloud.google.com/docs/authentication/provide-credentials-adc).
- Keep discovery read-only and scope GCP/Fabric identities to the least privilege required. For
  core dataset and table metadata, use dataset-level access where possible and
  `roles/bigquery.metadataViewer`. Use the project-level `roles/bigquery.resourceViewer` only
  when estate-wide job history requiring `jobs.listAll` is
  explicitly approved. When connection metadata is in scope, grant
  `roles/bigquery.connectionUser` for `connections.get` and `connections.list`. Do not grant
  BigQuery admin or other broad administrative roles for discovery.
- The adapter calls BigQuery metadata, BigQuery Data Transfer, and BigQuery Connection APIs using
  the BigQuery read-only scope. It extracts dataset GET `access` entries as redacted canonical
  `security_policy` records, each labeled `evidence_scope: dataset_access_entry`; these records
  describe dataset ACL declarations, not effective-access proof. Assessment treats this evidence
- Component discovery records provenance explicitly as `inventory`, `bigquery_api`, `dataflow_api`,
  `composer_api`, `dataproc_api`, `dataform_api`, or `external_payload`. Provenance identifies the
  input origin only; it must not be interpreted as
  freshness, trusted execution, or proof of effective access.
- When an associated GCP component originates in `external_payload` without its required adapter
  evidence, assessment emits FAIL `EXTERNAL_PAYLOAD_INCOMPLETE_ADAPTER` and marks downstream
  components for manual review. This identifies incomplete scope or evidence; it does not mean a
  dependency is missing. The check is offline: it does not call cloud APIs, prove freshness or
  access, or implement a live adapter.
- Opt-in read-only live adapters exist for Dataflow, Dataproc, Dataform, and Composer. They make
  real credentialed Google API calls when their CLI flag is supplied, and all four request
  `https://www.googleapis.com/auth/cloud-platform.read-only`, which is broader than the BigQuery
  path's `bigquery.readonly`. A security administrator must review and approve that scope before
  first use. None of the adapters has been validated against an authorized GCP sandbox.
- Workflows, Pub/Sub, GCS, Looker, Vertex AI, Dataplex, Cloud SQL, and Spanner have no live
  adapter and are limited to offline payload normalization and assessment. Their payloads do not
  establish live service state, trusted execution, or effective access.
- Dataset access evidence pseudonymizes principal identities as stable, non-reversible
  `principal:<12 hex>` values. Pseudonymization protects the generated artifact; it does not make
  the evidence an effective-access calculation.
  as incomplete and emits FAIL `SECURITY_EFFECTIVE_ACCESS_REVIEW`. It does not query IAM APIs or
  prove effective project, organization, group, or inherited permissions. Project/org IAM bindings
  and connection IAM policies are not extracted.
- BigQuery Data Policies, policy tags, and distinct row access policy resources are not currently
  called or extracted. A future adapter may require Data Policy Viewer access and a security
  review before collecting that metadata.
- Treat policy tags, row access policies, authorized views, and cross-project access as migration
  blockers until target permissions and RLS are validated.
- Generated output must contain logical references, never secret values.
- `connection-transcode.json` contains only deterministic logical references and review metadata.
  Embedded credential material is detected by type and forces `manual_review`; the original value
  is never copied into the transcode result.
- Expected behavior for persisted SQL and Spark conversion records: source and target text,
  extracted SQL, storage paths, mappings, pattern metadata, and rewrite warnings must not retain
  credentials or service-account key-file paths. `CredentialScanner` also redacts credential values
  in URL query parameters such as `password`, `token`, `secret`, and `api_key`. Spark conversion
  records sanitize all persisted metadata before serialization; warnings for embedded credential
  paths use a fixed security message and do not include the detected raw path.
- This credential-hygiene behavior is validated by `pytest tests/test_security.py
  tests/test_spark_converter.py -v`, including a full serialized-record regression test.
- Discovery classifies `service_account` and `serviceaccount` keys as sensitive and redacts a
  corresponding `service_account_path` before canonical inventory persistence. This behavior is
  validated by `python -m pytest tests/test_discovery.py tests/test_security.py -v` (42 passed).
- Broader secret-scan coverage remains open for generated artifacts and path-bearing fields outside
  the SQL and Spark conversion records covered above; each new persisted surface requires explicit
  review and test coverage before it can be considered protected.
- `manual_review_reasons` make known assessment constraints explicit in dry-run output. They do
  not prove remediation, parity, effective access, or deployment readiness.
- The repair loop is offline and opt-in. It works on defensive copies, records applied rule names,
  and revalidates before reporting `repaired`; it does not perform live healing, modify cloud state,
  or rewrite persisted input.
- Generated `Findings` are review evidence for migration planning. They do not prove remediation,
  security parity, effective access, or deployment readiness.
- Preserve redaction boundaries: inventories and generated artifacts may include only logical,
  non-secret references and redacted security-policy details. For BigQuery IAM and dataset access
  concepts, see [BigQuery access control](https://docs.cloud.google.com/bigquery/docs/access-control).
- Cloud deployment is outside V1 and must require explicit confirmation and an audit trail.
