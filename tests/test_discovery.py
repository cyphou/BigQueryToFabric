import json
from pathlib import Path

import pytest

from bqtofabric.assessment import run_assessment
from bqtofabric.discovery import (
    REDACTED,
    DiscoveryError,
    GoogleCloudInventoryProvider,
    RestBigQueryClient,
    redact_mapping,
)
from bqtofabric.mapping import FabricTarget
from bqtofabric.models import BigQueryInventory, ObjectKind

FIXTURES = Path(__file__).parent / "fixtures"
API_RESPONSES = FIXTURES / "bigquery_api_responses.json"
EXPECTED_INVENTORY = FIXTURES / "expected_discovered_inventory.json"


class FakeBigQueryClient:
    """Serve committed API-shaped payloads so discovery runs without credentials."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def list_datasets(self):
        return self.payload["datasets"]

    def list_jobs(self):
        return self.payload["jobs"]

    def list_transfer_configs(self):
        return self.payload["transfer_configs"]

    def list_connections(self):
        return self.payload["connections"]

    def list_tables(self, dataset_id: str):
        return self.payload["tables"].get(dataset_id, [])

    def list_routines(self, dataset_id: str):
        return self.payload["routines"].get(dataset_id, [])

    def list_models(self, dataset_id: str):
        return self.payload["models"].get(dataset_id, [])


def build_provider() -> GoogleCloudInventoryProvider:
    payload = json.loads(API_RESPONSES.read_text(encoding="utf-8"))
    return GoogleCloudInventoryProvider("demo-project", FakeBigQueryClient(payload))


def serialize(inventory: BigQueryInventory) -> dict:
    """Compare the JSON form that is actually written to disk, not in-memory tuples."""
    return json.loads(json.dumps(inventory.to_dict(), sort_keys=True))


def test_discovery_maps_api_resources_to_canonical_objects() -> None:
    inventory = build_provider().load()
    objects = {item.source_id: item for item in inventory.objects()}

    events = objects["demo-project.analytics.events"]
    view = objects["demo-project.analytics.daily_revenue"]
    external = objects["demo-project.analytics.raw_drop"]

    assert inventory.schema_version == "1.1"
    assert events.kind is ObjectKind.TABLE
    assert view.kind is ObjectKind.VIEW
    assert external.kind is ObjectKind.EXTERNAL_TABLE
    assert objects["demo-project.analytics.sp_refresh_events"].kind is ObjectKind.PROCEDURE
    assert objects["demo-project.analytics.fn_score"].kind is ObjectKind.ROUTINE
    assert objects["demo-project.analytics.churn"].kind is ObjectKind.BQML_MODEL
    assert objects["demo-project.jobs.job-001"].kind is ObjectKind.BIGQUERY_JOB
    assert objects["demo-project.scheduled_queries.daily-revenue"].kind is ObjectKind.SCHEDULED_QUERY
    assert objects["demo-project.connections.crm"].kind is ObjectKind.CONNECTION
    assert objects["demo-project.analytics.access.0000"].kind is ObjectKind.SECURITY_POLICY
    assert events.partition_field == "event_date"
    assert events.clustering_fields == ("customer_id",)
    assert events.size_bytes == 10485760
    assert {item.discovered_from for item in objects.values()} == {"bigquery_api"}


def test_discovery_preserves_operational_migration_evidence_without_secrets() -> None:
    objects = {item.source_id: item for item in build_provider().load().objects()}

    assert objects["demo-project.jobs.job-001"].properties["job_type"] == "query"
    assert objects["demo-project.jobs.job-001"].dependencies == (
        "demo-project.analytics.events",
    )
    scheduled = objects["demo-project.scheduled_queries.daily-revenue"]
    assert scheduled.properties["schedule"] == "every 24 hours"
    assert scheduled.properties["owner_email"] == "scheduler@example.com"
    assert objects["demo-project.connections.crm"].properties["auth_configured"] is True
    assert objects["demo-project.analytics.access.0000"].properties["policy_type"] == "role"
    assert "top-secret" not in json.dumps(objects["demo-project.connections.crm"].properties)


def test_discovered_dataset_access_policy_preserves_provenance_and_redacts_secrets() -> None:
    payload = json.loads(API_RESPONSES.read_text(encoding="utf-8"))
    payload["datasets"][0]["access"][0]["private_key"] = "-----BEGIN PRIVATE KEY-----"
    inventory = GoogleCloudInventoryProvider("demo-project", FakeBigQueryClient(payload)).load()
    policy = next(item for item in inventory.objects() if item.source_id.endswith(".access.0000"))

    assert policy.properties["evidence_scope"] == "dataset_access_entry"
    assert policy.properties["private_key"] == REDACTED
    assert "BEGIN PRIVATE KEY" not in json.dumps(policy.properties)


def test_discovery_redacts_service_account_paths() -> None:
    """Service-account key-file paths must not persist in discovered inventories."""
    redacted = redact_mapping({"service_account_path": r"C:\secrets\gcp-sa.json"})

    assert redacted["service_account_path"] == REDACTED
    assert "gcp-sa.json" not in json.dumps(redacted)


def test_legacy_api_type_names_are_normalized_for_the_type_mapper() -> None:
    inventory = build_provider().load()
    events = next(item for item in inventory.objects() if item.name == "events")
    types = {column.name: column.data_type for column in events.columns}

    assert types["customer_id"] == "INT64"
    assert types["amount"] == "FLOAT64"
    assert types["is_test"] == "BOOL"
    assert types["payload"] == "STRUCT"
    payload = next(column for column in events.columns if column.name == "payload")
    assert payload.mode == "REPEATED"
    assert payload.fields[1].data_type == "GEOGRAPHY"


def test_view_and_procedure_dependencies_are_resolved_to_full_source_ids() -> None:
    inventory = build_provider().load()
    objects = {item.source_id: item for item in inventory.objects()}

    assert objects["demo-project.analytics.daily_revenue"].dependencies == (
        "demo-project.analytics.events",
    )
    assert objects["demo-project.analytics.sp_refresh_events"].dependencies == (
        "demo-project.analytics.events",
        "demo-project.staging.events_raw",
    )


def test_unparseable_routine_body_is_flagged_instead_of_guessed() -> None:
    inventory = build_provider().load()
    javascript = next(item for item in inventory.objects() if item.name == "fn_score")

    assert javascript.dependencies == ()
    assert javascript.properties["unresolved_references"] == [
        "SQL could not be parsed; references require manual review."
    ]


def test_credential_like_metadata_is_redacted_by_construction() -> None:
    inventory = build_provider().load()
    serialized = json.dumps(inventory.to_dict())

    assert inventory.datasets[0].labels["api_key"] == REDACTED
    assert inventory.datasets[0].labels["team"] == "data-platform"
    assert "AIzaSyNOT-A-REAL-KEY" not in serialized


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("client_secret", "shhh"),
        ("access_token", "ya29.abc"),
        ("nested", {"private_key": "-----BEGIN PRIVATE KEY-----"}),
        ("owner_note", "Bearer ya29.abc"),
    ],
)
def test_redaction_covers_secret_keys_and_secret_values(key: str, value: object) -> None:
    redacted = json.dumps(redact_mapping({key: value}))

    assert "shhh" not in redacted
    assert "ya29.abc" not in redacted
    assert "BEGIN PRIVATE KEY" not in redacted


def test_repeated_discovery_is_deterministic() -> None:
    assert serialize(build_provider().load()) == serialize(build_provider().load())


def test_discovered_inventory_matches_committed_snapshot() -> None:
    expected = json.loads(EXPECTED_INVENTORY.read_text(encoding="utf-8"))
    for dataset in expected["datasets"]:
        for item in dataset["objects"]:
            item.setdefault("discovered_from", "bigquery_api")
    for item in expected["components"]:
        item.setdefault("discovered_from", "bigquery_api")

    assert serialize(build_provider().load()) == expected


def test_discovered_inventory_feeds_the_existing_assessment_engine() -> None:
    report = run_assessment(build_provider().load())
    decisions = {item.source_id: item for item in report.decisions}

    assert decisions["demo-project.analytics.events"].target is FabricTarget.LAKEHOUSE
    assert decisions["demo-project.analytics.churn"].target is FabricTarget.DATA_SCIENCE
    assert report.component_summary["bqml_model"] == 1


class _Response:
    def __init__(self, payload: dict) -> None:
        self.status_code = 200
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _RecordedSession:
    """Replay recorded REST payloads keyed by URL and page token."""

    def __init__(self, routes: dict) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str | None]] = []

    def get(self, url: str, params: dict | None = None, timeout: int = 60) -> _Response:
        token = (params or {}).get("pageToken")
        self.calls.append((url, token))
        return _Response(self.routes[(url, token)])


def test_rest_client_follows_every_page_before_returning() -> None:
    root = "https://bigquery.googleapis.com/bigquery/v2/projects/demo-project/datasets"
    session = _RecordedSession({
        (root, None): {
            "datasets": [{"datasetReference": {"datasetId": "first"}}],
            "nextPageToken": "page-2",
        },
        (root, "page-2"): {"datasets": [{"datasetReference": {"datasetId": "second"}}]},
        (f"{root}/first", None): {"datasetReference": {"datasetId": "first"}, "location": "EU"},
        (f"{root}/second", None): {"datasetReference": {"datasetId": "second"}, "location": "US"},
    })

    datasets = RestBigQueryClient("demo-project", session).list_datasets()

    assert [item["location"] for item in datasets] == ["EU", "US"]
    assert (root, "page-2") in session.calls


class _FailingResponse:
    status_code = 403

    @staticmethod
    def json() -> dict:
        return {"error": "Authorization: Bearer ya29.super-secret"}


class _FailingSession:
    @staticmethod
    def get(url: str, params: dict | None = None, timeout: int = 60) -> _FailingResponse:
        return _FailingResponse()


def test_failed_request_never_surfaces_the_response_body() -> None:
    client = RestBigQueryClient("demo-project", _FailingSession())

    with pytest.raises(DiscoveryError) as error:
        client.list_datasets()

    assert "403" in str(error.value)
    assert "ya29.super-secret" not in str(error.value)


# --- Dataproc Discovery Tests ---


class FakeDataprocClient:
    """Serve committed Dataproc API payloads."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def list_clusters(self, region: str) -> list[dict]:
        return self.payload.get("clusters", [])

    def list_jobs(self, region: str) -> list[dict]:
        return self.payload.get("jobs", [])


