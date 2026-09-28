import json
from dataclasses import replace
from pathlib import Path

from bqtofabric.cli import main
from bqtofabric.planner import (
    MigrationPlan,
    MigrationWave,
    WaveDecision,
    apply_wave_decisions,
    load_wave_decisions,
)

FIXTURE = Path(__file__).parent / "fixtures" / "gcp_ecosystem_project.json"


def _wave(number: int, *, status: str = "ready_for_review", depends: tuple[int, ...] = ()) -> MigrationWave:
    return MigrationWave(
        wave=number,
        source_ids=(f"p.d.t{number}",),
        target_summary=(("lakehouse", 1),),
        dependency_waves=depends,
        status=status,
        manual_review_count=0,
    )


def _plan(*waves: MigrationWave) -> MigrationPlan:
    return MigrationPlan("p", "lakehouse", (), (), waves)


def _decision(wave: int, decision: str = "approved", **overrides: object) -> WaveDecision:
    return replace(WaveDecision(wave, decision, "team-data", "reviewer-a", "Evidence reviewed."), **overrides)


def test_decisions_update_only_listed_waves() -> None:
    plan = _plan(_wave(1), _wave(2, depends=(1,)), _wave(3))

    updated, errors = apply_wave_decisions(
        plan, (_decision(1, effort_band="L"), _decision(2), _decision(3, "deferred"))
    )

    assert errors == []
    assert [(w.approval_status, w.owner, w.effort_band) for w in updated.waves] == [
        ("approved", "team-data", "L"),
        ("approved", "team-data", "S"),
        ("deferred", "team-data", "S"),
    ]
    assert apply_wave_decisions(plan, ())[0] == plan


def test_blocked_waves_and_unapproved_dependencies_cannot_be_approved() -> None:
    plan = _plan(_wave(1, status="blocked"), _wave(2, depends=(1,)))

    updated, errors = apply_wave_decisions(plan, (_decision(1), _decision(2)))

    assert updated == plan
    assert errors == [
        "wave 1: cannot approve a blocked wave",
        "wave 2: dependency waves [1] are not approved",
    ]
    assert apply_wave_decisions(plan, (_decision(1, "rejected"),))[1] == []


def test_duplicate_and_unknown_waves_fail_closed() -> None:
    plan = _plan(_wave(1))

    updated, errors = apply_wave_decisions(plan, (_decision(1), _decision(1, "deferred"), _decision(9)))

    assert updated == plan
    assert errors == ["wave 1: more than one decision", "wave 9: not in the plan"]


def test_load_reports_every_invalid_entry() -> None:
    decisions, errors = load_wave_decisions({
        "schema_version": "1.0",
        "decisions": [
            {"wave": 1, "decision": "approved", "owner": "a", "reviewer": "b", "rationale": "c"},
            {"wave": 2, "decision": "maybe", "owner": "", "reviewer": "b", "rationale": "c"},
            {"wave": True, "decision": "approved"},
            {"wave": 3, "decision": "deferred", "owner": "a", "reviewer": "b", "rationale": "c",
             "effort_band": "XXL"},
        ],
    })

    assert [item.wave for item in decisions] == [1]
    assert errors == [
        "decisions[1]: decision must be one of approved, deferred, rejected",
        "decisions[1]: missing owner",
        "decisions[2]: wave must be a positive integer",
        "decisions[3]: effort_band must be one of S, M, L, XL",
    ]
    assert load_wave_decisions({"decisions": []})[1] == ["schema_version must be '1.0'"]


def test_cli_rejects_approval_of_blocked_reference_wave(tmp_path: Path) -> None:
    decisions = tmp_path / "wave-decisions.json"
    decisions.write_text(json.dumps({"schema_version": "1.0", "decisions": [
        {"wave": 1, "decision": "approved", "owner": "a", "reviewer": "b", "rationale": "c"},
    ]}), encoding="utf-8")

    code = main(["plan", str(FIXTURE), "--output", str(tmp_path / "out"), "--decisions", str(decisions)])

    assert code == 5
    assert not (tmp_path / "out").exists()


def test_cli_defer_is_recorded_and_hashed(tmp_path: Path) -> None:
    decisions = tmp_path / "wave-decisions.json"
    decisions.write_text(json.dumps({"schema_version": "1.0", "decisions": [
        {"wave": 1, "decision": "deferred", "owner": "team-data", "reviewer": "board",
         "rationale": "Security review pending.", "decided_at": "2026-09-28"},
    ]}), encoding="utf-8")

    assert main(["plan", str(FIXTURE), "--output", str(tmp_path / "base")]) == 0
    assert main([
        "plan", str(FIXTURE), "--output", str(tmp_path / "out"), "--decisions", str(decisions),
    ]) == 0

    base = json.loads((tmp_path / "base" / "migration-plan.json").read_text(encoding="utf-8"))
    out = json.loads((tmp_path / "out" / "migration-plan.json").read_text(encoding="utf-8"))
    signoff = json.loads((tmp_path / "out" / "wave-signoff.json").read_text(encoding="utf-8"))
    manifest = (tmp_path / "out" / "evidence-manifest.json").read_text(encoding="utf-8")

    assert out["waves"][0]["approval_status"] == "deferred"
    assert out["waves"][0]["owner"] == "team-data"
    assert out["waves"][1:] == base["waves"][1:]
    assert signoff["waves"][0]["decision"]["reviewer"] == "board"
    assert "decision" not in signoff["waves"][1]
    assert "wave-decisions.json" in manifest
    assert not (tmp_path / "base" / "wave-decisions.json").exists()
