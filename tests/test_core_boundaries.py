"""The assessment core must stay deterministic and free of any model dependency.

An LLM may sit on top of this package — driving the CLI, or supplying inferred
evidence marked with `assisted` provenance — but it must never sit inside it. A
model call in the core would make findings irreproducible, which is the one
property a migration sign-off depends on.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "bqtofabric"

# The only third-party package the deterministic path may import.
CORE_DEPENDENCIES = {"sqlglot"}

# Imported lazily, inside function bodies, and only for opt-in read-only discovery.
OPTIONAL_DEPENDENCIES = {"google", "requests"}

MODEL_PACKAGES = {
    "openai",
    "anthropic",
    "langchain",
    "langchain_core",
    "llama_index",
    "litellm",
    "ollama",
    "transformers",
    "huggingface_hub",
    "sentence_transformers",
    "torch",
    "tensorflow",
    "google.generativeai",
    "vertexai",
    "azure.ai.inference",
    "semantic_kernel",
}


def _iter_modules() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def _imported_modules(path: Path) -> set[str]:
    """Return every absolute module name imported, keeping the full dotted path."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import within the package
                continue
            if node.module:
                modules.add(node.module)
    return modules


def _imported_roots(path: Path) -> set[str]:
    return {module.split(".")[0] for module in _imported_modules(path)}


def _banned_imports(path: Path) -> list[str]:
    """Match on the full dotted path so google.auth is not read as google.generativeai."""
    return sorted(
        module
        for module in _imported_modules(path)
        if any(
            module == package or module.startswith(f"{package}.")
            for package in MODEL_PACKAGES
        )
    )


def test_core_declares_no_model_dependency() -> None:
    """pyproject must not pull a model client into the install."""
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = manifest["project"]["dependencies"]
    names = {
        requirement.split("[")[0].split(">")[0].split("<")[0].split("=")[0].strip().lower()
        for requirement in declared
    }

    assert names == CORE_DEPENDENCIES
    for extra, requirements in manifest["project"].get("optional-dependencies", {}).items():
        for requirement in requirements:
            root = requirement.split("[")[0].split(">")[0].split("<")[0].split("=")[0]
            normalized = root.strip().lower().replace("-", "_")
            assert not any(
                normalized == package or package.startswith(f"{normalized}.")
                for package in MODEL_PACKAGES
            ), f"optional extra '{extra}' pulls in a model client: {requirement}"


def test_no_module_imports_a_model_client() -> None:
    """No module in the package may import an LLM or inference library."""
    offenders = {
        path.relative_to(ROOT).as_posix(): _banned_imports(path)
        for path in _iter_modules()
        if _banned_imports(path)
    }

    assert offenders == {}


def test_imports_stay_within_the_declared_surface() -> None:
    """Any new third-party import must be a deliberate, declared decision."""
    allowed = (
        CORE_DEPENDENCIES
        | OPTIONAL_DEPENDENCIES
        | {"bqtofabric"}
        | set(sys.stdlib_module_names)
    )
    unexpected = {
        path.relative_to(ROOT).as_posix(): sorted(_imported_roots(path) - allowed)
        for path in _iter_modules()
        if _imported_roots(path) - allowed
    }

    assert unexpected == {}


def test_optional_discovery_dependencies_are_imported_lazily() -> None:
    """Importing the package must not require the optional gcp extra."""
    for path in _iter_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:  # module level only
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                roots = {node.module.split(".")[0]}
            else:
                continue
            leaked = roots & OPTIONAL_DEPENDENCIES
            assert not leaked, (
                f"{path.relative_to(ROOT).as_posix()} imports {sorted(leaked)} at module "
                "level; the optional gcp extra must stay lazily imported"
            )