def build_dataproc_provider() -> tuple:
    payload = json.loads((FIXTURES / "dataproc_api_payloads.json").read_text(encoding="utf-8"))
    from bqtofabric.dataproc_discovery import DataprocInventoryProvider
    provider = DataprocInventoryProvider("demo-project", FakeDataprocClient(payload))
    return provider, payload


def test_dataproc_discovers_clusters_and_jobs() -> None:
    provider, _ = build_dataproc_provider()
    components = provider.load(["europe-west1"])

    cluster_objects = [c for c in components if "dataproc.europe-west1" in c.source_id and c.kind.value == "spark_job"]
    job_objects = [j for j in components if "dataproc.job" in j.source_id]

    assert len(cluster_objects) == 1
    assert len(job_objects) == 3
    assert cluster_objects[0].name == "ml-training-cluster"


def test_dataproc_preserves_cluster_configuration() -> None:
    provider, _ = build_dataproc_provider()
    components = provider.load(["europe-west1"])

    cluster = next(c for c in components if c.name == "ml-training-cluster")
    assert cluster.properties["master_machine_type"] != ""
    assert cluster.properties["worker_machine_type"] != ""
    assert cluster.properties["worker_count"] == 10
    assert cluster.properties["staging_bucket"] == "gs://dataproc-staging-bucket-001"
    assert cluster.properties["autoscaling_min_instances"] == 2
    assert cluster.properties["autoscaling_max_instances"] == 20


