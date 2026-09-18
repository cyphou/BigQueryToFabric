# Security

- Never store service-account JSON, OAuth tokens, secrets, tenant IDs, or connection passwords.
- Keep discovery read-only and scope GCP/Fabric identities to the least privilege required.
- Treat policy tags, row access policies, authorized views, and cross-project access as migration
  blockers until target permissions and RLS are validated.
- Generated output must contain logical references, never secret values.
- Cloud deployment is outside V1 and must require explicit confirmation and an audit trail.
