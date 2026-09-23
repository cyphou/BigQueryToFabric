"""Each BigQuery connection backend must name a concrete Fabric recreation path."""

import pytest

from bqtofabric.mapping import Compatibility, FabricTarget, map_component
from bqtofabric.models import BigQueryObject, ObjectKind


def _connection(**properties: object) -> BigQueryObject:
    return BigQueryObject(
        source_id="demo.connections.c",
        name="c",
        kind=ObjectKind.CONNECTION,
        discovered_from="bigquery_api",
        properties=dict(properties),
    )


@pytest.mark.parametrize(
    ("properties", "target", "compatibility"),
    [
        (
            {"connection_type": "CLOUD_SQL", "database_engine": "POSTGRES"},
            FabricTarget.DATA_PIPELINE,
            Compatibility.TRANSFORM,
        ),
        (
            {"connection_type": "AWS"},
            FabricTarget.ONELAKE_SHORTCUT,
            Compatibility.TRANSFORM,
        ),
        (
            {"connection_type": "AZURE"},
            FabricTarget.DATA_PIPELINE,
            Compatibility.TRANSFORM,
        ),
        (
            {"connection_type": "CLOUD_RESOURCE"},
            FabricTarget.ONELAKE_SHORTCUT,
            Compatibility.TRANSFORM,
        ),
        (
            {"connection_type": "SPARK"},
            FabricTarget.LAKEHOUSE,
            Compatibility.TRANSFORM,
        ),
        (
            {"connection_type": "CLOUD_SPANNER"},
            FabricTarget.MANUAL,
            Compatibility.REDESIGN,
        ),
    ],
)
def test_connection_backends_map_to_named_fabric_targets(
    properties: dict, target: FabricTarget, compatibility: Compatibility
) -> None:
    decision = map_component(_connection(**properties))

    assert decision.target is target
    assert decision.compatibility is compatibility
    assert decision.actions


def test_cloud_sql_names_the_matching_fabric_connector() -> None:
    """A reviewer needs the connector name, not a generic instruction."""
    engines = {"POSTGRES": "PostgreSQL", "MYSQL": "MySQL", "SQL_SERVER": "SQL Server"}

    for engine, connector in engines.items():
        decision = map_component(
            _connection(connection_type="CLOUD_SQL", database_engine=engine)
        )

        assert connector in decision.rationale
        assert any(connector in action for action in decision.actions)


def test_unrecorded_cloud_sql_engine_is_not_guessed() -> None:
    """Without the engine there is no connector to name, so it must not be invented."""
    decision = map_component(_connection(connection_type="CLOUD_SQL"))

    assert decision.target is FabricTarget.MANUAL
    assert decision.compatibility is Compatibility.REDESIGN


def test_unknown_backend_is_not_given_a_fabric_recommendation() -> None:
    decision = map_component(_connection(connection_type="UNKNOWN"))

    assert decision.target is FabricTarget.MANUAL
    assert decision.compatibility is Compatibility.REDESIGN


def test_no_connection_mapping_suggests_copying_a_secret() -> None:
    """Migration guidance must never tell a reader to move credential material."""
    for connection_type in (
        "CLOUD_SQL",
        "CLOUD_SPANNER",
        "AWS",
        "AZURE",
        "CLOUD_RESOURCE",
        "SPARK",
        "UNKNOWN",
    ):
        decision = map_component(
            _connection(connection_type=connection_type, database_engine="POSTGRES")
        )
        guidance = " ".join((decision.rationale, *decision.actions)).lower()

        assert "copy the password" not in guidance
        assert "reuse the credential" not in guidance
        if connection_type != "SPARK":
            assert "never copy secret values" in guidance
