"""Validate custom-agent and skill discovery contracts using only the standard library."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / ".github" / "agents"
SKILL = ROOT / ".github" / "skills" / "bigquery-to-fabric" / "SKILL.md"
REQUIRED_COMMANDS = {"discover", "inventory", "assess", "map", "plan", "generate", "validate"}


def validate() -> list[str]:
    errors: list[str] = []
    names: set[str] = set()
    owned: dict[str, str] = {}
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
        for owned_path in re.findall(r"^- `([^`]+)`$", text, re.MULTILINE):
            if owned_path in owned:
                errors.append(f"{owned_path}: owned by {owned[owned_path]} and {name}")
            owned[owned_path] = name

    skill_text = SKILL.read_text(encoding="utf-8")
    if "name: bigquery-to-fabric" not in skill_text:
        errors.append("Skill name does not match its directory")
    missing = sorted(command for command in REQUIRED_COMMANDS if f"bqtofabric {command}" not in skill_text)
    if missing:
        errors.append(f"Skill omits commands: {', '.join(missing)}")
    return errors


if __name__ == "__main__":
    problems = validate()
    if problems:
        raise SystemExit("\n".join(problems))
    print(f"Validated {len(list(AGENT_DIR.glob('*.agent.md')))} agents and 1 skill")