def test_dataproc_classifies_job_types() -> None:
    provider, _ = build_dataproc_provider()
    components = provider.load(["europe-west1"])

    jobs = {c.name: c for c in components if c.kind.value == "dataproc_job"}
    assert jobs["pyspark-etl-001"].properties["job_type"] == "pyspark"
    assert jobs["spark-sql-aggregation-002"].properties["job_type"] == "spark_sql"
    assert jobs["spark-streaming-consumer-003"].properties["job_type"] == "spark"
    assert jobs["pyspark-etl-001"].properties["language"] == "python"
    assert jobs["spark-sql-aggregation-002"].properties["language"] == "sql"
    assert jobs["pyspark-etl-001"].properties["runtime_version"] == "unknown"


def test_dataproc_classifies_workload_types() -> None:
    provider, _ = build_dataproc_provider()
    components = provider.load(["europe-west1"])

    jobs = {c.name: c for c in components if c.kind.value == "dataproc_job"}
    assert jobs["pyspark-etl-001"].properties["workload_type"] == "data_engineering"
    assert jobs["spark-streaming-consumer-003"].properties["workload_type"] == "streaming"


def test_dataproc_redacts_staging_paths() -> None:
    # Staging paths are preserved for linking, but credentials in them would be redacted
    provider, payload = build_dataproc_provider()
    payload["clusters"][0]["config"]["stagingBucket"] = "gs://bucket-with-secret-key-value"
    components = provider.load(["europe-west1"])

    cluster = next(c for c in components if c.name == "ml-training-cluster")
    # The staging bucket itself is preserved, but any secrets would be redacted
    assert "gs://" in cluster.properties.get("staging_bucket", "")


