"""Validate custom-agent and skill discovery contracts using only the standard library."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / ".github" / "agents"
SKILL_DIR = ROOT / ".github" / "skills"
PRIMARY_SKILL = "bigquery-to-fabric"
REQUIRED_COMMANDS = {"discover", "inventory", "assess", "map", "plan", "generate", "validate"}
DOCUMENTATION_AGENT = "Documentation"


def validate() -> list[str]:
    errors: list[str] = []
    names: set[str] = set()
    owned: dict[str, str] = {}
    ownership_sections = 0
    for path in sorted(AGENT_DIR.glob("*.agent.md")):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            errors.append(f"{path.name}: missing YAML frontmatter")
            continue
        name_match = re.search(r'^name: "([^"]+)"$', text, re.MULTILINE)
        if not name_match:
            errors.append(f"{path.name}: missing quoted name")
            continue
        name = name_match.group(1)
        if name in names:
            errors.append(f"Duplicate agent name: {name}")
        names.add(name)
        if not re.search(r'^description: ".+"$', text, re.MULTILINE):
            errors.append(f"{path.name}: missing quoted description")
        if not re.search(r"^tools: \[.+\]$", text, re.MULTILINE):
            errors.append(f"{path.name}: missing tools")
        if "## Owned files" not in text:
            errors.append(f"{path.name}: missing ownership section")
        else:
            ownership_sections += 1
        for owned_path in re.findall(r"^- `([^`]+)`$", text, re.MULTILINE):
            if owned_path in owned:
                errors.append(f"{owned_path}: owned by {owned[owned_path]} and {name}")
            owned[owned_path] = name

    if DOCUMENTATION_AGENT not in names:
        errors.append(f"Missing required agent: {DOCUMENTATION_AGENT}")
    if ownership_sections != len(list(AGENT_DIR.glob("*.agent.md"))):
        errors.append("Every agent must declare an ownership section")

    errors.extend(_validate_skills())
    errors.extend(_validate_roster(names))
    return errors


def _validate_roster(names: set[str]) -> list[str]:
    """The documented roster must match the agents that actually exist."""
    roster_path = ROOT / "docs" / "AGENTS.md"
    if not roster_path.exists():
        return ["docs/AGENTS.md is missing"]

    text = roster_path.read_text(encoding="utf-8")
    documented = {
        match.group(1).strip()
        for match in re.finditer(r"^\| ([A-Za-z]+) \| .+ \|$", text, re.MULTILINE)
    }
    documented.discard("Agent")
    documented.discard("Escalate to")

    errors: list[str] = []
    for missing in sorted(names - documented):
        errors.append(f"docs/AGENTS.md does not document agent: {missing}")
    for extra in sorted(documented - names):
        errors.append(f"docs/AGENTS.md documents an agent that does not exist: {extra}")
    return errors


def _validate_skills() -> list[str]:
    errors: list[str] = []
    skills = sorted(SKILL_DIR.glob("*/SKILL.md"))
    if not skills:
        return ["No skills found"]

    names = {path.parent.name for path in skills}
    if PRIMARY_SKILL not in names:
        errors.append(f"Missing required skill: {PRIMARY_SKILL}")

    for path in skills:
        directory = path.parent.name
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            errors.append(f"{directory}: missing YAML frontmatter")
            continue
        if not re.search(rf"^name: {re.escape(directory)}$", text, re.MULTILINE):
            errors.append(f"{directory}: skill name does not match its directory")
        if not re.search(r"^description: >-$", text, re.MULTILINE):
            errors.append(f"{directory}: missing folded description")
        for link in re.findall(r"\]\((?!https?:)([^)#]+)\)", text):
            if not (path.parent / link).resolve().exists():
                errors.append(f"{directory}: broken reference {link}")

    primary = SKILL_DIR / PRIMARY_SKILL / "SKILL.md"
    if primary.exists():
        primary_text = primary.read_text(encoding="utf-8")
        missing = sorted(
            command
            for command in REQUIRED_COMMANDS
            if f"bqtofabric {command}" not in primary_text
        )
        if missing:
            errors.append(f"Skill omits commands: {', '.join(missing)}")
    return errors


if __name__ == "__main__":
    problems = validate()
    if problems:
        raise SystemExit("\n".join(problems))
    agent_count = len(list(AGENT_DIR.glob("*.agent.md")))
    skill_count = len(list(SKILL_DIR.glob("*/SKILL.md")))
    print(f"Validated {agent_count} agents and {skill_count} skills")
