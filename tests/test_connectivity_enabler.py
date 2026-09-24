import json

from bqtofabric.connectivity import transcode_connection
from bqtofabric.models import BigQueryObject, ObjectKind


def _connection(**properties: object) -> BigQueryObject:
    return BigQueryObject(
        source_id="demo.connections.crm",
        name="crm",
        kind=ObjectKind.CONNECTION,
        properties=dict(properties),
    )


def test_transcode_connection_is_deterministic_and_secret_free() -> None:
    item = _connection(
        connection_type="CLOUD_SQL",
        database_engine="POSTGRES",
        connection_string="postgresql://user:secret@db.example/crm",
    )

    first = transcode_connection(item)
    second = transcode_connection(item)

    assert first == second
    assert first.status == "manual_review"
    assert first.reference_name == "gcp-connection-cd5dc3b60059"
    assert first.redaction_status == "blocked"
    output = json.dumps(first.to_dict()).lower()
    assert "user:secret@" not in output
    assert "postgresql://" not in output


def test_transcode_connection_maps_known_backend_without_credentials() -> None:
    result = transcode_connection(
        _connection(connection_type="CLOUD_SQL", database_engine="POSTGRES")
    )

    assert result.status == "ready_for_review"
    assert result.target_type == "PostgreSQL"
    assert result.compatibility == "transform"
    assert result.findings == ()


def test_transcode_connection_keeps_unknown_backend_manual() -> None:
    result = transcode_connection(_connection(connection_type="NEW_BACKEND"))

    assert result.status == "manual_review"
    assert result.compatibility == "redesign"
    assert "unknown" in " ".join(result.findings).lower()