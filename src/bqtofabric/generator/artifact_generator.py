"""Orchestrate all Fabric artifact generation."""

from __future__ import annotations

import json
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
        for source_id, notebook in notebooks.items():
            output_path = lakehouse_dir / f"notebook_{source_id.replace('.', '_')}.ipynb"
            self._write_notebook(notebook, output_path)
            manifest["artifacts"].setdefault("notebooks", []).append({
                "sourceId": source_id,
                "name": notebook.title,
                "path": str(output_path.relative_to(output_dir)),
                "valid": notebook.valid,
            })

        # Generate warehouse scripts
        warehouse_scripts = generate_all_warehouse_scripts(self.inventory, self.assessment)
        for source_id, script in warehouse_scripts.items():
            output_path = warehouse_dir / f"{script.name}.sql"
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
        for source_id, eventstream in eventstreams.items():
            output_path = realtime_dir / f"{eventstream.name}_topology.json"
            output_path.write_text(
                json.dumps(eventstream.topology, indent=2),
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
        for source_id, schema in eventhouse_schemas.items():
            output_path = realtime_dir / f"{schema.name}_schema.kql"
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
        for source_id, model in semantic_models.items():
            output_path = semantic_dir / f"{model.name}_definition.json"
            output_path.write_text(
                json.dumps(model.model, indent=2),
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
        for source_id, pipeline in pipelines.items():
            output_path = pipeline_dir / f"{pipeline.name}_definition.json"
            output_path.write_text(
                json.dumps(pipeline.pipeline, indent=2),
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
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        # Collect all warnings
        for script in warehouse_scripts.values():
            warnings.extend(script.warnings)
        for eventstream in eventstreams.values():
            warnings.extend(eventstream.warnings)
        for schema in eventhouse_schemas.values():
            warnings.extend(schema.warnings)
        for model in semantic_models.values():
            warnings.extend(model.warnings)
        for pipeline in pipelines.values():
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
            json.dumps(notebook.to_ipynb_dict(), indent=2),
            encoding="utf-8",
        )


def generate_artifacts(
    inventory: BigQueryInventory,
    assessment: AssessmentReport,
    output_dir: Path,
) -> ArtifactGenerationReport:
    """Generate all Fabric artifacts from inventory and assessment."""
    gen = ArtifactGenerator(inventory, assessment)
    return gen.generate_all(output_dir)
