# Known limitations

- Discovery reads BigQuery metadata read-only and is verified offline against committed API
  payloads; it has not been run against a live GCP estate, so `create_rest_client` and the `gcp`
  extra remain unverified.
- BigQuery discovery supports metadata for jobs, scheduled queries, connections, and dataset
  `access` entries. Dataset ACLs are emitted only as redacted canonical `security_policy`
  records; they document declared dataset access and do not prove effective access after project,
  organization, group, or inherited IAM evaluation.
- Generated Fabric artifacts are skeletons and are not production deployment payloads.
- GoogleSQL is parsed and classified with a SQL AST; generated translations remain review-only.
- BQML, JavaScript UDFs, dynamic SQL, and complex scripts require redesign.
- Discovery does not extract project or organization IAM bindings, connection IAM policies,
  BigQuery Data Policies or policy tags, distinct row access policy resources, or permissions for
  external GCP services. Policy tags, row access policies, authorized views, and cross-project
  access therefore require manual security review.
- Partitioning and clustering recommendations are not assumed to be behaviorally equivalent.
- Dataflow, Composer, Dataproc, Dataform, Workflows, Pub/Sub, GCS, Looker, Vertex AI, Dataplex,
  Cloud SQL, and Spanner can be assessed and planned from inventory data, but their live adapters,
  extraction, conversion, and deployment remain outside V1.
