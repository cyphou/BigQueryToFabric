from scripts.validate_agents import REQUIRED_COMMANDS, validate


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
