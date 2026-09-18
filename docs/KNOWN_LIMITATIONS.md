# Known limitations

- Discovery reads BigQuery metadata read-only and is verified offline against committed API
  payloads; it has not been run against a live GCP estate, so `create_rest_client` and the `gcp`
  extra remain unverified.
- Discovery does not yet cover BigQuery jobs, scheduled queries, connections, or access policies,
  so a discovered inventory understates orchestration and security work.
- Generated Fabric artifacts are skeletons and are not production deployment payloads.
- GoogleSQL is parsed and classified with a SQL AST; generated translations remain review-only.
- BQML, JavaScript UDFs, dynamic SQL, and complex scripts require redesign.
- Policy tags, authorized views, and row access policies require manual security review.
- Partitioning and clustering recommendations are not assumed to be behaviorally equivalent.
- Dataform, Composer, Beam, Pub/Sub, Looker, Vertex AI, Dataplex, Cloud SQL, and Spanner are
	assessed and planned, but their live extraction, conversion, and deployment remain outside V1.
