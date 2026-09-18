import json
from pathlib import Path

from bqtofabric.artifact_validation import validate_artifact, validate_directory


def test_validate_directory_checks_notebook_and_json(tmp_path: Path) -> None:
    (tmp_path / "valid.ipynb").write_text(json.dumps({
        "nbformat": 4,
        "cells": [{"cell_type": "code", "source": []}],
    }), encoding="utf-8")
    (tmp_path / "artifact.json").write_text(json.dumps({"mode": "dry-run"}), encoding="utf-8")

    result = validate_directory(tmp_path)

    assert result["status"] == "passed"
    assert len(result["artifacts"]) == 2


def test_validate_artifact_rejects_invalid_notebook(tmp_path: Path) -> None:
    path = tmp_path / "invalid.ipynb"
    path.write_text(json.dumps({"nbformat": 3, "cells": "invalid"}), encoding="utf-8")

    result = validate_artifact(path)

    assert result["status"] == "failed"
    assert result["errors"]