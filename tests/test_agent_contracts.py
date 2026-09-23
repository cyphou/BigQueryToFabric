from pathlib import Path

from scripts.validate_agents import AGENT_DIR, REQUIRED_COMMANDS, validate

ROOT = Path(__file__).resolve().parents[1]


def test_agent_and_skill_contracts_are_valid() -> None:
    assert validate() == []


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
