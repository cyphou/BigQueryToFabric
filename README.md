<p align="center">
	<img src="docs/images/data-migration-tool-logo.png" alt="Data migration from BigQuery to Microsoft Fabric" width="560"/>
</p>

<h1 align="center">✨ BigQuery → Microsoft Fabric</h1>

<p align="center">
	<strong>Evidence-based assessment and migration planning for the GCP data platform.</strong><br/>
	Inventory workloads, select the right Fabric targets, order migration waves, and generate
	reviewable dry-run artifacts before any cloud change occurs.
</p>

<p align="center">
	<img alt="Version 0.1.0" src="https://img.shields.io/badge/version-0.1.0-146C94?style=for-the-badge"/>
	<img alt="Python 3.12+" src="https://img.shields.io/badge/python-3.12+-3776AB?style=for-the-badge&amp;logo=python&amp;logoColor=white"/>
	<img alt="Tests 30 passing" src="https://img.shields.io/badge/tests-30%20passing-1F883D?style=for-the-badge"/>
	<img alt="Coverage 93.2 percent" src="https://img.shields.io/badge/coverage-93.2%25-12A594?style=for-the-badge"/>
	<img alt="Dry run by default" src="https://img.shields.io/badge/cloud-dry--run%20default-F2C811?style=for-the-badge"/>
	<a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-2EA44F?style=for-the-badge"/></a>
</p>

| | Verified baseline |
|---|---|
| 🔍 **Discovery** | Read-only BigQuery metadata · credentials redacted by construction |
| 🧭 **Assessment** | 25 GCP/BigQuery source types · normalized readiness score · explainable findings |
| 🏗️ **Fabric routing** | 15 target roles · Lakehouse/Notebook preference · workload overrides |
| 🧪 **Quality** | 30 tests passed · 93.2% coverage · Ruff and Pyright clean |
| 🤖 **Agent model** | 10 specialist agents · exclusive ownership and documentation handoff validated |
| 🔒 **Safety** | Deterministic output · no credentials · no cloud mutation |

> [!IMPORTANT]
> BQToFabric `0.1.0` is an **assessment and dry-run generation toolkit**. Discovery is read-only and
> has not yet been verified against a live GCP estate, and nothing is deployed to Fabric. Generated
> definitions are review artifacts, not production deployment payloads.

## ⚡ Quick Start

```powershell
python -m pip install -e ".[dev]"

# Optional: discover a live project read-only (requires the gcp extra and ADC)
python -m pip install -e ".[gcp]"
bqtofabric discover my-gcp-project --output artifacts/inventory.json

# Validate and inspect an inventory
bqtofabric validate tests/fixtures/gcp_ecosystem_project.json
bqtofabric inventory tests/fixtures/gcp_ecosystem_project.json

# Assess, plan, and generate the dry-run migration package
bqtofabric assess tests/fixtures/gcp_ecosystem_project.json
bqtofabric plan tests/fixtures/gcp_ecosystem_project.json --output artifacts/gcp-plan
bqtofabric generate tests/fixtures/gcp_ecosystem_project.json --output artifacts/gcp-project
bqtofabric manifest-verify artifacts/gcp-project/fabric/deployment-manifest.json
bqtofabric deployment-check artifacts/gcp-project/fabric
```

The generated package contains:

- `assessment.json` — score, evidence, SQL analysis, findings, and portfolio summaries.
- `component-mapping.csv` — primary/supporting targets, compatibility, rationale, and actions.
- `migration-plan.md` and `migration-plan.json` — dependency-ordered migration waves.
- `lineage.mmd` — Mermaid dependency graph.
- `fabric/` — dry-run Warehouse SQL, Fabric notebook, pipeline, and orchestration manifests.
- `fabric/target-manifest.json` — every target entry with `processingStage`, `wave`, and source `dependencies` for deterministic full-chain dry-run review. Stages are `ingestion`, `storage`, `transformation`, `orchestration`, `consumption`, `governance`, `integration`, or `operational` for known source kinds.
- `fabric/deployment-manifest.json` — immutable dry-run payload with SHA-256 integrity hash.
- `fabric/artifact-validation.json` — offline structural validation results.
- `fabric/deployment-manifest.json` is checked by `deployment-check`; readiness never performs apply.

