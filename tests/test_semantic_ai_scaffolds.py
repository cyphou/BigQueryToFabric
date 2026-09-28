from bqtofabric.fabric_artifacts import _convert_lookml_measures, _data_science_scaffold
from bqtofabric.models import BigQueryObject, ObjectKind


def test_simple_lookml_aggregates_become_dax_measures() -> None:
    converted, unconverted = _convert_lookml_measures([
        {"name": "order_count", "type": "count", "view": "orders"},
        {"name": "revenue", "type": "sum", "view": "orders", "sql": "${TABLE}.amount"},
        {"name": "avg_basket", "type": "average", "view": "orders", "sql": "${amount}"},
        {"name": "buyers", "type": "count_distinct", "view": "orders", "sql": "${TABLE}.customer_id"},
    ])

    assert unconverted == []
    assert [measure["expression"] for measure in converted] == [
        "COUNTROWS('orders')",
        "SUM('orders'[amount])",
        "AVERAGE('orders'[amount])",
        "DISTINCTCOUNT('orders'[customer_id])",
    ]


def test_anything_not_a_plain_aggregate_is_listed_not_guessed() -> None:
    converted, unconverted = _convert_lookml_measures([
        {"name": "margin", "type": "number", "view": "orders", "sql": "${revenue} - ${cost}"},
        {"name": "net", "type": "sum", "view": "orders", "sql": "${TABLE}.amount - ${TABLE}.tax"},
        {"name": "eu_revenue", "type": "sum", "view": "orders", "sql": "${TABLE}.amount",
         "filters": [{"field": "region", "value": "EU"}]},
        {"name": "bad'name", "type": "count", "view": "orders"},
        {"name": "p90", "type": "percentile", "view": "orders", "sql": "${TABLE}.amount"},
    ])

    assert converted == []
    assert [item["reason"] for item in unconverted] == [
        "unsupported_type:number",
        "sql_expression",
        "filtered_measure",
        "unsafe_identifier",
        "unsupported_type:percentile",
    ]


def test_data_science_scaffold_never_claims_model_parity() -> None:
    bqml = BigQueryObject("p.bqml.churn", "churn", ObjectKind.BQML_MODEL)
    vertex = BigQueryObject(
        "p.vertex.churn-pipeline", "churn-pipeline", ObjectKind.VERTEX_AI_PIPELINE,
        properties={"pipeline_steps": ["train", "deploy"]},
    )

    bqml_scaffold = _data_science_scaffold(bqml, "logistic_reg")
    vertex_scaffold = _data_science_scaffold(vertex, "review_required")

    assert bqml_scaffold["approach"] == "scikit-learn LogisticRegression"
    assert bqml_scaffold["experimentName"] == "bqml_model_churn"
    assert vertex_scaffold["approach"] == "review_required"
    assert vertex_scaffold["experimentName"] == "vertex_ai_pipeline_churn_pipeline"
    assert vertex_scaffold["notebookSteps"] == ["train", "deploy"]
    assert {bqml_scaffold["modelParity"], vertex_scaffold["modelParity"]} == {"not_run"}
