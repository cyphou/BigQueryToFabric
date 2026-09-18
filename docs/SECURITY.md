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
- Component discovery records provenance explicitly as `inventory`, `bigquery_api`, or
  `external_payload`. Provenance identifies the input origin only; it must not be interpreted as
  freshness, trusted execution, or proof of effective access.
- Associated GCP services are limited to offline payload normalization and assessment unless a
  live adapter is explicitly implemented. Their payloads do not establish live service state,
  trusted execution, or effective access.
  as incomplete and emits FAIL `SECURITY_EFFECTIVE_ACCESS_REVIEW`. It does not query IAM APIs or
  prove effective project, organization, group, or inherited permissions. Project/org IAM bindings
  and connection IAM policies are not extracted.
- BigQuery Data Policies, policy tags, and distinct row access policy resources are not currently
  called or extracted. A future adapter may require Data Policy Viewer access and a security
  review before collecting that metadata.
- Treat policy tags, row access policies, authorized views, and cross-project access as migration
  blockers until target permissions and RLS are validated.
- Generated output must contain logical references, never secret values.
- Preserve redaction boundaries: inventories and generated artifacts may include only logical,
  non-secret references and redacted security-policy details. For BigQuery IAM and dataset access
  concepts, see [BigQuery access control](https://docs.cloud.google.com/bigquery/docs/access-control).
- Cloud deployment is outside V1 and must require explicit confirmation and an audit trail.