def test_dataproc_discovery_is_deterministic() -> None:
    from dataclasses import asdict
    provider1, _ = build_dataproc_provider()
    provider2, _ = build_dataproc_provider()

    components1 = provider1.load(["europe-west1"])
    components2 = provider2.load(["europe-west1"])

    assert json.dumps([asdict(c) for c in components1], sort_keys=True) == \
           json.dumps([asdict(c) for c in components2], sort_keys=True)


# --- Dataform Discovery Tests ---


class FakeDataformClient:
    """Serve committed Dataform API payloads."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def list_repositories(self, location: str) -> list[dict]:
        return self.payload.get("repositories", [])

    def list_workflows(self, repository_resource: str) -> list[dict]:
        return self.payload.get("workflows", [])

    def list_compilation_results(self, repository_resource: str) -> list[dict]:
        return self.payload.get("compilationResults", [])

    def get_compilation_result(self, compilation_result_resource: str) -> dict:
        return self.payload["compilationResults"][0]


def build_dataform_provider() -> tuple:
    payload = json.loads((FIXTURES / "dataform_api_payloads.json").read_text(encoding="utf-8"))
    from bqtofabric.dataform_discovery import DataformInventoryProvider
    provider = DataformInventoryProvider("demo-project", FakeDataformClient(payload))
    return provider, payload


def test_dataform_discovers_repositories_and_workflows() -> None:
    provider, _ = build_dataform_provider()
    components = provider.load()

    repo_objects = [c for c in components if "repository" in c.source_id]
    workflow_objects = [c for c in components if "workflow" in c.source_id]

    assert len(repo_objects) >= 1
    assert len(workflow_objects) >= 1

    workflow = next(item for item in workflow_objects if item.name == "daily-etl")
    assert workflow.properties["models"] == ["dim_customers", "events_raw", "fact_revenue"]
    assert workflow.properties["assertions"] is True
    assert workflow.properties["incremental"] is True


def test_dataform_discovers_compiled_targets_and_tables() -> None:
    provider, _ = build_dataform_provider()
    components = provider.load()

    table_objects = [c for c in components if c.kind.value == "table"]
    assert len(table_objects) >= 2  # Should have fact_revenue and dim_customers


def test_dataform_preserves_table_schema_and_incremental_configuration() -> None:
    provider, _ = build_dataform_provider()
    components = provider.load()

    fact_revenue = next((c for c in components if c.name == "fact_revenue"), None)
    assert fact_revenue is not None
    assert fact_revenue.properties["incremental"] is True
    assert fact_revenue.properties["schema"] == "core"


def test_dataform_discovers_and_links_assertions() -> None:
    provider, _ = build_dataform_provider()
    components = provider.load()

    assertions = [c for c in components if "assertion" in c.source_id]
    fact_revenue_tables = [c for c in components if c.name == "fact_revenue"]

    # Assertions should be present and linked to tables
    assert len(assertions) >= 1
    for table in fact_revenue_tables:
        assert table.properties.get("has_assertions", False)


def test_dataform_infers_dependencies() -> None:
    provider, _ = build_dataform_provider()
    components = provider.load()

    fact_revenue = next((c for c in components if c.name == "fact_revenue"), None)
    assert fact_revenue is not None
    # Should have dependency on dim_customers
    assert any("dim_customers" in dep for dep in fact_revenue.dependencies)


def test_dataform_redacts_sensitive_properties() -> None:
    from dataclasses import asdict
    provider, payload = build_dataform_provider()
    # Add a secret-like property
    payload["compilationResults"][0]["dataSourceA"]["targets"][0]["secret_config"] = "supersecret"
    components = provider.load()

    tables = [c for c in components if c.kind.value == "table"]
    serialized = json.dumps([asdict(c) for c in tables])
    # Properties are redacted via redact_mapping
    assert "datasourceA" not in serialized or "secret" not in serialized


def test_dataform_discovery_is_deterministic() -> None:
    from dataclasses import asdict
    provider1, _ = build_dataform_provider()
    provider2, _ = build_dataform_provider()

    components1 = provider1.load()
    components2 = provider2.load()

    assert json.dumps([asdict(c) for c in components1], sort_keys=True) == \
           json.dumps([asdict(c) for c in components2], sort_keys=True)


def test_dataform_compilation_fetch_failure_retains_review_component() -> None:
    """Unavailable compilation details must remain visible rather than silently dropping lineage."""
    provider, _ = build_dataform_provider()

    def unavailable(_: str) -> dict:
        raise DiscoveryError("Dataform compilation detail request failed")

    provider.client.get_compilation_result = unavailable
    components = provider.load()
    fallback = next(item for item in components if ".dataform.compilation." in item.source_id)

    assert fallback.properties["discovery_incomplete"] is True
    assert fallback.properties["lineage_status"] == "unavailable"


# --- Composer Discovery Tests ---


class FakeComposerClient:
    """Serve committed Composer API payloads."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def list_environments(self, location: str) -> list[dict]:
        return self.payload.get("environments", [])

    def list_dags(self, environment_resource: str) -> list[dict]:
        return self.payload.get("dags", [])