## Assess A Live GCP Project

Live discovery is read-only BigQuery metadata discovery. It creates a local canonical inventory;
all assessment, mapping, planning, generation, and deployment-readiness steps remain offline and
non-destructive.

1. Install the optional GCP dependencies and enable the **BigQuery API**, **BigQuery Data Transfer
	API**, and **BigQuery Connection API** for the project.
2. Sign in using user Application Default Credentials. Do not use or store service-account JSON.

	```powershell
	python -m pip install -e ".[gcp]"
	gcloud auth application-default login
	```

3. Have a security administrator grant the user least-privilege read access for the required APIs
	and resources, including job-history visibility where required.
4. Run the local workflow:

	```powershell
	bqtofabric discover <project-id> --output artifacts/<project-id>/inventory.json
	bqtofabric validate artifacts/<project-id>/inventory.json
	bqtofabric inventory artifacts/<project-id>/inventory.json
	bqtofabric assess artifacts/<project-id>/inventory.json
	bqtofabric map artifacts/<project-id>/inventory.json
	bqtofabric plan artifacts/<project-id>/inventory.json --output artifacts/<project-id>/plan
	bqtofabric generate artifacts/<project-id>/inventory.json --output artifacts/<project-id>/project
	bqtofabric deployment-check artifacts/<project-id>/project/fabric
	```

	Discovery uses Application Default Credentials (ADC) with
	`https://www.googleapis.com/auth/bigquery.readonly`. It reads datasets; tables, views, materialized
	views, and external tables; routines and procedures; BQML models; jobs; scheduled-query transfer
	configurations; connections; and dataset `access` entries. Dataset access entries are redacted and
	represented as canonical `security_policy` records. See Google's [ADC guidance](https://docs.cloud.google.com/docs/authentication/provide-credentials-adc)
	and [BigQuery access-control reference](https://docs.cloud.google.com/bigquery/docs/access-control).

	Discovery exit code `3` means ADC, BigQuery API enablement, or required IAM visibility is missing.
	Re-authenticate with `gcloud auth application-default login`, confirm the three required APIs are
	enabled, and have a security administrator review the least-privilege guidance in the
	[migration runbook](docs/MIGRATION_RUNBOOK.md). Provider response bodies are never printed.

External GCP services -- Dataflow, Composer, Dataproc, Dataform, Pub/Sub, GCS, Looker, Vertex AI,
Dataplex, Cloud SQL, and Spanner -- support offline normalization and assessment only. They do not
have live discovery adapters.

<details>
<summary><b>📦 Installation and development setup</b></summary>

```powershell
git clone <repository-url>
cd BQToFabric
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
```

**Requirements:** Python 3.12+ and `sqlglot` for structured GoogleSQL analysis.

</details>

## 🎯 What It Assesses

<table>
<tr>
<td width="50%">

### 🗄️ Data and SQL
BigQuery tables, views, materialized views, external tables, routines, procedures,
scheduled queries, GoogleSQL scripts, nested `ARRAY`/`STRUCT`/`JSON`, partitioning,
clustering, GCS sources, Cloud SQL, and Spanner.

</td>
<td width="50%">

### ⚙️ Engineering and orchestration
Spark, Dataproc, Apache Beam/Dataflow, Dataform, Composer/Airflow, GCP Workflows,
connections, dependencies, retries, schedules, state, and migration waves.

</td>
</tr>
<tr>
<td>

### ⚡ Streaming and events
Pub/Sub and streaming jobs mapped to Eventstream/Eventhouse when low-latency event
analytics dominates, with optional Lakehouse retention for medallion processing.

</td>
<td>

### 📊 BI, ML, and governance
Looker, BQML, Vertex AI, Dataplex, policy tags, row access policies, Purview,
semantic models, Power BI reports, Data Science, and explicit manual-review boundaries.

</td>
</tr>
</table>

## 🧭 Target Strategy

The requested default is **Lakehouse + Notebook**, but preferences never override stronger
technical evidence.

| Source evidence | Recommended Fabric design |
|---|---|
| Spark, nested data, medallion, ML features | **Lakehouse + Notebook** |
| Structured BI, T-SQL, DML, multi-table transactions | **Warehouse** |
| Pub/Sub, Beam streaming, high-granularity events | **Eventstream + Eventhouse** |
| Existing Composer DAG with reusable operators | **Fabric Airflow Job** + Lakehouse/Notebook |
| Cloud SQL or transactional application data | **SQL Database** + analytical replication |
| BQML or Vertex AI lifecycle | **Fabric Data Science** + Lakehouse/Notebook |
| Looker semantic layer | **Semantic model + Power BI report** |
| Dataplex and classifications | **Purview + Fabric domains** |

Set advisory preferences in the canonical inventory:

```json
{
	"metadata": {
		"preferences": {
			"data_target": "lakehouse",
			"compute_target": "notebook",
			"preserve_airflow": true
		}
	}
}
```

## 🏗️ How It Works

```mermaid
flowchart LR
		GCP["☁️ GCP estate\nBigQuery · Spark · Airflow · Pub/Sub"] --> INV["🔍 INVENTORY\nCanonical JSON"]
		INV --> ASSESS["🧭 ASSESS\nCompatibility · SQL AST · risk"]
		ASSESS --> PLAN["🗺️ PLAN\nTargets · lineage · waves"]
		PLAN --> GEN["✨ GENERATE\nDeterministic dry-run package"]
		GEN --> LH["🗄️ Lakehouse"]
		GEN --> NB["📓 Notebook"]
		GEN --> WH["🏢 Warehouse"]
		GEN --> RTI["⚡ Eventhouse"]
		GEN --> AF["🌬️ Airflow Job"]

		style GCP fill:#4285F4,color:#fff,stroke:#3367D6
		style INV fill:#17324D,color:#fff,stroke:#17324D
		style ASSESS fill:#146C94,color:#fff,stroke:#146C94
		style PLAN fill:#12A594,color:#fff,stroke:#0B7F72
		style GEN fill:#F2C811,color:#17212B,stroke:#C9A600
```

Every mapping is classified as `direct`, `transform`, `redesign`, or `unsupported` and
includes a rationale plus concrete follow-up actions. GoogleSQL is parsed as an AST with
`sqlglot`; ETL logic is never translated to DAX.

### Streaming Processing-Chain Guardrail

- **Expected:** A `DATAFLOW_JOB` with `properties.streaming: true` requires review of every
	transitive downstream canonical consumer.
- **Implemented:** Assessment emits `WARN` finding `STREAMING_DOWNSTREAM_REVIEW` on each
	downstream object, requiring deduplication, idempotency, and out-of-order delivery review.
	The planner marks those consumers `manual_review`; the streaming job remains
	`redesign`/`manual_review`.
- **Validated:** `python -m pytest tests/test_assessment.py -q` (`8 passed`).
- **Open:** This uses static inventory dependencies only. It does not process live streams,
	validate data, or deploy Fabric artifacts.

## 🧰 CLI

| Command | Purpose |
|---|---|
| `bqtofabric discover` | Inventory a live BigQuery project read-only, with credentials redacted |
| `bqtofabric inventory` | Summarize datasets and components by source type |
| `bqtofabric validate` | Validate the canonical inventory contract |
| `bqtofabric assess` | Produce readiness, target, type, SQL, and risk evidence |
| `bqtofabric map` | Print component-level Fabric decisions |
| `bqtofabric plan` | Generate dependency-ordered migration waves |
| `bqtofabric generate` | Produce the complete dry-run assessment package |

## ✅ Verified Baseline

Validated locally on Python 3.13 against the committed synthetic GCP portfolio:

```powershell
python scripts/validate_agents.py
python -m ruff check src tests scripts
python -m pyright
python -m pytest --cov=bqtofabric --cov-report=term-missing --cov-fail-under=80
```

- `30 passed`
- `93.25%` package coverage
- `0` Ruff findings
- `0` Pyright errors or warnings
- `10` agents and `1` skill contract validated
- Reference portfolio: `19` components, Lakehouse primary, hybrid architecture, Airflow retained

## 🗺️ Roadmap

The next development tracks are live GCP discovery, deeper SQL/Spark conversion, production-grade
Fabric artifacts, parity validation, and opt-in deployment. See the full
[development roadmap](docs/ROADMAP.md) for priorities, deliverables, and release gates.

## 📚 Documentation

| Guide | Purpose |
|---|---|
| [Architecture](docs/ARCHITECTURE.md) | Pipeline and ownership boundaries |
| [GCP component assessment](docs/GCP_COMPONENT_ASSESSMENT.md) | Supported source families and evidence |
| [Mapping reference](docs/MAPPING_REFERENCE.md) | BigQuery/GCP to Fabric mapping rules |
| [Target decision guide](docs/TARGET_DECISION_GUIDE.md) | Lakehouse, Warehouse, Eventhouse, and hybrid choices |
| [Migration runbook](docs/MIGRATION_RUNBOOK.md) | Operational assessment workflow |
| [Known limitations](docs/KNOWN_LIMITATIONS.md) | Explicit V1 boundaries |
| [Security](docs/SECURITY.md) | Credentials, identities, and governance constraints |
| [Agents](docs/AGENTS.md) | Specialist-agent ownership model |

## Public Reference Examples

Tests use synthetic, sanitized fixtures for deterministic offline testing. The links below are
public upstream examples to study; no external source code is vendored. Public links may evolve,
and the test suite remains independent of them.

| Source family | Public examples |
|---|---|
| BigQuery, scheduled queries, routines, materialized views, external tables, and BigQuery ML | [Google Cloud BigQuery samples](https://github.com/GoogleCloudPlatform/python-docs-samples/tree/main/bigquery) |
| Dataflow / Beam | [Google Cloud Dataflow sample applications](https://github.com/GoogleCloudPlatform/dataflow-sample-applications); [Apache Beam examples](https://github.com/apache/beam/tree/master/examples) |
| Dataproc / Spark | [Google Cloud Dataproc samples](https://github.com/GoogleCloudPlatform/python-docs-samples/tree/main/dataproc) |
| Dataform | [Google Cloud Dataform samples](https://github.com/GoogleCloudPlatform/dataform-samples) |
| Composer / Airflow | [Google Cloud Composer samples](https://github.com/GoogleCloudPlatform/python-docs-samples/tree/main/composer) |
| Workflows | [Google Cloud Workflows samples](https://github.com/GoogleCloudPlatform/python-docs-samples/tree/main/workflows) |
| Pub/Sub | [Google Cloud Pub/Sub samples](https://github.com/GoogleCloudPlatform/python-docs-samples/tree/main/pubsub) |
| GCS | [Google Cloud Storage samples](https://github.com/GoogleCloudPlatform/python-docs-samples/tree/main/storage) |
| Looker | [Looker SDK for Python](https://github.com/looker-open-source/looker-sdk-python) |
| Vertex AI | [Google Cloud Vertex AI samples](https://github.com/GoogleCloudPlatform/vertex-ai-samples) |
| Dataplex | [Google Cloud Dataplex samples](https://github.com/GoogleCloudPlatform/python-docs-samples/tree/main/dataplex) |
| Cloud SQL | [Google Cloud SQL samples](https://github.com/GoogleCloudPlatform/python-docs-samples/tree/main/cloud-sql) |
| Spanner | [Google Cloud Spanner samples](https://github.com/GoogleCloudPlatform/python-docs-samples/tree/main/spanner) |

## 🔒 Safety Principles

- No credentials, service-account keys, tokens, tenant IDs, or secrets in inventories or output.
- No cloud mutation in the default path.
- Native Fabric BigQuery connectors are preferred over proprietary data movers.
- Unsupported security semantics fail closed and require manual review.
- Generated output is deterministic and suitable for source control and review.

## 📄 License

BQToFabric is released under the [MIT License](LICENSE). The license permits use,
modification, distribution, and resale, subject to its notice and warranty terms.

---

<p align="center">
	<strong>Assess first. Preserve intent. Move each workload to the Fabric service that fits it.</strong>
</p>

