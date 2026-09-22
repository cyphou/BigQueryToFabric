"""Orchestrate all Fabric artifact generation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..assessment import AssessmentReport
from ..models import BigQueryInventory
from .eventstream_generator import (
    generate_all_eventhouse_schemas,
    generate_all_eventstreams,
)
from .notebook_generator import generate_all_notebooks
from .pipeline_generator import generate_all_pipelines
from .semantic_model_generator import generate_all_semantic_models
from .warehouse_generator import generate_all_warehouse_scripts


@dataclass(frozen=True, slots=True)
class ArtifactGenerationReport:
    """Summary of artifact generation execution."""

    project_id: str
    total_generated: int
    notebooks: int
    warehouse_scripts: int
    eventstreams: int
    eventhouse_schemas: int
    semantic_models: int
    pipelines: int
    warnings: list[str]
    manifest: dict[str, Any]


class ArtifactGenerator:
    """Orchestrate complete Fabric artifact generation."""

    def __init__(self, inventory: BigQueryInventory, assessment: AssessmentReport) -> None:
        """Initialize with inventory and assessment."""
        self.inventory = inventory
        self.assessment = assessment

    def generate_all(self, output_dir: Path) -> ArtifactGenerationReport:
        """Generate all artifacts and write to output directory."""
        output_dir.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        lakehouse_dir = output_dir / "lakehouse"
        warehouse_dir = output_dir / "warehouse"
        realtime_dir = output_dir / "realtime"
        semantic_dir = output_dir / "semantic_model"
        pipeline_dir = output_dir / "pipelines"

        for d in [lakehouse_dir, warehouse_dir, realtime_dir, semantic_dir, pipeline_dir]:
            d.mkdir(parents=True, exist_ok=True)

        warnings: list[str] = []
        manifest: dict[str, Any] = {
            "version": "1.0",
            "projectId": self.inventory.project_id,
            "generatedAt": "{{timestamp}}",
            "artifacts": {},
        }

        # Generate notebooks
        notebooks = generate_all_notebooks(self.inventory, self.assessment)
        for source_id, notebook in sorted(notebooks.items()):
            output_path = lakehouse_dir / self._artifact_filename("notebook", source_id, ".ipynb")
            self._write_notebook(notebook, output_path)
            manifest["artifacts"].setdefault("notebooks", []).append({
                "sourceId": source_id,
                "name": notebook.title,
                "path": str(output_path.relative_to(output_dir)),
                "valid": notebook.valid,
            })

        # Generate warehouse scripts
        warehouse_scripts = generate_all_warehouse_scripts(self.inventory, self.assessment)
        for source_id, script in sorted(warehouse_scripts.items()):
            output_path = warehouse_dir / self._artifact_filename("warehouse", source_id, ".sql")
            output_path.write_text(script.script, encoding="utf-8")
            manifest["artifacts"].setdefault("warehouse", []).append({
                "sourceId": source_id,
                "name": script.name,
                "path": str(output_path.relative_to(output_dir)),
                "warnings": list(script.warnings),
                "valid": script.valid,
            })

        # Generate eventstreams
        eventstreams = generate_all_eventstreams(self.inventory, self.assessment)
        for source_id, eventstream in sorted(eventstreams.items()):
            output_path = realtime_dir / self._artifact_filename(
                "eventstream", source_id, "_topology.json"
            )
            output_path.write_text(
            json.dumps(eventstream.topology, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            manifest["artifacts"].setdefault("eventstreams", []).append({
                "sourceId": source_id,
                "name": eventstream.name,
                "path": str(output_path.relative_to(output_dir)),
                "warnings": list(eventstream.warnings),
                "valid": eventstream.valid,
            })

        # Generate eventhouse schemas
        eventhouse_schemas = generate_all_eventhouse_schemas(self.inventory, self.assessment)
        for source_id, schema in sorted(eventhouse_schemas.items()):
            output_path = realtime_dir / self._artifact_filename(
                "eventhouse", source_id, "_schema.kql"
            )
            output_path.write_text(schema.kql_script, encoding="utf-8")
            manifest["artifacts"].setdefault("eventhouse", []).append({
                "sourceId": source_id,
                "name": schema.name,
                "path": str(output_path.relative_to(output_dir)),
                "warnings": list(schema.warnings),
                "valid": schema.valid,
            })

        # Generate semantic models
        semantic_models = generate_all_semantic_models(self.inventory, self.assessment)
        for source_id, model in sorted(semantic_models.items()):
            output_path = semantic_dir / self._artifact_filename(
                "semantic_model", source_id, "_definition.json"
            )
            output_path.write_text(
            json.dumps(model.model, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            manifest["artifacts"].setdefault("semantic_models", []).append({
                "sourceId": source_id,
                "name": model.name,
                "path": str(output_path.relative_to(output_dir)),
                "warnings": list(model.warnings),
                "valid": model.valid,
            })

        # Generate pipelines
        pipelines = generate_all_pipelines(self.inventory, self.assessment)
        for source_id, pipeline in sorted(pipelines.items()):
            output_path = pipeline_dir / self._artifact_filename(
                "pipeline", source_id, "_definition.json"
            )
            output_path.write_text(
            json.dumps(pipeline.pipeline, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            manifest["artifacts"].setdefault("pipelines", []).append({
                "sourceId": source_id,
                "name": pipeline.name,
                "path": str(output_path.relative_to(output_dir)),
                "warnings": list(pipeline.warnings),
                "valid": pipeline.valid,
            })

        # Write manifest
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

        # Collect all warnings
        for _, script in sorted(warehouse_scripts.items()):
            warnings.extend(script.warnings)
        for _, eventstream in sorted(eventstreams.items()):
            warnings.extend(eventstream.warnings)
        for _, schema in sorted(eventhouse_schemas.items()):
            warnings.extend(schema.warnings)
        for _, model in sorted(semantic_models.items()):
            warnings.extend(model.warnings)
        for _, pipeline in sorted(pipelines.items()):
            warnings.extend(pipeline.warnings)

        return ArtifactGenerationReport(
            project_id=self.inventory.project_id,
            total_generated=sum(len(x) for x in [
                notebooks,
                warehouse_scripts,
                eventstreams,
                eventhouse_schemas,
                semantic_models,
                pipelines,
            ]),
            notebooks=len(notebooks),
            warehouse_scripts=len(warehouse_scripts),
            eventstreams=len(eventstreams),
            eventhouse_schemas=len(eventhouse_schemas),
            semantic_models=len(semantic_models),
            pipelines=len(pipelines),
            warnings=warnings,
            manifest=manifest,
        )

    @staticmethod
    def _write_notebook(notebook, output_path: Path) -> None:
        """Write notebook to .ipynb file."""
        output_path.write_text(
            json.dumps(notebook.to_ipynb_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    @staticmethod
    def _artifact_filename(prefix: str, source_id: str, suffix: str) -> str:
        """Build a stable filename that remains unique for distinct source IDs."""
        safe_source_id = re.sub(r"[^A-Za-z0-9._-]+", "_", source_id).strip("._")
        source_hash = hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:12]
        return f"{prefix}_{safe_source_id or 'unknown'}_{source_hash}{suffix}"


def generate_artifacts(
    inventory: BigQueryInventory,
    assessment: AssessmentReport,
    output_dir: Path,
) -> ArtifactGenerationReport:
    """Generate all Fabric artifacts from inventory and assessment."""
    gen = ArtifactGenerator(inventory, assessment)
    return gen.generate_all(output_dir)
