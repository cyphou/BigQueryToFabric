import json
import re
from pathlib import Path
from typing import Any

import pytest

from bqtofabric.mapping import FabricTarget, MappingDecision
from bqtofabric.models import BigQueryObject, ObjectKind
from bqtofabric.sql_assessment import assess_sql
from bqtofabric.type_mapping import Compatibility

ROOT = Path(__file__).resolve().parents[1]
CORPUS = json.loads((ROOT / "tests" / "fixtures" / "sql_corpus.json").read_text(encoding="utf-8"))
REFERENCE = ROOT / ".github" / "skills" / "bigquery-to-fabric" / "references" / "sql-compatibility.md"
ORDER = ["direct", "transform", "redesign", "unsupported"]


def _assess(case: dict[str, Any], target: FabricTarget) -> Compatibility:
    item = BigQueryObject(f"p.corpus.{case['id']}", case["id"], ObjectKind.SQL_SCRIPT, sql=case["sql"])
    decision = MappingDecision(item.source_id, item.kind, target, Compatibility.DIRECT, "corpus")
    result = assess_sql(item, decision)
    assert result is not None
    return result.compatibility


@pytest.mark.parametrize("target", [FabricTarget.WAREHOUSE, FabricTarget.LAKEHOUSE])
@pytest.mark.parametrize("case", CORPUS["cases"], ids=[case["id"] for case in CORPUS["cases"]])
def test_construct_is_never_rated_better_than_its_semantics(
    case: dict[str, Any], target: FabricTarget
) -> None:
    verdict = _assess(case, target)

    assert ORDER.index(verdict.value) >= ORDER.index(case["max_compatibility"]), (
        f"{case['id']} on {target.value}: {verdict.value} is better than {case['max_compatibility']}"
    )


def test_every_documented_construct_has_a_corpus_case() -> None:
    table = REFERENCE.read_text(encoding="utf-8").split("| Construct | Risk |", 1)[1]
    documented = set(re.findall(r"^\| (.+?) \| ", table, re.MULTILINE)) - {"---"}
    covered = {case["construct"] for case in CORPUS["cases"]}

    assert documented
    assert documented <= covered, f"no corpus case for: {sorted(documented - covered)}"


def test_corpus_ids_are_unique_and_levels_known() -> None:
    ids = [case["id"] for case in CORPUS["cases"]]

    assert len(ids) == len(set(ids))
    assert {case["max_compatibility"] for case in CORPUS["cases"]} <= set(ORDER)