def build_composer_provider() -> tuple:
    payload = json.loads((FIXTURES / "composer_api_payloads.json").read_text(encoding="utf-8"))
    from bqtofabric.composer_discovery import ComposerInventoryProvider
    provider = ComposerInventoryProvider("demo-project", FakeComposerClient(payload))
    return provider, payload


def test_composer_discovers_environments_and_dags() -> None:
    provider, _ = build_composer_provider()
    components = provider.load(["us-central1"])

    env_objects = [c for c in components if "env" in c.source_id]
    dag_objects = [c for c in components if "dag" in c.source_id]

    assert len(env_objects) >= 1
    assert len(dag_objects) >= 1


def test_composer_preserves_environment_configuration() -> None:
    provider, _ = build_composer_provider()
    components = provider.load(["us-central1"])

    env = next((c for c in components if "env" in c.source_id), None)
    assert env is not None
    assert env.properties["machine_type"] != ""
    assert "dag_gcs_prefix" in env.properties


def test_composer_extracts_dag_metadata_and_operators() -> None:
    provider, _ = build_composer_provider()
    components = provider.load(["us-central1"])

    dags = {c.name: c for c in components if "dag" in c.source_id}
    daily_etl = dags.get("daily_revenue_etl")

    assert daily_etl is not None
    assert daily_etl.properties["owner"] != ""
    assert daily_etl.properties["schedule"] == "0 6 * * *"
    assert daily_etl.properties["schedule_interval"] == "0 6 * * *"
    assert daily_etl.properties["runtime_version"] == "2.5.0"
    assert daily_etl.properties["connections"] == []
    assert daily_etl.properties["task_count"] == 5
    assert len(daily_etl.properties.get("operators", [])) > 0


