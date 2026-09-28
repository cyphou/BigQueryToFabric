from pathlib import Path

import pytest

from scripts.validate_agents import AGENT_DIR, REQUIRED_COMMANDS, validate

ROOT = Path(__file__).resolve().parents[1]


def test_agent_and_skill_contracts_are_valid() -> None:
    assert validate() == []


def test_ownership_coverage_rejects_drift() -> None:
    """Owned paths that don't exist and unowned modules were both shipped once."""
    from scripts.validate_agents import _validate_ownership_coverage

    owned = {
        "src/bqtofabric/": "Orchestrator",
        "src/bqtofabric/cli.py": "Architect",
        "src/bqtofabric/generators/": "FabricGenerator",
    }
    errors = _validate_ownership_coverage(owned)

    assert "src/bqtofabric/generators/: owned by FabricGenerator but does not exist" in errors
    assert "src/bqtofabric/cli.py: owned by Architect and Orchestrator" in errors
    assert "src/bqtofabric/repair.py: no owning agent" in _validate_ownership_coverage(
        {"src/bqtofabric/cli.py": "Orchestrator"}
    )


def test_skill_documents_the_public_cli_surface() -> None:
    assert REQUIRED_COMMANDS == {
        "discover",
        "inventory",
        "assess",
        "map",
        "plan",
        "generate",
        "validate",
    }


def test_supervision_agents_exist() -> None:
    """Direction and method review must be separable from implementation."""
    names = {
        path.name for path in AGENT_DIR.glob("*.agent.md")
    }

    assert "tech-lead.agent.md" in names
    assert "preceptor.agent.md" in names


def test_supervision_agents_do_not_own_implementation_files() -> None:
    """A supervisor that edits src/ has taken someone else's work."""
    for filename in ("tech-lead.agent.md", "preceptor.agent.md"):
        text = (AGENT_DIR / filename).read_text(encoding="utf-8")
        owned = [
            line.strip().strip("-").strip().strip("`")
            for line in text.splitlines()
            if line.strip().startswith("- `")
        ]

        assert owned, f"{filename} declares no ownership"
        assert not any(path.startswith("src/") for path in owned), (
            f"{filename} owns implementation files: {owned}"
        )


def test_escalation_paths_are_documented() -> None:
    """An agent that cannot escalate will work around a blocker instead."""
    instructions = (ROOT / ".github" / "agent-instructions.md").read_text(encoding="utf-8")

    assert "Preceptor" in instructions
    assert "TechLead" in instructions
    assert "Escalation" in instructions


def test_verdict_schema_bounds_the_feedback_loop() -> None:
    """The loop must terminate, and acceptance must be derived from gates, not asserted."""
    import json

    schema = json.loads(
        (ROOT / ".github" / "review-verdict.schema.json").read_text(encoding="utf-8")
    )
    rules = {json.dumps(rule["if"], sort_keys=True): rule["then"] for rule in schema["allOf"]}

    round_three = rules[json.dumps({"properties": {"round": {"const": 3}}}, sort_keys=True)]
    assert round_three["properties"]["verdict"]["enum"] == ["accepted", "escalate"]
    assert schema["properties"]["round"]["maximum"] == 3

    accepted = rules[json.dumps({"properties": {"verdict": {"const": "accepted"}}}, sort_keys=True)]
    gates = accepted["properties"]["gates"]["properties"]
    assert set(gates) == set(schema["$defs"]["gates"]["required"])
    assert all(gate == {"const": "passed"} for gate in gates.values())

    escalate = rules[json.dumps({"properties": {"verdict": {"const": "escalate"}}}, sort_keys=True)]
    assert escalate == {"required": ["escalate_to"]}


def test_repair_summary_in_verdict_mirrors_repair_result() -> None:
    import json
    from dataclasses import fields

    from bqtofabric.repair import RepairResult

    schema = json.loads(
        (ROOT / ".github" / "review-verdict.schema.json").read_text(encoding="utf-8")
    )
    repair = schema["$defs"]["repair"]["properties"]

    assert set(repair) <= {field.name for field in fields(RepairResult)}
    assert set(repair["status"]["enum"]) == {"passed", "repaired", "manual_review"}


def test_validator_rejects_a_verdict_schema_without_a_return_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from scripts import validate_agents

    broken = tmp_path / "review-verdict.schema.json"
    broken.write_text(
        json.dumps({"properties": {"verdict": {"enum": ["accepted"]}}}), encoding="utf-8"
    )
    monkeypatch.setattr(validate_agents, "VERDICT_SCHEMA", broken)

    errors = validate_agents.validate()

    assert any("verdicts" in error for error in errors)


def test_deep_dive_report_is_current() -> None:
    """The committed report is generated; nothing otherwise notices when it goes stale."""
    import json
    import re

    from scripts.refresh_deep_dive_report import REPORT, build_objects

    embedded = re.search(
        r"const OBJECTS = \[\n(.*?)\n\];", REPORT.read_text(encoding="utf-8"), re.DOTALL
    )
    assert embedded is not None, "OBJECTS block not found in the report"

    published = json.loads(f"[{embedded.group(1)}]")

    assert published == build_objects(), (
        "docs/assessment-object-deep-dive.html is stale; "
        "run python scripts/refresh_deep_dive_report.py"
    )
