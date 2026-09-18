from bqtofabric.assessment import run_assessment
from bqtofabric.deployment_manifest import build_manifest
from bqtofabric.inventory import JsonInventoryProvider
from bqtofabric.planner import build_plan


def test_deployment_manifest_is_deterministic() -> None:
    inventory = JsonInventoryProvider("tests/fixtures/mixed_project.json").load()
    assessment = run_assessment(inventory)
    plan = build_plan(inventory, assessment)

    first = build_manifest(inventory, assessment, plan)
    second = build_manifest(inventory, assessment, plan)

    assert first == second
    assert len(first["sha256"]) == 64
    assert first["payload"]["projectId"] == "retail-analytics"