import json
from pathlib import Path

import pytest
from test_discovery import FakeBigQueryClient

from bqtofabric import cli
from bqtofabric.assessment import run_assessment
from bqtofabric.dataflow_discovery import (
    DataflowInventoryProvider,
    RestDataflowClient,
    merge_dataflow_jobs,
)
from bqtofabric.discovery import REDACTED, DiscoveryError
from bqtofabric.models import BigQueryInventory, ObjectKind


class _Response:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self.payload = payload

    def json(self) -> dict:
        return self.payload


class _Session:
    def __init__(self, routes: dict[tuple[str, str | None], _Response]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str | None]] = []

    def get(self, url: str, params: dict | None = None, timeout: int = 60) -> _Response:
        token = (params or {}).get("pageToken")
        self.calls.append((url, token))
        return self.routes[(url, token)]


def _job(job_id: str, job_type: str, **extra: object) -> dict:
    return {
        "id": job_id,
        "name": f"job-{job_id}",
        "type": job_type,
        "currentState": "JOB_STATE_RUNNING",
        "createTime": "2026-01-02T03:04:05Z",
        "currentStateTime": "2026-01-02T03:05:06Z",
        "labels": {"team": "streaming", "access_token": "do-not-persist"},
        **extra,
    }


class _FakeDataflowClient:
    def __init__(self, jobs: dict[str, list[dict]]) -> None:
        self.jobs = jobs
        self.regions: list[str] = []

    def list_jobs(self, region: str) -> list[dict]:
        self.regions.append(region)
        return self.jobs[region]


def test_dataflow_mapping_preserves_evidence_and_classifies_streaming() -> None:
    jobs = _FakeDataflowClient({
        "europe-west1": [
            _job("batch", "JOB_TYPE_BATCH"),
            _job("stream", "JOB_TYPE_STREAMING", environment={"tempLocation": "gs://bucket"}),
        ]
    })

    objects = DataflowInventoryProvider("demo-project", jobs).load(["europe-west1"])

    assert [item.name for item in objects] == ["job-batch", "job-stream"]
    streaming = objects[1]
    assert streaming.kind is ObjectKind.DATAFLOW_JOB
    assert streaming.discovered_from == "dataflow_api"
    assert streaming.properties["streaming"] is True
    assert objects[0].properties["streaming"] is False
    assert "portable" not in streaming.properties
    assert "connector_compatible" not in streaming.properties
    assert streaming.labels["access_token"] == REDACTED
    assert "do-not-persist" not in json.dumps(streaming.__dict__ if hasattr(streaming, "__dict__") else streaming.properties)


def test_dataflow_payload_evidence_fields_are_preserved_when_present() -> None:
    object_ = DataflowInventoryProvider(
        "demo-project",
        _FakeDataflowClient({
            "us-central1": [_job("portable", "JOB_TYPE_BATCH", portable=True, connector_compatible=False)]
        }),
    ).load(["us-central1"])[0]

    assert object_.properties["portable"] is True
    assert object_.properties["connector_compatible"] is False


def test_assessment_exposes_missing_dataflow_compatibility_evidence() -> None:
    job = DataflowInventoryProvider(
        "demo-project",
        _FakeDataflowClient({"us-central1": [_job("stream", "JOB_TYPE_STREAMING")]}),
    ).load(["us-central1"])[0]
    inventory = BigQueryInventory("demo-project", (), components=(job,))

    report = run_assessment(inventory)

    assert report.evidence_summary[job.source_id]["missing"] == [
        "portable",
        "connector_compatible",
    ]
    assert {finding.code for finding in report.findings} >= {"EVIDENCE_MISSING"}


