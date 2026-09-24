from bqtofabric.repair import (
    RepairRule,
    repair_and_validate,
    repair_duplicate_schema_fields,
    repair_pipeline_triggers,
)


def test_repair_loop_records_repairs_and_revalidates() -> None:
    def move_triggers(value: dict) -> tuple[dict, bool]:
        properties = value.get("properties", {})
        if "triggers" not in properties:
            return value, False
        repaired = dict(value)
        repaired["triggers"] = properties["triggers"]
        repaired["properties"] = {key: item for key, item in properties.items() if key != "triggers"}
        return repaired, True

    result = repair_and_validate(
        {"properties": {"activities": [], "triggers": [{"name": "daily"}]}},
        rules=(RepairRule("move_pipeline_triggers", move_triggers),),
        validator=lambda value: "triggers" not in value.get("properties", {}),
    )

    assert result.status == "repaired"
    assert result.applied_rules == ("move_pipeline_triggers",)
    assert result.valid is True
    assert result.value["triggers"] == [{"name": "daily"}]


def test_repair_loop_fails_closed_when_validation_still_fails() -> None:
    result = repair_and_validate(
        {"properties": {"secret": "value"}},
        rules=(),
        validator=lambda value: "secret" not in value.get("properties", {}),
    )

    assert result.status == "manual_review"
    assert result.valid is False
    assert result.applied_rules == ()


def test_pipeline_trigger_repair_moves_only_the_invalid_field() -> None:
    pipeline = {"properties": {"activities": [], "triggers": [{"name": "daily"}]}}

    repaired, changed = repair_pipeline_triggers(pipeline)

    assert changed is True
    assert repaired == {
        "properties": {"activities": []},
        "triggers": [{"name": "daily"}],
    }
    assert pipeline["properties"]["triggers"] == [{"name": "daily"}]


def test_pipeline_trigger_repair_can_clear_the_existing_validator_error() -> None:
    from bqtofabric.artifact_validation import PipelineValidator

    result = repair_and_validate(
        {"properties": {"activities": [], "triggers": [{"name": "daily"}]}},
        rules=(RepairRule("move_pipeline_triggers", repair_pipeline_triggers),),
        validator=lambda value: PipelineValidator(value).validate().valid,
    )

    assert result.status == "repaired"
    assert result.valid is True


def test_schema_repair_removes_exact_duplicates_recursively() -> None:
    schema = [
        {"name": "id", "data_type": "INT64", "fields": []},
        {"name": "id", "data_type": "INT64", "fields": []},
        {
            "name": "payload",
            "data_type": "STRUCT",
            "fields": [
                {"name": "value", "data_type": "STRING"},
                {"name": "value", "data_type": "STRING"},
            ],
        },
    ]

    repaired, changed = repair_duplicate_schema_fields(schema)

    assert changed is True
    assert repaired == [
        {"name": "id", "data_type": "INT64", "fields": []},
        {"name": "payload", "data_type": "STRUCT", "fields": [{"name": "value", "data_type": "STRING"}]},
    ]
    assert len(schema) == 3


def test_schema_repair_keeps_conflicting_duplicates_for_manual_review() -> None:
    schema = [
        {"name": "id", "data_type": "INT64"},
        {"name": "id", "data_type": "STRING"},
    ]

    repaired, changed = repair_duplicate_schema_fields(schema)

    assert changed is False
    assert repaired == schema


def test_schema_repair_can_clear_duplicate_field_parity_failure() -> None:
    from bqtofabric.parity import compare_schema

    schema = [
        {"name": "id", "data_type": "INT64"},
        {"name": "id", "data_type": "INT64"},
    ]
    result = repair_and_validate(
        schema,
        rules=(RepairRule("remove_exact_duplicate_schema_fields", repair_duplicate_schema_fields),),
        validator=lambda value: compare_schema(value, value)["status"] == "passed",
    )

    assert result.status == "repaired"
    assert result.valid is True