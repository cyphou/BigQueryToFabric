from bqtofabric.dataform_conversion import convert_dataform_workflow
from bqtofabric.models import BigQueryObject, ObjectKind


def test_dataform_conversion_preserves_quality_and_incremental_requirements() -> None:
    item = BigQueryObject(
        source_id="demo.dataform.gold",
        name="gold",
        kind=ObjectKind.DATAFORM_WORKFLOW,
        dependencies=("demo.sql.daily",),
        properties={"models": ["orders"], "assertions": True, "incremental": True},
    )

    conversion = convert_dataform_workflow(item)

    assert conversion["target"] == "fabric_pipeline"
    assert conversion["dependencies"] == ["demo.sql.daily"]
    assert conversion["assertions"] is True
    assert conversion["incremental"] is True
    assert len(conversion["actions"]) == 4