import json

from bqtofabric.gcp_components import normalize_external_components
from bqtofabric.models import ObjectKind


def test_external_gcp_components_are_normalized_and_redacted() -> None:
    resources = [{
        "kind": "dataflow_job",
        "name": "streaming",
        "dependencies": ["demo.pubsub.events"],
        "labels": {"team": "data", "api_key": "secret"},
        "properties": {"streaming": True, "access_token": "Bearer hidden"},
    }]

    components = normalize_external_components("demo", resources)

    assert len(components) == 1
    assert components[0].kind is ObjectKind.DATAFLOW_JOB
    assert components[0].dependencies == ("demo.pubsub.events",)
    assert "secret" not in json.dumps(components[0].to_dict() if hasattr(components[0], "to_dict") else components[0].properties)


def test_unknown_external_component_is_ignored() -> None:
    assert normalize_external_components("demo", [{"kind": "unknown", "name": "x"}]) == ()