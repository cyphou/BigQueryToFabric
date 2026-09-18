# Shared agent rules

1. Read the canonical model and existing tests before changing behavior.
2. Modify only files listed under the agent's ownership section.
3. Preserve immutable BigQuery source identifiers; proposed Fabric names are separate outputs.
4. Treat dynamic SQL, JavaScript UDFs, BQML, policy tags, and cross-project dependencies as
   explicit review items when equivalence cannot be proven.
5. Validate the narrow changed behavior first, then run the full suite.
6. Cloud deployment must remain opt-in and dry-run by default.
