"""Inventory providers for BigQuery migration discovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from .models import BigQueryInventory


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
        return BigQueryInventory.from_dict(value)