def test_dataflow_rest_client_paginates_regional_jobs() -> None:
    url = "https://dataflow.googleapis.com/v1b3/projects/demo-project/locations/europe-west1/jobs"
    session = _Session({
        (url, None): _Response(200, {"jobs": [_job("second", "JOB_TYPE_BATCH")], "nextPageToken": "p2"}),
        (url, "p2"): _Response(200, {"jobs": [_job("first", "JOB_TYPE_BATCH")]}),
    })

    jobs = RestDataflowClient("demo-project", session).list_jobs("europe-west1")

    assert [item["id"] for item in jobs] == ["second", "first"]
    assert session.calls[-1] == (url, "p2")


def test_dataflow_output_is_deterministic_and_merge_preserves_bigquery_inventory() -> None:
    client = _FakeDataflowClient({
        "us-central1": [_job("z", "JOB_TYPE_BATCH")],
        "europe-west1": [_job("a", "JOB_TYPE_STREAMING")],
    })
    provider = DataflowInventoryProvider("demo-project", client)
    first = provider.load(["us-central1", "europe-west1"])
    second = provider.load(["europe-west1", "us-central1"])
    inventory = BigQueryInventory("demo-project", (), components=())

    assert [item.source_id for item in first] == [item.source_id for item in second]
    merged = merge_dataflow_jobs(inventory, first)
    assert [item.source_id for item in merged.components] == [
        "demo-project.dataflow.europe-west1.a",
        "demo-project.dataflow.us-central1.z",
    ]


def test_dataflow_duplicate_page_items_are_deduplicated() -> None:
    job = _job("same", "JOB_TYPE_BATCH")
    client = _FakeDataflowClient({"us-central1": [job, dict(job)]})

    objects = DataflowInventoryProvider("demo-project", client).load(["us-central1"])

    assert [item.source_id for item in objects] == ["demo-project.dataflow.us-central1.same"]


class _FailingSession:
    def get(self, url: str, params: dict | None = None, timeout: int = 60) -> _Response:
        return _Response(403, {"error": "Bearer ya29.super-secret"})


def test_dataflow_failure_suppresses_response_body() -> None:
    client = RestDataflowClient("demo-project", _FailingSession())

    with pytest.raises(DiscoveryError) as error:
        client.list_jobs("europe-west1")

    assert "403" in str(error.value)
    assert "ya29.super-secret" not in str(error.value)


def test_cli_merges_dataflow_jobs_only_for_requested_regions(monkeypatch, tmp_path: Path) -> None:
    bigquery_payload = json.loads(
        (Path(__file__).parent / "fixtures" / "bigquery_api_responses.json").read_text()
    )
    dataflow_client = _FakeDataflowClient({
        "europe-west1": [_job("df-1", "JOB_TYPE_STREAMING")],
    })
    monkeypatch.setattr(cli, "create_rest_client", lambda project: FakeBigQueryClient(bigquery_payload))
    monkeypatch.setattr(cli, "create_dataflow_rest_client", lambda project: dataflow_client)
    output = tmp_path / "inventory.json"

    assert cli.main([
        "discover", "demo-project", "--output", str(output), "--dataflow-region", "europe-west1"
    ]) == cli.ExitCode.SUCCESS
    written = json.loads(output.read_text())
    dataflow = next(item for item in written["components"] if item["kind"] == "dataflow_job")
    assert dataflow["discovered_from"] == "dataflow_api"
    assert dataflow_client.regions == ["europe-west1"]


def test_cli_without_dataflow_regions_keeps_bigquery_only_path(monkeypatch, tmp_path: Path) -> None:
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "bigquery_api_responses.json").read_text()
    )
    monkeypatch.setattr(cli, "create_rest_client", lambda project: FakeBigQueryClient(payload))

    def unexpected_dataflow_client(project: str):
        raise AssertionError("Dataflow client must not be created without --dataflow-region")

    monkeypatch.setattr(cli, "create_dataflow_rest_client", unexpected_dataflow_client)
    output = tmp_path / "inventory.json"

    assert cli.main(["discover", "demo-project", "--output", str(output)]) == cli.ExitCode.SUCCESS
    assert all(item["discovered_from"] == "bigquery_api" for item in json.loads(
        output.read_text()
    )["components"])