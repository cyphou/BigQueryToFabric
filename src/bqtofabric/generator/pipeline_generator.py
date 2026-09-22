"""Generate Azure Data Factory pipeline definitions for ETL orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..assessment import AssessmentReport
from ..mapping import FabricTarget, MappingDecision
from ..models import BigQueryInventory, BigQueryObject, ObjectKind


@dataclass(frozen=True, slots=True)
class PipelineDefinition:
    """Complete Data Factory pipeline definition."""

    name: str
    description: str
    source_id: str
    source_kind: ObjectKind
    pipeline: dict[str, Any]
    warnings: tuple[str, ...] = ()
    valid: bool = True


class PipelineGenerator:
    """Generate Azure Data Factory pipelines."""

    def __init__(self, inventory: BigQueryInventory, assessment: AssessmentReport) -> None:
        """Initialize with inventory and assessment data."""
        self.inventory = inventory
        self.assessment = assessment
        self.objects = {obj.source_id: obj for obj in inventory.objects()}
        self.decisions = {dec.source_id: dec for dec in assessment.decisions}

    def generate_pipeline(
        self, item: BigQueryObject, decision: MappingDecision
    ) -> PipelineDefinition | None:
        """Generate a Data Factory pipeline from a Composer DAG or scheduled object."""
        if item.kind not in {
            ObjectKind.COMPOSER_DAG,
            ObjectKind.SCHEDULED_QUERY,
            ObjectKind.BIGQUERY_JOB,
            ObjectKind.DATAFORM_WORKFLOW,
        }:
            return None

        warnings: list[str] = []
        pipeline: dict[str, Any] = {
            "name": f"pipeline_{item.name}",
            "properties": {
                "description": decision.rationale,
                "activities": self._build_activities(item, decision, warnings),
                "parameters": self._build_parameters(item),
                "variables": self._build_variables(item),
                "triggers": self._build_triggers(item, warnings),
            },
            "sourceId": item.source_id,
            "sourceKind": item.kind.value,
        }

        return PipelineDefinition(
            name=f"pipeline_{item.name}",
            description=f"Generated from {item.kind.value} {item.source_id}",
            source_id=item.source_id,
            source_kind=item.kind,
            pipeline=pipeline,
            warnings=tuple(warnings),
        )

    def _build_activities(
        self, item: BigQueryObject, decision: MappingDecision, warnings: list[str]
    ) -> list[dict[str, Any]]:
        """Build pipeline activities from item dependencies and type."""
        activities: list[dict[str, Any]] = []

        # Add lookup activity for watermark
        activities.append({
            "name": "Get Watermark",
            "type": "Lookup",
            "typeProperties": {
                "source": {
                    "type": "SqlServerSource",
                    "sqlReaderQuery": "SELECT ISNULL(MAX(watermark_value), '1900-01-01') AS value FROM watermark_table WHERE table_name = '@{pipeline().parameters.TableName}'",
                },
                "firstRowOnly": True,
            },
            "linkedServiceName": {"referenceName": "AzureSqlLinkedService", "type": "LinkedServiceReference"},
        })

        # Main activity based on source kind
        if item.kind is ObjectKind.SCHEDULED_QUERY:
            activities.append(self._build_sql_activity(item, warnings))
        elif item.kind is ObjectKind.BIGQUERY_JOB:
            activities.append(self._build_copy_activity(item, warnings))
        elif item.kind is ObjectKind.COMPOSER_DAG:
            # For Composer DAGs, build an activity per task
            tasks = item.properties.get("tasks", [])
            for task_idx, task in enumerate(tasks):
                activities.append(self._build_task_activity(task, item, task_idx, warnings))
        elif item.kind is ObjectKind.DATAFORM_WORKFLOW:
            activities.append(self._build_notebook_activity(item, warnings))

        main_activity_name = activities[-1]["name"]

        # Add error handling activity
        activities.append({
            "name": "Handle Error",
            "type": "WebHook",
            "typeProperties": {
                "url": "${linkedService().properties.typeProperties.deploymentUri}/webhooks/failure",
                "method": "POST",
                "headers": {"x-pipeline-name": f"pipeline_{item.name}"},
                "body": {"errorMessage": "@{activity('Main Activity').error.message}"},
                "timeout": "00:10:00",
            },
            "onInactivityTimeout": "00:05:00",
            "policy": {"secureInput": True, "secureOutput": True},
            "dependsOn": [{"activity": main_activity_name, "dependencyConditions": ["Failed"]}],
        })

        # Add update watermark activity
        activities.append({
            "name": "Update Watermark",
            "type": "SqlServerStoredProcedure",
            "typeProperties": {
                "storedProcedureName": "usp_update_watermark",
                "storedProcedureParameters": {
                    "table_name": {"value": "@{pipeline().parameters.TableName}", "type": "String"},
                    "watermark_value": {"value": "@{activity('Get Watermark').output.firstRow.value}", "type": "String"},
                },
            },
            "linkedServiceName": {"referenceName": "AzureSqlLinkedService", "type": "LinkedServiceReference"},
            "dependsOn": [
                {"activity": main_activity_name, "dependencyConditions": ["Succeeded"]},
            ],
        })

        if not activities:
            warnings.append("No activities generated; manual pipeline configuration required")

        return activities

    def _build_sql_activity(self, item: BigQueryObject, warnings: list[str]) -> dict[str, Any]:
        """Build SQL activity for scheduled query."""
        return {
            "name": "Main Activity",
            "type": "ExecutePipeline",
            "typeProperties": {
                "pipeline": {
                    "referenceName": "ExecuteSqlJob",
                    "type": "PipelineReference",
                },
                "parameters": {
                    "SourceConnectionString": "@linkedService().properties.typeProperties.connectionString",
                    "TargetConnectionString": "@linkedService('AzureSqlLinkedService').properties.typeProperties.connectionString",
                    "JobId": "@{pipeline().parameters.JobId}",
                },
                "waitOnCompletion": True,
            },
            "linkedServiceName": {"referenceName": "BigQueryLinkedService", "type": "LinkedServiceReference"},
        }

    def _build_copy_activity(self, item: BigQueryObject, warnings: list[str]) -> dict[str, Any]:
        """Build copy activity for BigQuery job."""
        warnings.append("TODO: MANUAL REVIEW - Configure BigQuery source and Warehouse sink")

        return {
            "name": "Main Activity",
            "type": "Copy",
            "typeProperties": {
                "source": {
                    "type": "GoogleBigQuerySource",
                    "project": "@{linkedService('BigQueryLinkedService').properties.typeProperties.project}",
                    "dataset": f"{item.dataset}",
                    "table": f"{item.name}",
                    "query": None,
                    "queryTimeout": "00:30:00",
                },
                "sink": {
                    "type": "SqlServerSink",
                    "preCopyScript": f"TRUNCATE TABLE [{item.dataset}].[{item.name}]",
                    "allowPolyBase": True,
                },
                "translator": {"type": "TabularTranslator", "mappings": []},
                "parallelCopies": 4,
            },
            "linkedServiceName": {"referenceName": "BigQueryLinkedService", "type": "LinkedServiceReference"},
            "inputs": [{"referenceName": f"ds_bigquery_{item.name}", "type": "DatasetReference"}],
            "outputs": [{"referenceName": f"ds_warehouse_{item.name}", "type": "DatasetReference"}],
        }

    def _build_task_activity(
        self, task: dict[str, Any], item: BigQueryObject, task_idx: int, warnings: list[str]
    ) -> dict[str, Any]:
        """Build activity from Composer task."""
        task_type = task.get("operator", "BashOperator")
        task_id = task.get("task_id", f"task_{task_idx}")

        # Map Airflow operators to ADF activities
        if "bash" in task_type.lower():
            return {
                "name": task_id,
                "type": "WebHook",
                "typeProperties": {
                    "url": "${linkedService().properties.typeProperties.webhookUrl}",
                    "method": "POST",
                    "headers": {"x-airflow-task": task_id},
                    "body": task.get("bash_command", ""),
                },
            }
        elif "sql" in task_type.lower():
            return {
                "name": task_id,
                "type": "ExecutePipeline",
                "typeProperties": {
                    "pipeline": {"referenceName": "ExecuteSqlJob", "type": "PipelineReference"},
                    "parameters": {
                        "SqlQuery": task.get("sql", ""),
                    },
                },
            }
        else:
            warnings.append(f"Task {task_id}: operator {task_type} may require manual conversion")
            return {
                "name": task_id,
                "type": "Wait",
                "typeProperties": {"waitTimeInSeconds": 1},
            }

    def _build_notebook_activity(self, item: BigQueryObject, warnings: list[str]) -> dict[str, Any]:
        """Build notebook activity for Dataform workflow."""
        warnings.append("TODO: MANUAL REVIEW - Link to generated Lakehouse notebook")

        return {
            "name": "Main Activity",
            "type": "ExecutePipelineActivity",
            "typeProperties": {
                "pipeline": {
                    "referenceName": f"notebook_{item.name}",
                    "type": "PipelineReference",
                },
                "parameters": {
                    "InputPath": "@pipeline().parameters.InputPath",
                    "OutputPath": "@pipeline().parameters.OutputPath",
                },
                "waitOnCompletion": True,
            },
        }

    def _build_parameters(self, item: BigQueryObject) -> list[dict[str, Any]]:
        """Build pipeline parameters."""
        return [
            {"name": "TableName", "type": "string", "defaultValue": item.name},
            {"name": "JobId", "type": "string", "defaultValue": item.source_id},
            {"name": "InputPath", "type": "string", "defaultValue": "/input"},
            {"name": "OutputPath", "type": "string", "defaultValue": "/output"},
            {"name": "PartitionDate", "type": "string", "defaultValue": "@utcNow('yyyy-MM-dd')"},
        ]

    def _build_variables(self, item: BigQueryObject) -> list[dict[str, Any]]:
        """Build pipeline variables."""
        return [
            {"name": "ExecutionId", "type": "String"},
            {"name": "RowCount", "type": "Integer"},
            {"name": "LastWatermark", "type": "String"},
        ]

    def _build_triggers(self, item: BigQueryObject, warnings: list[str]) -> list[dict[str, Any]]:
        """Build triggers from schedule information."""
        triggers: list[dict[str, Any]] = []

        schedule_interval = item.properties.get("schedule_interval", item.properties.get("schedule"))
        if schedule_interval:
            # Map Airflow schedule_interval to ADF trigger
            if schedule_interval == "@daily":
                recurrence = {"frequency": "Day", "interval": 1}
            elif schedule_interval == "@hourly":
                recurrence = {"frequency": "Hour", "interval": 1}
            elif schedule_interval == "@weekly":
                recurrence = {"frequency": "Week", "interval": 1}
            else:
                recurrence = None
                warnings.append(f"Schedule {schedule_interval} not automatically mapped; manual configuration required")

            if recurrence:
                triggers.append({
                    "name": f"trigger_{item.name}",
                    "properties": {
                        "description": f"Trigger for {item.name}",
                        "runtimeState": "Started",
                        "type": "ScheduleTrigger",
                        "typeProperties": {
                            "recurrence": recurrence,
                            "startTime": "@utcNow('2024-01-01T00:00:00Z')",
                            "endTime": None,
                            "timeZone": "UTC",
                        },
                        "pipelines": [
                            {
                                "pipelineReference": {"referenceName": f"pipeline_{item.name}", "type": "PipelineReference"},
                                "parameters": {},
                            }
                        ],
                    },
                })

        if not triggers:
            warnings.append("No triggers configured; manually add trigger for scheduling")

        return triggers


def generate_all_pipelines(
    inventory: BigQueryInventory,
    assessment: AssessmentReport,
) -> dict[str, PipelineDefinition]:
    """Generate all pipelines from inventory and assessment."""
    gen = PipelineGenerator(inventory, assessment)
    objects = {obj.source_id: obj for obj in inventory.objects()}
    decisions = {dec.source_id: dec for dec in assessment.decisions}

    pipelines: dict[str, PipelineDefinition] = {}
    for source_id, decision in decisions.items():
        if decision.target not in {FabricTarget.DATA_PIPELINE, FabricTarget.NOTEBOOK}:
            continue
        item = objects.get(source_id)
        if item is None:
            continue
        pipeline = gen.generate_pipeline(item, decision)
        if pipeline is not None:
            pipelines[source_id] = pipeline

    return pipelines
