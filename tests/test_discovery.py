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