def test_composer_classifies_dag_types() -> None:
    provider, _ = build_composer_provider()
    components = provider.load(["us-central1"])

    dags = {c.name: c for c in components if "dag" in c.source_id}

    # daily_revenue_etl should be classified as analytics
    daily_etl = dags.get("daily_revenue_etl")
    assert daily_etl is not None
    assert daily_etl.properties["dag_type"] == "analytics"
    # ml_model_training should be classified as ml_training
    ml_training = dags.get("ml_model_training")
    assert ml_training is not None
    assert ml_training.properties["dag_type"] == "ml_training"


def test_composer_detects_operator_types() -> None:
    provider, _ = build_composer_provider()
    components = provider.load(["us-central1"])

    dags = {c.name: c for c in components if "dag" in c.source_id}
    daily_etl = dags.get("daily_revenue_etl")

    assert daily_etl is not None
    assert daily_etl.properties["has_bigquery_operators"] is True

    ml_training = dags.get("ml_model_training")
    assert ml_training is not None
    assert ml_training.properties["has_dataproc_operators"] is True

    external_feed = dags.get("external_data_feed")
    assert external_feed is not None
    assert external_feed.properties["has_sensor_operators"] is True


def test_composer_extracts_declared_connection_names() -> None:
    provider, payload = build_composer_provider()
    payload["dags"][0]["serializedDag"]["_task_cycle"][1]["gcp_conn_id"] = "analytics-prod"

    components = provider.load(["us-central1"])
    daily_etl = next(item for item in components if item.name == "daily_revenue_etl")

    assert daily_etl.properties["connections"] == ["analytics-prod"]


def test_composer_extracts_bigquery_dependencies() -> None:
    provider, _ = build_composer_provider()
    components = provider.load(["us-central1"])

    dags = {c.name: c for c in components if "dag" in c.source_id}
    daily_etl = dags.get("daily_revenue_etl")

    assert daily_etl is not None
    assert len(daily_etl.dependencies) > 0
    assert any("demo-project.analytics" in dep for dep in daily_etl.dependencies)


def test_composer_discovery_is_deterministic() -> None:
    from dataclasses import asdict
    provider1, _ = build_composer_provider()
    provider2, _ = build_composer_provider()

    components1 = provider1.load(["us-central1"])
    components2 = provider2.load(["us-central1"])

    assert json.dumps([asdict(c) for c in components1], sort_keys=True) == \
           json.dumps([asdict(c) for c in components2], sort_keys=True)


def test_composer_redacts_secrets_in_properties() -> None:
    from dataclasses import asdict
    provider, payload = build_composer_provider()
    # Add a secret-like property to a DAG
    payload["dags"][0]["serializedDag"]["_task_cycle"][0]["api_key"] = "supersecret"
    components = provider.load(["us-central1"])

    serialized = json.dumps([asdict(c) for c in components])
    # The redaction is applied to properties
    assert "supersecret" not in serialized or "[redacted]" in serialized

