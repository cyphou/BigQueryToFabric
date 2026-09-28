"""Reviewed Fabric security-control proposals for BigQuery security policies (offline).

A proposal names the Fabric control that could carry the policy's intent. It never
claims effective access or permission parity, and never emits a principal in clear.
"""

from __future__ import annotations

import re
from typing import Any

from .models import BigQueryObject, ObjectKind

_PSEUDONYM = re.compile(r"^principal:[0-9a-f]{12}$")
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# policy_type -> (Fabric control, compatibility, reviewer action)
POLICY_CONTROLS: dict[str, tuple[str, str, str]] = {
    "row_access_policy": (
        "warehouse_row_level_security",
        "redesign",
        (
            "Recreate as a Warehouse security policy with an inline predicate function; "
            "translate the source filter and test it per principal."
        ),
    ),
    "policy_tag": (
        "column_level_security",
        "redesign",
        (
            "Map the taxonomy to Purview sensitivity labels and enforce with Warehouse column "
            "GRANT/DENY or OneLake security."
        ),
    ),
    "data_masking": (
        "dynamic_data_masking",
        "redesign",
        "Recreate the masking rule as Warehouse Dynamic Data Masking and verify UNMASK grants.",
    ),
    "authorized_view": (
        "view_grant",
        "transform",
        "Recreate the view, GRANT SELECT on the view only, and deny direct base-table access.",
    ),
    "dataset_access_entry": (
        "workspace_or_onelake_role",
        "redesign",
        "Map dataset roles to Fabric workspace roles or OneLake data access roles.",
    ),
}


def propose_security_control(item: BigQueryObject) -> dict[str, Any]:
    """Return one deterministic, review-only proposal for a security policy."""
    if item.kind is not ObjectKind.SECURITY_POLICY:
        raise ValueError(f"Not a security policy: {item.kind.value}")
    policy_type = str(item.properties.get("policy_type") or item.properties.get("evidence_scope") or "")
    control, compatibility, action = POLICY_CONTROLS.get(
        policy_type,
        ("manual", "unsupported", "No mapped Fabric control; design the control by hand."),
    )
    grantees = item.properties.get("grantees", [])
    grantees = grantees if isinstance(grantees, list) else []
    pseudonymized = sorted({str(value) for value in grantees if _PSEUDONYM.match(str(value))})

    proposal: dict[str, Any] = {
        "sourceId": item.source_id,
        "policyType": policy_type or "not_recorded",
        "control": control,
        "compatibility": compatibility,
        "actions": [action],
        "principals": pseudonymized,
        "unpseudonymizedPrincipals": len(grantees) - len(pseudonymized),
        "effectiveAccess": "not_recorded",
        "permissionParity": "not_recorded",
        "status": "review_required",
    }
    if control == "warehouse_row_level_security":
        sql = _rls_template(item)
        if sql:
            proposal["dryRunSql"] = sql
        else:
            proposal["actions"].append(
                "Record properties.table (dataset.table) and properties.filter_column to "
                "generate a predicate template."
            )
    return proposal


def _rls_template(item: BigQueryObject) -> str | None:
    table = str(item.properties.get("table", ""))
    column = str(item.properties.get("filter_column", ""))
    schema, _, name = table.partition(".")
    if not all(_SAFE_IDENTIFIER.match(value) for value in (schema, name, column, item.name)):
        return None
    function = f"fn_{item.name}_predicate"
    # Deny-all predicate and STATE = OFF: the template cannot grant access until a human edits it.
    return (
        f"CREATE FUNCTION [security].[{function}](@{column} AS sql_variant)\n"
        "RETURNS TABLE WITH SCHEMABINDING AS\n"
        "RETURN SELECT 1 AS allowed WHERE 1 = 0; -- TODO: translate the BigQuery filter\n"
        "GO\n"
        f"CREATE SECURITY POLICY [security].[{item.name}_filter]\n"
        f"ADD FILTER PREDICATE [security].[{function}]([{column}]) ON [{schema}].[{name}]\n"
        "WITH (STATE = OFF);\n"
    )
