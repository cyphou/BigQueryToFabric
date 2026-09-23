"""Inventory providers for BigQuery migration discovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from .models import BigQueryInventory, ObjectKind


class BigQueryInventoryProvider(Protocol):
    def load(self) -> BigQueryInventory: ...


class JsonInventoryProvider:
    """Load a canonical inventory without requiring GCP credentials."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> BigQueryInventory:
        if not self.path.is_file():
            raise FileNotFoundError(f"Inventory file not found: {self.path}")
        with self.path.open(encoding="utf-8") as stream:
            value = json.load(stream)
        if not isinstance(value, dict):
            raise TypeError("Inventory root must be a JSON object")
        validate_inventory_document(value)
        return BigQueryInventory.from_dict(value)


def validate_inventory_document(value: dict[str, Any]) -> None:
    """Validate the canonical inventory contract before model coercion."""
    if not isinstance(value.get("project_id"), str) or not value["project_id"].strip():
        raise ValueError("Inventory project_id must be a non-empty string")
    for field_name in ("datasets", "components"):
        if field_name in value and not isinstance(value[field_name], list):
            raise ValueError(f"Inventory {field_name} must be an array")

    seen_ids: set[str] = set()
    for dataset in value.get("datasets", []):
        _validate_dataset(dataset, seen_ids)
    for component in value.get("components", []):
        _validate_object(component, seen_ids)


def _validate_dataset(value: Any, seen_ids: set[str]) -> None:
    if not isinstance(value, dict):
        raise TypeError("Dataset must be an object")
    _require_string(value, "source_id", "Dataset")
    _require_string(value, "name", "Dataset")
    if "objects" in value and not isinstance(value["objects"], list):
        raise ValueError("Dataset objects must be an array")
    for item in value.get("objects", []):
        _validate_object(item, seen_ids)


def _validate_object(value: Any, seen_ids: set[str]) -> None:
    if not isinstance(value, dict):
        raise TypeError("Inventory object must be an object")
    source_id = _require_string(value, "source_id", "Inventory object")
    _require_string(value, "name", "Inventory object")
    kind = _require_string(value, "kind", "Inventory object")
    if kind not in {item.value for item in ObjectKind}:
        raise ValueError(f"Unknown inventory object kind: {kind}")
    if source_id in seen_ids:
        raise ValueError(f"Duplicate inventory source_id: {source_id}")
    seen_ids.add(source_id)
    for field_name in ("columns", "dependencies", "clustering_fields"):
        if field_name in value and not isinstance(value[field_name], list):
            raise ValueError(f"Inventory object {field_name} must be an array: {source_id}")
    for dependency in value.get("dependencies", []):
        if not isinstance(dependency, str) or not dependency:
            raise ValueError(f"Inventory dependency must be a non-empty string: {source_id}")
    for column in value.get("columns", []):
        _validate_column(column, source_id)
    if "size_bytes" in value and value["size_bytes"] is not None and (
        not isinstance(value["size_bytes"], int)
        or isinstance(value["size_bytes"], bool)
        or value["size_bytes"] < 0
    ):
        raise ValueError(f"Inventory size_bytes must be a non-negative integer: {source_id}")


def _validate_column(value: Any, source_id: str) -> None:
    if not isinstance(value, dict):
        raise TypeError(f"Inventory column must be an object: {source_id}")
    _require_string(value, "name", "Inventory column")
    _require_string(value, "data_type", "Inventory column")
    if "fields" in value and not isinstance(value["fields"], list):
        raise ValueError(f"Inventory column fields must be an array: {source_id}")
    for nested in value.get("fields", []):
        _validate_column(nested, source_id)


def _require_string(value: dict[str, Any], field_name: str, context: str) -> str:
    field = value.get(field_name)
    if not isinstance(field, str) or not field.strip():
        raise ValueError(f"{context} {field_name} must be a non-empty string")
    return field
