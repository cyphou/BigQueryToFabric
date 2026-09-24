"""Opt-in integration coverage for the supported live GCP discovery adapters."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from bqtofabric.cli import ExitCode, main

pytestmark = pytest.mark.live_gcp


def _required_environment() -> dict[str, str]:
    if os.environ.get("BQTOFABRIC_LIVE_GCP") != "1":
        pytest.skip("set BQTOFABRIC_LIVE_GCP=1 to enable live GCP discovery")

    names = {
        "project": "BQTOFABRIC_GCP_PROJECT",
        "dataflow_regions": "BQTOFABRIC_DATAFLOW_REGIONS",
        "dataproc_regions": "BQTOFABRIC_DATAPROC_REGIONS",
        "composer_regions": "BQTOFABRIC_COMPOSER_REGIONS",
        "dataform_location": "BQTOFABRIC_DATAFORM_LOCATION",
    }
    missing = [name for name, variable in names.items() if not os.environ.get(variable)]
    if missing:
        pytest.fail(
            "live GCP discovery is enabled but configuration is missing: "
            + ", ".join(missing)
        )
    return {name: os.environ[variable] for name, variable in names.items()}


def _regions(value: str) -> list[str]:
    return [region.strip() for region in value.split(",") if region.strip()]


def _flag_values(flag: str, values: list[str]) -> list[str]:
    return [item for value in values for item in (flag, value)]


def _discover(project: str, output: Path, config: dict[str, str]) -> int:
    arguments = [
        "discover",
        project,
        "--output",
        str(output),
        *_flag_values("--dataflow-region", _regions(config["dataflow_regions"])),
        *_flag_values("--dataproc-region", _regions(config["dataproc_regions"])),
        "--dataform",
        "--dataform-location",
        config["dataform_location"],
        *_flag_values("--composer-region", _regions(config["composer_regions"])),
    ]
    return int(main(arguments))


def test_live_discovery_all_adapters_is_deterministic_and_redacted(tmp_path: Path) -> None:
    """Verify the public discovery path against an authorized read-only GCP sandbox."""
    config = _required_environment()
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    assert _discover(config["project"], first, config) == ExitCode.SUCCESS
    assert _discover(config["project"], second, config) == ExitCode.SUCCESS
    assert first.read_bytes() == second.read_bytes()

    inventory = json.loads(first.read_text(encoding="utf-8"))
    objects = inventory["objects"]
    provenances = {item["discovered_from"] for item in objects}
    assert "bigquery_api" in provenances
    assert provenances - {"bigquery_api"} <= {
        "dataflow_api",
        "dataproc_api",
        "dataform_api",
        "composer_api",
    }

    serialized = first.read_text(encoding="utf-8").lower()
    assert "[redacted]" in serialized or not any(
        marker in serialized for marker in ("bearer ", "private_key", "-----begin")
    )