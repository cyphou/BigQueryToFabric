# Known limitations

- Discovery reads BigQuery metadata and explicitly requested regional Dataflow jobs read-only and
  is verified offline against committed API payloads; it has not been run against a live GCP estate,
  so `create_rest_client`, the `gcp` extra, and live permission coverage remain unverified.
- Component discovery records provenance explicitly as `inventory`, `bigquery_api`, `dataflow_api`, or
  `external_payload`. These values identify the input origin only; they are not freshness,
  trusted-execution, or effective-access proof.
- Dataflow live discovery is opt-in and regional through repeatable `--dataflow-region` arguments;
  it does not scan all regions. It records job identity, state, type, streaming classification,
  labels, timestamps, and present environment/pipeline metadata only. `portable` and
  `connector_compatible` remain absent unless directly supplied by the API payload, so assessment
  reports missing evidence rather than inferring compatibility.
- An associated GCP component supplied through `external_payload` without required adapter
  evidence produces FAIL `EXTERNAL_PAYLOAD_INCOMPLETE_ADAPTER` and propagates a manual-review
  requirement to downstream components. This signals incomplete scope or evidence, not a missing
  dependency. It is an offline assessment rule and does not call cloud APIs, prove freshness or
  access, or implement a live adapter.
- BigQuery discovery supports metadata for jobs, scheduled queries, connections, and dataset
  `access` entries. Dataset ACLs are emitted only as redacted canonical `security_policy`
  records, each labeled `evidence_scope: dataset_access_entry`; they document declared dataset
  access and do not prove effective access after project, organization, group, or inherited IAM
  evaluation. Assessment treats this as incomplete security evidence and emits FAIL
  `SECURITY_EFFECTIVE_ACCESS_REVIEW`; discovery does not query IAM APIs or prove those effective
  permissions.
- Generated Fabric artifacts are skeletons and are not production deployment payloads.
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
- Composer, Dataproc, Dataform, Workflows, Pub/Sub, GCS, Looker, Vertex AI, Dataplex, Cloud SQL,
  and Spanner are limited to offline payload normalization and assessment. Dataflow has a live
  adapter, but only for explicitly requested regions; all-region discovery, conversion, and
  deployment remain outside this adapter's behavior.
