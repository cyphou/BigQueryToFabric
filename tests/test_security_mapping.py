import json
from pathlib import Path

import pytest

from bqtofabric.cli import main
from bqtofabric.models import BigQueryObject, ObjectKind
from bqtofabric.security_mapping import POLICY_CONTROLS, propose_security_control

FIXTURE = Path(__file__).parent / "fixtures" / "gcp_ecosystem_project.json"


def _policy(name: str = "customer_policy", **properties: object) -> BigQueryObject:
    return BigQueryObject(f"p.security.{name}", name, ObjectKind.SECURITY_POLICY, properties=dict(properties))


@pytest.mark.parametrize("policy_type", sorted(POLICY_CONTROLS))
def test_every_policy_type_has_a_control_and_never_claims_access(policy_type: str) -> None:
    proposal = propose_security_control(_policy(policy_type=policy_type))

    assert proposal["control"] == POLICY_CONTROLS[policy_type][0]
    assert proposal["compatibility"] in {"transform", "redesign"}
    assert proposal["effectiveAccess"] == "not_recorded"
    assert proposal["permissionParity"] == "not_recorded"
    assert proposal["status"] == "review_required"


def test_unknown_or_missing_policy_type_is_unsupported() -> None:
    assert propose_security_control(_policy(policy_type="org_policy"))["compatibility"] == "unsupported"
    assert propose_security_control(_policy())["policyType"] == "not_recorded"


def test_principals_are_never_emitted_in_clear() -> None:
    proposal = propose_security_control(_policy(
        policy_type="dataset_access_entry",
        grantees=["principal:0123456789ab", "user:alice@example.com", "group:ops@example.com"],
    ))

    assert proposal["principals"] == ["principal:0123456789ab"]
    assert proposal["unpseudonymizedPrincipals"] == 2
    assert "example.com" not in json.dumps(proposal)


def test_rls_template_is_deny_all_and_disabled() -> None:
    proposal = propose_security_control(_policy(
        policy_type="row_access_policy", table="sales.orders", filter_column="region",
    ))

    sql = proposal["dryRunSql"]
    assert "WHERE 1 = 0" in sql
    assert "WITH (STATE = OFF)" in sql
    assert "ON [sales].[orders]" in sql


def test_rls_template_requires_safe_identifiers() -> None:
    proposal = propose_security_control(_policy(
        policy_type="row_access_policy", table="sales.orders]; DROP TABLE x;--", filter_column="region",
    ))

    assert "dryRunSql" not in proposal
    assert any("properties.table" in action for action in proposal["actions"])


def test_report_flow_writes_security_proposals(tmp_path: Path) -> None:
    assert main(["plan", str(FIXTURE), "--output", str(tmp_path)]) == 0

    proposals = json.loads((tmp_path / "security-proposals.json").read_text(encoding="utf-8"))

    assert [item["control"] for item in proposals["proposals"]] == ["warehouse_row_level_security"]
